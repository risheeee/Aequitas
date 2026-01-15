import { useEffect, useState } from 'react';

interface Metrics {
  total_processed: number;
  male_approval_rate: number;
  female_approval_rate: number;
  dir_score: number;
  status: string;
}

const RealTimeStats = () => {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  // Poll the API every 2 seconds
  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const response = await fetch('http://localhost:8000/metrics');
        const data = await response.json();
        
        // If the API returns "waiting", don't update state yet
        if (data.status !== "waiting") {
          setMetrics(data);
        }
        setLoading(false);
      } catch (error) {
        console.error("Error fetching metrics:", error);
      }
    };

    // Run immediately, then every 2 seconds
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);

    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="p-4 text-gray-500">Connecting to Live Feed...</div>;
  if (!metrics) return <div className="p-4 text-gray-500">Waiting for traffic...</div>;

  // Color Logic: Red if BIASED, Green if FAIR
  const isFair = metrics.dir_score >= 0.8;
  const statusColor = isFair ? "bg-green-100 text-green-800 border-green-300" : "bg-red-100 text-red-800 border-red-300";
  const statusText = isFair ? "FAIR" : "BIASED DETECTED";

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
      
      {/* CARD 1: The Big Status */}
      <div className={`p-6 rounded-lg border-2 shadow-sm ${statusColor} flex flex-col items-center justify-center`}>
        <h3 className="text-sm font-bold uppercase tracking-wider mb-1">Live Audit Status</h3>
        <span className="text-3xl font-extrabold">{statusText}</span>
        <div className="text-xs mt-2 opacity-75">Updated just now</div>
      </div>

      {/* CARD 2: The DIR Score */}
      <div className="bg-white p-6 rounded-lg border border-gray-200 shadow-sm">
        <h3 className="text-gray-500 text-sm font-medium uppercase">Disparate Impact Ratio</h3>
        <div className="flex items-end mt-2">
          <span className={`text-4xl font-bold ${isFair ? 'text-gray-800' : 'text-red-600'}`}>
            {metrics.dir_score}
          </span>
          <span className="text-gray-400 ml-2 mb-1 text-sm">Target: &gt; 0.80</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2.5 mt-4">
          <div 
            className={`h-2.5 rounded-full ${isFair ? 'bg-blue-600' : 'bg-red-500'}`} 
            style={{ width: `${Math.min(metrics.dir_score * 100, 100)}%` }}
          ></div>
        </div>
      </div>

      {/* CARD 3: Approval Rates */}
      <div className="bg-white p-6 rounded-lg border border-gray-200 shadow-sm">
        <h3 className="text-gray-500 text-sm font-medium uppercase">Approval Rates (Last 100)</h3>
        
        {/* Male Bar */}
        <div className="mt-4">
          <div className="flex justify-between text-xs mb-1">
            <span>Male (Privileged)</span>
            <span>{(metrics.male_approval_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${metrics.male_approval_rate * 100}%` }}></div>
          </div>
        </div>

        {/* Female Bar */}
        <div className="mt-4">
          <div className="flex justify-between text-xs mb-1">
            <span>Female (Unprivileged)</span>
            <span>{(metrics.female_approval_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div className={`h-2 rounded-full ${isFair ? 'bg-blue-500' : 'bg-orange-500'}`} style={{ width: `${metrics.female_approval_rate * 100}%` }}></div>
          </div>
        </div>
      </div>

    </div>
  );
};

export default RealTimeStats;