import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient'
import { AlertCircle, CheckCircle, ShieldAlert, Lock, FileText, X } from 'lucide-react'
import { useAuth } from 'react-oidc-context'
import RealTimeStats from './RealTimeStats'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'
const EVIDENCE_MARKER = '[EVIDENCE_JSON]'

interface GroundedFactor {
  feature: string
  label: string
  value: number
  contribution: number
}

interface ExplanationEvidencePayload {
  top_factors?: GroundedFactor[]
  threshold?: number
  model?: string
  version?: string
}

interface BenchmarkModelRow {
  model_name: string
  roc_auc: number
  pr_auc: number
  brier_score: number
  disparate_impact_sex: number
  disparate_impact_race: number
  equal_opportunity_gap_sex: number
  equal_opportunity_gap_race: number
  inference_ms_per_1000: number
  created_at?: string
}

interface BenchmarkPayload {
  status: 'ok' | 'missing'
  source?: 'supabase' | 'csv'
  run_id?: string
  created_at?: string
  best_model?: BenchmarkModelRow
  models?: BenchmarkModelRow[]
  active_model?: {
    name?: string
    path?: string
    run_id?: string
    updated_at?: string
  }
}

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

function extractExplanationParts(rawText?: string): { summary: string; payload: ExplanationEvidencePayload | null } {
  if (!rawText) {
    return { summary: 'No explanation available.', payload: null }
  }

  const markerIndex = rawText.indexOf(EVIDENCE_MARKER)
  if (markerIndex === -1) {
    return { summary: rawText, payload: null }
  }

  const summary = rawText.slice(0, markerIndex).trim()
  const payloadText = rawText.slice(markerIndex + EVIDENCE_MARKER.length).trim()

  try {
    return { summary, payload: JSON.parse(payloadText) as ExplanationEvidencePayload }
  } catch {
    return { summary, payload: null }
  }
}

