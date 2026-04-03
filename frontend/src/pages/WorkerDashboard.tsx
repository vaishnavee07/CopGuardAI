import { useState, useEffect } from 'react';
import { Activity, ShieldAlert, FileText, MapPin, CheckCircle, AlertTriangle, Clock } from 'lucide-react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { getCityFromCoords } from '../utils/geocode';

// Fix Leaflet icon in Vite
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const blueIcon = L.divIcon({
    className: '',
    html: `<div style="width:18px;height:18px;border-radius:50%;background:#3b82f6;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.5);"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -12],
});

export default function WorkerDashboard() {
    const [claims, setClaims] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [myPos, setMyPos] = useState<{ lat: number; lng: number } | null>(null);
    const [myCity, setMyCity] = useState('Locating...');
    const [lastSeen, setLastSeen] = useState<Date | null>(null);

    useEffect(() => {
        const fetchMyClaims = async () => {
            try {
                const token = localStorage.getItem('token');
                const res = await fetch(`${import.meta.env.VITE_API_URL}/api/claims/my`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await res.json();
                setClaims(Array.isArray(data) ? data : []);
                setLoading(false);
            } catch {
                setError('Failed to fetch your data');
                setLoading(false);
            }
        };
        fetchMyClaims();
    }, []);

    // Live location tracking for mini-map
    const updateLocation = () => {
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                const { latitude: lat, longitude: lng } = pos.coords;
                setMyPos({ lat, lng });
                setLastSeen(new Date());
                const city = await getCityFromCoords(lat, lng);
                setMyCity(city);
            },
            () => setMyCity('Location unavailable')
        );
    };

    useEffect(() => {
        updateLocation();
        const interval = setInterval(updateLocation, 60000);
        return () => clearInterval(interval);
    }, []);

    if (loading) return <div className="p-8 flex items-center text-blue-500"><Activity className="animate-spin mr-3" /> Loading your dashboard...</div>;
    if (error) return <div className="text-red-500 p-8">{error}</div>;

    const latestClaim = claims[0];
    const avgScore = claims.length > 0
        ? Math.round(claims.reduce((acc, c) => acc + (c.gap_finder?.fraud_score || 0), 0) / claims.length)
        : 0;

    return (
        <div className="p-8 max-w-7xl mx-auto space-y-8 w-full">
            <div className="flex justify-between items-center mb-8 border-b border-gray-800 pb-6">
                <div>
                    <h2 className="text-2xl font-bold text-white tracking-wide uppercase">Worker Dashboard</h2>
                    <p className="text-gray-400 mt-1">Your personal activity and trust metrics.</p>
                </div>
                <div className="flex items-center space-x-2 bg-green-500/10 border border-green-500/20 px-4 py-2 rounded-lg">
                    <MapPin className="text-green-500 w-5 h-5" />
                    <span className="text-green-500 font-medium text-sm">Location Services Active</span>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {/* Fraud Score */}
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 relative overflow-hidden flex flex-col items-center justify-center min-h-[200px]">
                    <h3 className="text-gray-400 font-medium uppercase text-xs tracking-wider absolute top-6 left-6">My Fraud Risk</h3>
                    <div className="text-5xl font-bold mt-4">
                        <span className={avgScore > 60 ? 'text-red-500' : avgScore > 30 ? 'text-yellow-500' : 'text-green-500'}>
                            {avgScore}
                        </span>
                        <span className="text-gray-600 text-2xl">/100</span>
                    </div>
                    <p className="text-gray-500 text-sm mt-3">Average across {claims.length} claims.</p>
                </div>

                {/* Transparency Report */}
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 lg:col-span-2">
                    <h3 className="text-gray-400 font-medium uppercase text-xs tracking-wider mb-4 flex items-center">
                        <FileText className="w-4 h-4 mr-2" /> My Transparency Report
                    </h3>
                    {latestClaim && latestClaim.gap_finder ? (
                        <div className="bg-gray-950 rounded-lg p-5 border border-gray-800">
                            <p className="text-sm text-gray-300 leading-relaxed mb-4">
                                <span className="text-blue-400 font-semibold">Latest Verdict: </span>
                                {latestClaim.gap_finder.worker_report || 'Pending automated analysis.'}
                            </p>
                            <div className="space-y-3">
                                <div className="flex items-start">
                                    {latestClaim.gap_finder.fraud_score > 50
                                        ? <AlertTriangle className="w-4 h-4 text-red-500 mr-2 mt-0.5 flex-shrink-0" />
                                        : <CheckCircle className="w-4 h-4 text-green-500 mr-2 mt-0.5 flex-shrink-0" />}
                                    <p className="text-xs text-gray-400">{latestClaim.gap_finder.q1_gaps}</p>
                                </div>
                                <div className="flex items-start">
                                    <ShieldAlert className="w-4 h-4 text-gray-500 mr-2 mt-0.5 flex-shrink-0" />
                                    <p className="text-xs text-gray-400">{latestClaim.gap_finder.q2_blindspot}</p>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-gray-500 text-sm py-4">No recent transparency reports available.</div>
                    )}
                </div>
            </div>

            {/* My Location Mini-Map */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
                    <h3 className="text-gray-400 font-medium uppercase text-xs tracking-wider flex items-center">
                        <MapPin className="w-4 h-4 mr-2 text-blue-500" /> My Current Location
                    </h3>
                    {lastSeen && (
                        <span className="text-xs text-gray-500 flex items-center">
                            <Clock className="w-3 h-3 mr-1" />
                            Updated {lastSeen.toLocaleTimeString()}
                        </span>
                    )}
                </div>
                {myPos ? (
                    <>
                        <div style={{ height: 280 }}>
                            <MapContainer
                                center={[myPos.lat, myPos.lng]}
                                zoom={13}
                                style={{ height: '100%', width: '100%' }}
                                zoomControl={false}
                            >
                                <TileLayer
                                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                                />
                                <Marker position={[myPos.lat, myPos.lng]} icon={blueIcon}>
                                    <Popup>📍 You are here</Popup>
                                </Marker>
                            </MapContainer>
                        </div>
                        <div className="px-6 py-4 bg-gray-950 flex items-center justify-between">
                            <div>
                                <p className="text-blue-400 font-semibold text-sm">{myCity}</p>
                                <p className="text-gray-500 text-xs font-mono mt-1">
                                    {myPos.lat.toFixed(5)}, {myPos.lng.toFixed(5)}
                                </p>
                            </div>
                            <div className="flex items-center space-x-2 text-green-400 text-xs font-medium">
                                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                                <span>Live Tracking Active</span>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="p-8 text-center text-gray-500 text-sm">
                        <MapPin className="w-8 h-8 mx-auto mb-2 text-gray-700" />
                        Waiting for GPS signal...
                    </div>
                )}
            </div>

            {/* Claims List */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-gray-400 font-medium uppercase text-xs tracking-wider mb-6">My Claims</h3>
                <div className="space-y-3">
                    {claims.map((claim) => (
                        <div key={claim.id} className="bg-gray-950 rounded-lg p-4 border border-gray-800 flex items-center justify-between hover:border-gray-700 transition-colors">
                            <div className="flex items-center space-x-4">
                                <div className="bg-gray-900 text-gray-400 px-3 py-1.5 rounded font-mono text-sm border border-gray-800">{claim.id}</div>
                                <div className="text-sm text-gray-500">{new Date(claim.timestamp).toLocaleString()}</div>
                            </div>
                            <div className={`px-3 py-1 text-xs font-bold rounded uppercase ${(claim.gap_finder?.fraud_score > 60) ? 'bg-red-500/10 text-red-500 border border-red-500/20' :
                                    (claim.gap_finder?.fraud_score > 30) ? 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/20' :
                                        'bg-green-500/10 text-green-500 border border-green-500/20'
                                }`}>
                                Score: {claim.gap_finder ? claim.gap_finder.fraud_score : 'PENDING'}
                            </div>
                        </div>
                    ))}
                    {claims.length === 0 && <div className="text-gray-500 text-sm py-4">You have no recorded claims.</div>}
                </div>
            </div>
        </div>
    );
}
