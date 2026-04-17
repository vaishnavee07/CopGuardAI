import { useState, useEffect } from 'react';
import { FileText, Filter, AlertTriangle, CheckCircle, XCircle, Clock, MapPin } from 'lucide-react';

type ClaimStatus = 'ALL' | 'PENDING' | 'SENT' | 'REJECTED';

interface Claim {
  claim_id: string;
  timestamp: string;
  risk_score: number;
  status: 'PENDING' | 'SENT' | 'REJECTED';
  reason: string;
  location: {
    lat: number;
    lng: number;
  };
}

interface ClaimsResponse {
  status: string;
  filter: string;
  total: number;
  claims: Claim[];
}

export default function MyClaimsPanel() {
  const [selectedFilter, setSelectedFilter] = useState<ClaimStatus>('ALL');
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const filters: ClaimStatus[] = ['ALL', 'PENDING', 'SENT', 'REJECTED'];

  const fetchClaims = async (filter: ClaimStatus) => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      const userStr = localStorage.getItem('user');
      if (!userStr) return;

      const user = JSON.parse(userStr);
      const response = await fetch(
        `${import.meta.env.VITE_API_URL}/api/worker/${user.id}/claims?status=${filter}`,
        {
          headers: { 'Authorization': `Bearer ${token}` }
        }
      );

      if (!response.ok) throw new Error('Failed to fetch claims');

      const data: ClaimsResponse = await response.json();
      if (data.status === 'success') {
        setClaims(data.claims);
        setError('');
      }
    } catch (err) {
      setError('Failed to load claims');
      console.error(err);
      setClaims([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClaims(selectedFilter);
    const interval = setInterval(() => fetchClaims(selectedFilter), 10000);
    return () => clearInterval(interval);
  }, [selectedFilter]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'PENDING':
        return <Clock className="w-5 h-5 text-yellow-400" />;
      case 'SENT':
        return <CheckCircle className="w-5 h-5 text-green-400" />;
      case 'REJECTED':
        return <XCircle className="w-5 h-5 text-red-400" />;
      default:
        return <FileText className="w-5 h-5 text-gray-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'PENDING':
        return 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300';
      case 'SENT':
        return 'bg-green-500/10 border-green-500/30 text-green-300';
      case 'REJECTED':
        return 'bg-red-500/10 border-red-500/30 text-red-300';
      default:
        return 'bg-gray-500/10 border-gray-500/30 text-gray-300';
    }
  };

  const getRiskColor = (riskScore: number) => {
    if (riskScore >= 70) return 'text-red-400';
    if (riskScore >= 40) return 'text-yellow-400';
    return 'text-green-400';
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="bg-gradient-to-r from-blue-900/20 to-purple-900/20 border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white tracking-wide uppercase flex items-center gap-2">
              <FileText className="w-5 h-5" />
              My Claims
            </h3>
            <p className="text-sm text-gray-400 mt-1">
              {claims.length} claim{claims.length !== 1 ? 's' : ''} {selectedFilter !== 'ALL' ? `(${selectedFilter})` : ''}
            </p>
          </div>
          <Filter className="w-5 h-5 text-gray-500" />
        </div>
      </div>

      <div className="border-b border-gray-800 px-6 py-4 flex gap-2">
        {filters.map((filter) => (
          <button
            key={filter}
            onClick={() => setSelectedFilter(filter)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              selectedFilter === filter
                ? 'bg-blue-600 text-white border border-blue-500'
                : 'bg-gray-800 text-gray-300 border border-gray-700 hover:bg-gray-700'
            }`}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="p-6">
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-500 border-t-transparent"></div>
            <span className="ml-3 text-gray-400">Loading claims...</span>
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-300">
            {error}
          </div>
        )}

        {!loading && claims.length === 0 && (
          <div className="text-center py-12">
            <FileText className="w-12 h-12 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-400">
              {selectedFilter === 'ALL'
                ? 'No claims yet. Your claims will appear here.'
                : `No ${selectedFilter.toLowerCase()} claims found.`}
            </p>
          </div>
        )}

        {!loading && claims.length > 0 && (
          <div className="space-y-3">
            {claims.map((claim) => (
              <div
                key={claim.claim_id}
                className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 hover:border-gray-600 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-mono text-sm font-bold text-white">
                        {claim.claim_id}
                      </h4>
                      <span className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium border ${getStatusColor(claim.status)}`}>
                        {getStatusIcon(claim.status)}
                        {claim.status}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(claim.timestamp).toLocaleString()}
                    </p>
                  </div>
                </div>

                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm text-gray-400">Risk Score:</span>
                  <span className={`text-lg font-bold ${getRiskColor(claim.risk_score)}`}>
                    {claim.risk_score}/100
                  </span>
                </div>

                {claim.reason && (
                  <div className="bg-gray-900/50 rounded p-3 mb-3">
                    <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">AI Reason</p>
                    <p className="text-sm text-gray-300">{claim.reason}</p>
                  </div>
                )}

                {claim.location && (
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <MapPin className="w-3 h-3" />
                    <span>{claim.location.lat.toFixed(4)}, {claim.location.lng.toFixed(4)}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {!loading && claims.length > 0 && (
        <div className="border-t border-gray-800 bg-gray-800/30 px-6 py-4">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-xs text-gray-500 uppercase">Avg Risk</p>
              <p className="text-lg font-bold text-yellow-400">
                {Math.round(claims.reduce((sum, c) => sum + c.risk_score, 0) / claims.length)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase">High Risk</p>
              <p className="text-lg font-bold text-red-400">
                {claims.filter(c => c.risk_score >= 70).length}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase">Safe</p>
              <p className="text-lg font-bold text-green-400">
                {claims.filter(c => c.risk_score < 40).length}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
