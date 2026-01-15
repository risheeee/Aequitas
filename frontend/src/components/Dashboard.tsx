import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient'
import { AlertCircle, CheckCircle, ShieldAlert, Lock, FileText, X } from 'lucide-react'
import { useAuth } from 'react-oidc-context'
import RealTimeStats from './RealTimeStats'

// 1. Updated Interface to include the Explanation
interface Decision {
  id: string
  applicant_id: string
  age: number
  race: number
  sex: number
  decision: number
  probability: number
  explanation: string // <--- NEW FIELD
  created_at: string
}

export default function Dashboard() {
  const auth = useAuth()
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [stats, setStats] = useState({ total: 0, denied: 0 })
  
  // 2. State for the Popup Modal
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null)

  useEffect(() => {
    fetchDecisions()
    
    const subscription = supabase
      .channel('realtime:decisions')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'decisions' }, payload => {
        const newDecision = payload.new as Decision
        setDecisions(prev => [newDecision, ...prev].slice(0, 50))
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

  async function testSecureApi() {
    const token = auth.user?.access_token
    if (!token) { alert("No token found."); return }

    try {
      const res = await fetch('http://localhost:8000/secure-test', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        alert(`✅ Backend says: "${data.message}"`)
      } else {
        alert(`❌ Error ${res.status}: Access Denied`)
      }
    } catch (e) { alert("❌ Connection failed.") }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8 relative">
      <div className="max-w-6xl mx-auto">
        
        {/* HEADER */}
        <header className="mb-8 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
              <ShieldAlert className="text-blue-600" /> Aequitas
            </h1>
            <p className="text-gray-500">Real-time Algorithmic Fairness Audit</p>
          </div>

          <div className="flex gap-4 items-center">
            <button 
              onClick={testSecureApi}
              className="flex items-center gap-2 bg-gray-800 text-white px-4 py-2 rounded hover:bg-gray-700 transition shadow"
            >
              <Lock size={16} /> Secure Test
            </button>
            <div className="bg-white p-4 rounded-lg shadow border border-gray-100 text-center min-w-[100px]">
              <p className="text-xs text-gray-500 uppercase font-semibold">Total Logs</p>
              <p className="text-2xl font-bold text-gray-800">{stats.total}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow border border-gray-100 text-center min-w-[100px]">
              <p className="text-xs text-gray-500 uppercase font-semibold">Denial Rate</p>
              <p className="text-2xl font-bold text-red-600">
                {stats.total > 0 ? ((stats.denied / stats.total) * 100).toFixed(1) : 0}%
              </p>
            </div>
          </div>
        </header>

        {/* REAL-TIME HUD */}
        <RealTimeStats />

        {/* TABLE */}
        <div className="bg-white shadow rounded-lg overflow-hidden mt-8">
            <div className="px-6 py-4 border-b border-gray-200">
                <h3 className="text-lg font-medium text-gray-900">Recent Audit Logs</h3>
            </div>
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Applicant ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Demo</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Decision</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
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
                    {/* 3. The View Button */}
                    <button 
                      onClick={() => setSelectedDecision(d)}
                      className="text-blue-600 hover:text-blue-900 flex items-center gap-1 text-xs font-bold uppercase"
                    >
                      <FileText size={14} /> View Report
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4. THE POPUP MODAL */}
      {selectedDecision && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full overflow-hidden transform transition-all">
            
            {/* Modal Header */}
            <div className={`px-6 py-4 border-b ${selectedDecision.decision === 1 ? 'bg-green-50 border-green-100' : 'bg-red-50 border-red-100'} flex justify-between items-center`}>
              <div>
                <h3 className={`text-lg font-bold ${selectedDecision.decision === 1 ? 'text-green-800' : 'text-red-800'}`}>
                  {selectedDecision.decision === 1 ? 'Application Approved' : 'Application Denied'}
                </h3>
                <p className="text-xs text-gray-500">ID: {selectedDecision.applicant_id}</p>
              </div>
              <button onClick={() => setSelectedDecision(null)} className="text-gray-400 hover:text-gray-600">
                <X size={24} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6">
              
              {/* GenAI Explanation Box */}
              <div className="mb-6">
                <h4 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <span className="w-2 h-2 bg-purple-500 rounded-full"></span>
                  AI Generated Explanation
                </h4>
                <div className="bg-gray-50 p-4 rounded-lg border border-gray-200 text-gray-700 italic leading-relaxed">
                  "{selectedDecision.explanation || "No explanation available."}"
                </div>
              </div>

              {/* Technical Details Grid */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="bg-white p-3 border rounded">
                  <span className="block text-xs text-gray-400 uppercase">Confidence Score</span>
                  <span className="font-mono font-bold text-gray-800">
                    {(selectedDecision.probability * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="bg-white p-3 border rounded">
                  <span className="block text-xs text-gray-400 uppercase">Protected Group (Sex)</span>
                  <span className="font-medium text-gray-800">
                    {selectedDecision.sex === 1 ? 'Male' : 'Female'}
                  </span>
                </div>
              </div>

            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 bg-gray-50 border-t flex justify-end">
              <button 
                onClick={() => setSelectedDecision(null)}
                className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded hover:bg-gray-50 transition"
              >
                Close Report
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  )
}