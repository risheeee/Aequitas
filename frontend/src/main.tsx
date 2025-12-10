import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import App from './App.tsx'
import './index.css'

const oidcConfig = {
  authority: "http://localhost:8080/realms/Aequitas", // The Keycloak Realm URL
  client_id: "aequitas-frontend", // The Client ID you created
  redirect_uri: window.location.origin, // Returns to localhost:5173 after login
  onSigninCallback: () => {
    // Remove the ugly code from the URL after login
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