import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Activity, ShieldAlert } from 'lucide-react';
import type { Claim } from './Dashboard';

export default function SyndicateMap() {
  const [syndicateClusters, setSyndicateClusters] = useState<[string, Claim[]][]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem('token');
    fetch(`${import.meta.env.VITE_API_URL}/api/syndicate`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => {
        if (!res.ok) throw new Error("Failed to fetch syndicate clusters");
        return res.json();
      })
      .then(data => {
        setSyndicateClusters(data);
        setError(null);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError("Failed to load syndicate network map. Ensure the backend is active.");
        setLoading(false);
      });
  }, []);

  return (
    <div className="p-8 space-y-6 bg-gray-950 min-h-screen">
      <header className="pb-4 border-b border-gray-800">
        <h1 className="text-3xl font-extrabold text-white flex items-center"><Network className="w-8 h-8 mr-4 text-purple-500" /> Syndicate Ring Detection</h1>
        <p className="text-gray-400 mt-2">Visually clustering tightly coupled temporal and spatial claims.</p>
      </header>

      {loading ? (
        <div className="p-10 border border-gray-800 rounded-xl text-center">
          <Activity className="w-12 h-12 text-gray-700 mx-auto mb-4 animate-spin" />
          <h2 className="text-xl font-bold text-gray-400">Loading Network Map...</h2>
        </div>
      ) : error ? (
        <div className="p-10 border border-red-900 rounded-xl text-center">
          <ShieldAlert className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-red-500">{error}</h2>
        </div>
      ) : syndicateClusters.length === 0 ? (
        <div className="p-10 border border-gray-800 rounded-xl text-center">
          <Activity className="w-12 h-12 text-gray-700 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-400">No active syndicates detected.</h2>
        </div>
      ) : (
        syndicateClusters.map(([loc, arr]) => (
          <div key={loc} className="bg-gray-900 border border-red-900/50 rounded-xl p-6 shadow-[0_0_15px_rgba(239,68,68,0.1)]">
            <div className="flex items-center justify-between mb-4 border-b border-gray-800 pb-4">
              <div className="flex items-center space-x-3">
                <ShieldAlert className="w-6 h-6 text-red-500" />
                <h3 className="text-lg font-bold text-red-500 uppercase tracking-widest">Cluster at Node {loc}</h3>
              </div>
              <div className="bg-red-900/40 px-3 py-1 rounded text-red-400 text-sm font-bold border border-red-800">
                {arr.length} Linked Nodes
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {arr.map(c => (
                <div key={c.id} onClick={() => navigate(`/claim/${c.id}`)} className="bg-gray-950 p-4 rounded-lg border border-gray-800 cursor-pointer hover:border-red-500/50 transition-colors">
                  <p className="font-mono text-white text-sm mb-1">{c.id}</p>
                  <p className="text-xs text-gray-500">{new Date(c.timestamp).toLocaleTimeString()}</p>
                  <p className="text-xs text-red-400 mt-2 font-bold">Score: {c.gap_finder.fraud_score}</p>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