export default function Dashboard() {
  const auth = useAuth()
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [stats, setStats] = useState({ total: 0, denied: 0 })
  const [benchmark, setBenchmark] = useState<BenchmarkPayload | null>(null)
  const [showModelModal, setShowModelModal] = useState(false)
  const [activatingModel, setActivatingModel] = useState<string | null>(null)
  
  // 2. State for the Popup Modal
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null)

  useEffect(() => {
    fetchDecisions()
    fetchLatestBenchmark()
    
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

  function fairnessRiskLabel(row: BenchmarkModelRow): { label: string; className: string } {
    const dirSexOk = row.disparate_impact_sex >= 0.8
    const dirRaceOk = row.disparate_impact_race >= 0.8
    const eogSexOk = Math.abs(row.equal_opportunity_gap_sex) <= 0.1
    const eogRaceOk = Math.abs(row.equal_opportunity_gap_race) <= 0.1

    const allOk = dirSexOk && dirRaceOk && eogSexOk && eogRaceOk
    const anyOk = dirSexOk || dirRaceOk || eogSexOk || eogRaceOk

    if (allOk) {
      return { label: 'Low Fairness Risk', className: 'bg-green-100 text-green-800' }
    }
    if (anyOk) {
      return { label: 'Medium Fairness Risk', className: 'bg-yellow-100 text-yellow-800' }
    }
    return { label: 'High Fairness Risk', className: 'bg-red-100 text-red-800' }
  }

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

  async function fetchLatestBenchmark() {
    try {
      const response = await fetch(`${apiBaseUrl}/model-benchmarks/latest`)
      const data = (await response.json()) as BenchmarkPayload
      setBenchmark(data)
    } catch (error) {
      console.error('Error fetching benchmark:', error)
      setBenchmark(null)
    }
  }

  async function activateModel(modelName: string) {
    const token = auth.user?.access_token
    if (!token) {
      alert('No auth token available. Please log in again.')
      return
    }

    try {
      setActivatingModel(modelName)
      const response = await fetch(`${apiBaseUrl}/models/activate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          model_name: modelName,
          run_id: benchmark?.run_id ?? null,
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        alert(`Failed to activate model: ${payload?.detail || response.statusText}`)
        return
      }

      alert(`✅ ${payload.message}`)
      await fetchLatestBenchmark()
    } catch (error) {
      console.error('Error activating model:', error)
      alert('Failed to activate model due to a network/server error.')
    } finally {
      setActivatingModel(null)
    }
  }

  async function testSecureApi() {
    const token = auth.user?.access_token
    if (!token) { alert("No token found."); return }

    try {
      const res = await fetch(`${apiBaseUrl}/secure-test`, {
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

        {/* MODEL GOVERNANCE */}
        <div className="bg-white shadow rounded-lg border border-gray-100 p-6 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-gray-900">Model Governance Snapshot</h3>
            <div className="flex items-center gap-4">
              <button
                onClick={() => setShowModelModal(true)}
                className="text-xs font-semibold uppercase text-blue-600 hover:text-blue-800"
              >
                View All Models
              </button>
              <button
                onClick={fetchLatestBenchmark}
                className="text-xs font-semibold uppercase text-blue-600 hover:text-blue-800"
              >
                Refresh
              </button>
            </div>
          </div>

          {benchmark?.status === 'ok' && benchmark.best_model ? (
            (() => {
              const risk = fairnessRiskLabel(benchmark.best_model)
              return (
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4 text-sm">
                  <div className="bg-gray-50 p-4 rounded border">
                    <p className="text-xs text-gray-500 uppercase">Best Model</p>
                    <p className="font-bold text-gray-800 mt-1">{benchmark.best_model.model_name}</p>
                    <p className="text-xs text-gray-500 mt-1">Source: {benchmark.source}</p>
                    {benchmark.active_model?.name && (
                      <p className="text-xs text-gray-500 mt-1">Active: {benchmark.active_model.name}</p>
                    )}
                  </div>
                  <div className="bg-gray-50 p-4 rounded border">
                    <p className="text-xs text-gray-500 uppercase">ROC-AUC / PR-AUC</p>
                    <p className="font-mono font-bold text-gray-800 mt-1">
                      {benchmark.best_model.roc_auc.toFixed(3)} / {benchmark.best_model.pr_auc.toFixed(3)}
                    </p>
                  </div>
                  <div className="bg-gray-50 p-4 rounded border">
                    <p className="text-xs text-gray-500 uppercase">Latency</p>
                    <p className="font-mono font-bold text-gray-800 mt-1">
                      {benchmark.best_model.inference_ms_per_1000.toFixed(2)} ms / 1k
                    </p>
                  </div>
                  <div className="bg-gray-50 p-4 rounded border">
                    <p className="text-xs text-gray-500 uppercase">Fairness Signal</p>
                    <span className={`inline-flex px-2 py-1 rounded text-xs font-semibold mt-1 ${risk.className}`}>
                      {risk.label}
                    </span>
                  </div>
                  <div className="bg-gray-50 p-4 rounded border">
                    <p className="text-xs text-gray-500 uppercase">Last Benchmark</p>
                    <p className="font-medium text-gray-800 mt-1">
                      {benchmark.created_at ? new Date(benchmark.created_at).toLocaleString() : 'Unknown'}
                    </p>
                  </div>
                </div>
              )
            })()
          ) : (
            <p className="text-sm text-gray-500">
              No benchmark data available yet. Run `python backend/benchmark_models.py` to populate governance metrics.
            </p>
          )}
        </div>

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
        (() => {
          const { summary, payload } = extractExplanationParts(selectedDecision.explanation)
          const factors = payload?.top_factors ?? []
          return (
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
                  "{summary}"
                </div>
              </div>

              {factors.length > 0 && (
                <div className="mb-6">
                  <h4 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-2">
                    Grounded Factors
                  </h4>
                  <div className="space-y-2">
                    {factors.map((factor, index) => {
                      const isNegative = factor.contribution < 0
                      return (
                        <div key={`${factor.feature}-${index}`} className="bg-white p-3 border rounded text-sm flex justify-between items-center">
                          <div>
                            <p className="font-medium text-gray-800">{factor.label}</p>
                            <p className="text-xs text-gray-500">Value: {factor.value}</p>
                          </div>
                          <span className={`font-mono font-bold ${isNegative ? 'text-red-600' : 'text-green-700'}`}>
                            {factor.contribution >= 0 ? '+' : ''}{factor.contribution.toFixed(4)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                  {payload?.model && (
                    <p className="text-xs text-gray-500 mt-2">
                      Evidence model: {payload.model}
                    </p>
                  )}
                </div>
              )}

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
          )
        })()
      )}

      {showModelModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-2xl max-w-5xl w-full overflow-hidden">
            <div className="px-6 py-4 border-b flex justify-between items-center">
              <div>
                <h3 className="text-lg font-bold text-gray-900">All Benchmark Models</h3>
                <p className="text-xs text-gray-500">
                  Run: {benchmark?.run_id ?? 'Unknown'}
                </p>
              </div>
              <button onClick={() => setShowModelModal(false)} className="text-gray-400 hover:text-gray-600">
                <X size={24} />
              </button>
            </div>

            <div className="p-6 overflow-auto max-h-[70vh]">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">ROC-AUC</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">PR-AUC</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">DIR (Sex/Race)</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(benchmark?.models ?? []).map((row) => {
                    const isActive = benchmark?.active_model?.name === row.model_name
                    return (
                      <tr key={row.model_name}>
                        <td className="px-4 py-3 font-medium text-gray-800">
                          {row.model_name}
                          {isActive && (
                            <span className="ml-2 inline-flex px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-700">Active</span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono">{row.roc_auc.toFixed(3)}</td>
                        <td className="px-4 py-3 font-mono">{row.pr_auc.toFixed(3)}</td>
                        <td className="px-4 py-3 font-mono">{row.disparate_impact_sex.toFixed(3)} / {row.disparate_impact_race.toFixed(3)}</td>
                        <td className="px-4 py-3 font-mono">{row.inference_ms_per_1000.toFixed(2)} ms</td>
                        <td className="px-4 py-3">
                          <button
                            disabled={isActive || activatingModel === row.model_name}
                            onClick={() => activateModel(row.model_name)}
                            className="px-3 py-1 rounded border border-gray-300 text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
                          >
                            {activatingModel === row.model_name ? 'Activating...' : isActive ? 'Active' : 'Set Active'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {(benchmark?.models ?? []).length === 0 && (
                <p className="text-sm text-gray-500">No models found in benchmark snapshot.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}