import os
from fastapi import HTTPException, Security, status
from fastapi.security import OpenIdConnect
from jose import jwt, JWTError
import requests
import time
from typing import Any

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8085")
REALM = os.getenv("KEYCLOAK_REALM", "master")
EXPECTED_ISSUER = f"{KEYCLOAK_URL}/realms/{REALM}"
EXPECTED_AUDIENCES = [aud.strip() for aud in os.getenv("KEYCLOAK_AUDIENCES", "aequitas-frontend,account").split(",") if aud.strip()]
CERTS_URL = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs"
JWKS_CACHE_TTL_SECONDS = int(os.getenv("JWKS_CACHE_TTL_SECONDS", "300"))

oauth2_scheme = OpenIdConnect(openIdConnectUrl=f"{KEYCLOAK_URL}/realms/{REALM}/.well-known/openid-configuration")

_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0}


def _get_jwks() -> dict[str, Any]:
    now = time.time()
    if _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < JWKS_CACHE_TTL_SECONDS:
        return {"keys": _jwks_cache["keys"]}

    response = requests.get(CERTS_URL, timeout=5)
    response.raise_for_status()
    jwks = response.json()
    _jwks_cache["keys"] = jwks.get("keys", [])
    _jwks_cache["fetched_at"] = now
    return jwks


def _build_rsa_key(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    unverified_header = jwt.get_unverified_header(token)
    key_id = unverified_header.get("kid")
    for key in jwks.get("keys", []):
        if key.get("kid") == key_id:
            return {
                "kty": key.get("kty"),
                "kid": key.get("kid"),
                "use": key.get("use"),
                "n": key.get("n"),
                "e": key.get("e"),
            }
    return {}

def get_current_user(token: str = Security(oauth2_scheme)):
    try:
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")

        jwks = _get_jwks()
        rsa_key = _build_rsa_key(token, jwks)
        if not rsa_key:
            raise JWTError("Unable to find matching JWKS key")

        last_error: Exception | None = None
        for audience in EXPECTED_AUDIENCES:
            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=EXPECTED_ISSUER,
                    options={"verify_at_hash": False},
                )
                return payload
            except Exception as exc:
                last_error = exc

        if last_error:
            raise last_error
        raise JWTError("Token audience validation failed")

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )