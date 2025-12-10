import os
from fastapi import HTTPException, Security, status
from fastapi.security import OpenIdConnect
from jose import jwt, JWTError
import requests
import json

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
REALM = "Aequitas"
CERTS_URL = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs"

oauth2_scheme = OpenIdConnect(openIdConnectUrl=f"{KEYCLOAK_URL}/realms/{REALM}/.well-known/openid-configuration")

def get_current_user(token: str = Security(oauth2_scheme)):
    try:
        # --- CLEANING ---
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")

        # --- 🕵️ PEEK INSIDE (No Verification) ---
        # We look at the claims BEFORE validating to see what Keycloak sent
        unverified_claims = jwt.get_unverified_claims(token)
        print(f"👀 Token Claims (Audience): {unverified_claims.get('aud')}")

        # 1. Get Keys
        response = requests.get(CERTS_URL)
        jwks = response.json()
        
        # 2. Decode Header
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        
        # 3. Verify Token
        # We explicitly pass the audience we found in the step above
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=unverified_claims.get('aud'), # <--- DYNAMICALLY MATCH AUDIENCE
            options={"verify_at_hash": False}
        )
        
        print(f"✅ SUCCESS: Verified user {payload.get('preferred_username')}")
        return payload

    except Exception as e:
        print(f"❌ AUTH ERROR: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )