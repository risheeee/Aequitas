import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import App from './App.tsx'
import './index.css'

const authority = import.meta.env.VITE_KEYCLOAK_AUTHORITY as string | undefined
const clientId = import.meta.env.VITE_KEYCLOAK_CLIENT_ID as string | undefined
const redirectUri = (import.meta.env.VITE_KEYCLOAK_REDIRECT_URI as string | undefined) ?? window.location.origin

if (!authority || !clientId) {
  throw new Error('Missing VITE_KEYCLOAK_AUTHORITY or VITE_KEYCLOAK_CLIENT_ID in frontend environment')
}

const oidcConfig = {
  authority,
  client_id: clientId,
  redirect_uri: redirectUri,
  onSigninCallback: () => {
    window.history.replaceState({}, document.title, window.location.pathname)
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider {...oidcConfig}>
      <App />
    </AuthProvider>
  </StrictMode>,
)