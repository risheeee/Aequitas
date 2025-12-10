import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient'
import { AlertCircle, CheckCircle, ShieldAlert, Lock} from 'lucide-react'
import { useAuth } from 'react-oidc-context' // <--- 1. Import Auth Hook

// Matches the Supabase table structure
interface Decision {
  id: string
  applicant_id: string
  age: number
  race: number
  sex: number
  decision: number
  probability: number
  created_at: string
}

export default function Dashboard() {
  const auth = useAuth() // <--- 2. Get Auth Context
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [stats, setStats] = useState({ total: 0, denied: 0 })

  useEffect(() => {
    fetchDecisions()
    
    // Real-time subscription to the 'decisions' table
    const subscription = supabase
      .channel('realtime:decisions')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'decisions' }, payload => {
        const newDecision = payload.new as Decision
        setDecisions(prev => [newDecision, ...prev].slice(0, 50)) // Keep last 50
        updateStats(newDecision)
      })
      .subscribe()

    return () => { supabase.removeChannel(subscription) }
  }, [])

  const updateStats = (d: Decision) => {
    setStats(prev => ({
      total: prev.total + 1,
      denied: d.decision === 0 ? prev.denied + 1 : prev.denied
    }))
  }

  async function fetchDecisions() {
    const { data, error } = await supabase
      .from('decisions')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(50)
    
    if (error) console.error('Error fetching:', error)
    else {
      setDecisions(data || [])
      const total = data?.length || 0
      const denied = data?.filter(d => d.decision === 0).length || 0
      setStats({ total, denied })
    }
  }

  // <--- 3. New Function to Test Backend Security
  async function testSecureApi() {
    const token = auth.user?.access_token
    
    if (!token) {
      alert("No token found. Are you logged in?")
      return
    }

    try {
      // We call the endpoint we created in main.py
      const res = await fetch('http://localhost:8000/secure-test', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}` // <--- The magic key
        }
      })

      if (res.ok) {
        const data = await res.json()
        alert(`✅ Success!\nBackend says: "${data.message}"\nYour Roles: ${JSON.stringify(data.roles)}`)
      } else {
        alert(`❌ Error ${res.status}: Access Denied`)
      }
    } catch (e) {
      console.error(e)
      alert("❌ Connection failed. Is FastAPI running?")
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto">
        <header className="mb-8 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
              <ShieldAlert className="text-blue-600" /> Aequitas
            </h1>
            <p className="text-gray-500">Real-time Algorithmic Fairness Audit</p>
          </div>

          <div className="flex gap-4 items-center">
            {/* <--- 4. New Security Test Button */}
            <button 
              onClick={testSecureApi}
              className="flex items-center gap-2 bg-gray-800 text-white px-4 py-2 rounded hover:bg-gray-700 transition shadow"
            >
              <Lock size={16} /> Test Secure API
            </button>

            <div className="bg-white p-4 rounded-lg shadow border border-gray-100">
              <p className="text-xs text-gray-500 uppercase font-semibold">Live Events</p>
              <p className="text-2xl font-bold text-gray-800">{stats.total}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow border border-gray-100">
              <p className="text-xs text-gray-500 uppercase font-semibold">Denial Rate</p>
              <p className="text-2xl font-bold text-red-600">
                {stats.total > 0 ? ((stats.denied / stats.total) * 100).toFixed(1) : 0}%
              </p>
            </div>
          </div>
        </header>

        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Applicant ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Demo (Age/Race/Sex)</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Decision</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Confidence</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {decisions.map((d) => (
                <tr key={d.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {new Date(d.created_at).toLocaleTimeString()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-500">
                    {d.applicant_id.split('-')[0]}...
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                    {d.age} / {d.race} / {d.sex}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {d.decision === 1 ? (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        <CheckCircle className="w-3 h-3 mr-1" /> Approved
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        <AlertCircle className="w-3 h-3 mr-1" /> Denied
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {(d.probability * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}