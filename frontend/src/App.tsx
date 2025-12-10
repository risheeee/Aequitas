import { useAuth } from 'react-oidc-context'
import Dashboard from './components/Dashboard'

function App() {
  const auth = useAuth()

  // 1. Loading State
  if (auth.isLoading) {
    return <div className="flex h-screen items-center justify-center">Loading authentication...</div>
  }

  // 2. Error State
  if (auth.error) {
    return <div className="text-red-500">Auth Error: {auth.error.message}</div>
  }

  // 3. Authenticated State -> Show Dashboard
  if (auth.isAuthenticated) {
    return (
      <div>
        {/* Simple Logout Bar */}
        <div className="bg-gray-800 text-white p-2 flex justify-between items-center text-sm px-8">
          <span>
            Logged in as: <strong>{auth.user?.profile.preferred_username}</strong>
          </span>
          <button 
            onClick={() => auth.signoutRedirect()}
            className="bg-red-600 px-3 py-1 rounded hover:bg-red-700 transition"
          >
            Log out
          </button>
        </div>
        
        {/* The Main App */}
        <Dashboard />
      </div>
    )
  }

  // 4. Unauthenticated State -> Show Login Button
  return (
    <div className="flex h-screen items-center justify-center bg-gray-100">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-4 text-blue-900">Aequitas</h1>
        <p className="text-gray-600 mb-8">Algorithmic Fairness Audit Platform</p>
        <button 
          onClick={() => auth.signinRedirect()}
          className="bg-blue-600 text-white px-6 py-3 rounded-lg text-lg font-semibold hover:bg-blue-700 transition shadow-lg"
        >
          Log in with SSO
        </button>
      </div>
    </div>
  )
}

export default App