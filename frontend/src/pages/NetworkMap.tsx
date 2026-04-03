import { useEffect, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle } from 'react-leaflet';
import L from 'leaflet';
import {
    Radio, Activity, AlertTriangle,
    Signal, RefreshCw
} from 'lucide-react';

// Fix Leaflet icons in Vite
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// ─── Types ──────────────────────────────────────────────────────────────────
interface Tower {
    id: string; lat: number; lng: number;
    operator: string; frequency: string; mcc: number; mnc: number;
}
interface WorkerLocation {
    worker_id: string; full_name: string; age: number; phone_number: string;
    gps: { lat: number; lng: number } | null;
    last_seen: string | null; fraud_score: number | null; verdict: string | null;
}
interface ClaimData {
    id: string; worker_id: string;
    gps_coords: { lat: number; lng: number };
    sensor_data?: { cell_towers_detected?: number };
    environment?: { cell_tower_handoffs?: number };
    gap_finder?: { fraud_score: number; verdict: string };
}
interface WorkerNetworkResult {
    worker: WorkerLocation;
    nearbyCount: number;
    dominantOp: string;
    coverage: 'strong' | 'medium' | 'weak';
    claimedHandoffs: number;
    networkFraudScore: number; // 0-100
    fraudWarning: string | null;
}

// ─── Helpers ────────────────────────────────────────────────────────────────
const OP_COLORS: Record<string, string> = {
    Jio: '#3b82f6', Airtel: '#ef4444', Vi: '#a855f7', BSNL: '#f97316', default: '#6b7280'
};

const towerIcon = (op: string) => L.divIcon({
    className: '',
    html: `<div style="
        width:10px; height:10px; border-radius:2px;
        background:${OP_COLORS[op] || OP_COLORS.default};
        border:1.5px solid rgba(255,255,255,0.4);
        box-shadow: 0 0 6px ${OP_COLORS[op] || OP_COLORS.default}88;
    "></div>`,
    iconSize: [10, 10], iconAnchor: [5, 5], popupAnchor: [0, -8],
});

const workerIcon = (coverage: 'strong' | 'medium' | 'weak') => {
    const color = coverage === 'strong' ? '#22c55e' : coverage === 'medium' ? '#f97316' : '#3b82f6';
    return L.divIcon({
        className: '',
        html: `<div style="
            width:20px; height:20px; border-radius:50%;
            background:${color}; border:3px solid white;
            box-shadow: 0 0 12px ${color}88;
        "></div>`,
        iconSize: [20, 20], iconAnchor: [10, 10], popupAnchor: [0, -14],
    });
};

function calcNetworkFraudScore(nearbyCount: number, claimedHandoffs: number): { score: number; warning: string | null } {
    if (nearbyCount === 0) return { score: 0, warning: null };
    // If claimed 0 handoffs but many towers nearby → suspicious
    if (claimedHandoffs === 0 && nearbyCount >= 5) {
        return {
            score: Math.min(100, 50 + nearbyCount * 5),
            warning: `Worker claims zero handoffs but ${nearbyCount} towers detected nearby.`
        };
    }
    if (claimedHandoffs === 0 && nearbyCount >= 2) {
        return {
            score: 30 + nearbyCount * 5,
            warning: `Worker claims zero handoffs but ${nearbyCount} towers nearby.`
        };
    }
    // Claimed handoffs reasonable vs tower density
    const ratio = claimedHandoffs / Math.max(nearbyCount, 1);
    if (ratio >= 0.3) return { score: 5, warning: null };
    return { score: 15, warning: null };
}

// ─── City coverage zones (for the overlay circles) ──────────────────────────
const CITY_ZONES = [
    { name: 'Mumbai', lat: 19.0760, lng: 72.8777, r: 18000, strong: true },
    { name: 'Delhi', lat: 28.6139, lng: 77.2090, r: 20000, strong: true },
    { name: 'Bangalore', lat: 12.9716, lng: 77.5946, r: 17000, strong: true },
    { name: 'Chennai', lat: 13.0827, lng: 80.2707, r: 16000, strong: true },
    { name: 'Hyderabad', lat: 17.3850, lng: 78.4867, r: 15000, strong: true },
    { name: 'Kolkata', lat: 22.5726, lng: 88.3639, r: 14000, strong: true },
    { name: 'Pune', lat: 18.5204, lng: 73.8567, r: 12000, strong: true },
    { name: 'Ahmedabad', lat: 23.0225, lng: 72.5714, r: 12000, strong: true },
    { name: 'Jaipur', lat: 26.9124, lng: 75.7873, r: 10000, strong: true },
    { name: 'Surat', lat: 21.1702, lng: 72.8311, r: 8000, strong: true },
    { name: 'Lucknow', lat: 26.8467, lng: 80.9462, r: 8000, strong: false },
    { name: 'Patna', lat: 25.5941, lng: 85.1376, r: 7000, strong: false },
    { name: 'Bhopal', lat: 23.2599, lng: 77.4126, r: 7000, strong: false },
    { name: 'Nagpur', lat: 21.1458, lng: 79.0882, r: 7000, strong: false },
    { name: 'Rural Zone A', lat: 22.0000, lng: 74.5000, r: 25000, strong: false },
    { name: 'Rural Zone B', lat: 15.5000, lng: 75.8000, r: 22000, strong: false },
    { name: 'Rural Zone C', lat: 24.0000, lng: 83.0000, r: 20000, strong: false },
];

// ─── Component ──────────────────────────────────────────────────────────────
export default function NetworkMap() {
    const [towers, setTowers] = useState<Tower[]>([]);
    const [workers, setWorkers] = useState<WorkerLocation[]>([]);
    const [claims, setClaims] = useState<ClaimData[]>([]);
    const [workerResults, setWorkerResults] = useState<WorkerNetworkResult[]>([]);
    const [showTowers, setShowTowers] = useState(true);
    const [showZones, setShowZones] = useState(true);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const fetchAll = useCallback(async () => {
        const token = localStorage.getItem('token');
        const headers = { Authorization: `Bearer ${token}` };
        try {
            const [tRes, wRes, cRes] = await Promise.all([
                fetch(`${import.meta.env.VITE_API_URL}/api/network/towers`, { headers }),
                fetch(`${import.meta.env.VITE_API_URL}/api/workers/locations`, { headers }),
                fetch(`${import.meta.env.VITE_API_URL}/api/claims`, { headers }),
            ]);
            const td = await tRes.json();
            const wd = await wRes.json();
            const cd = await cRes.json();

            const allTowers: Tower[] = td.towers || [];
            const allWorkers: WorkerLocation[] = wd.workers || [];
            const allClaims: ClaimData[] = Array.isArray(cd) ? cd : [];

            setTowers(allTowers);
            setWorkers(allWorkers);
            setClaims(allClaims);

            // Compute per-worker network fraud results
            const results: WorkerNetworkResult[] = allWorkers.map(w => {
                if (!w.gps) return {
                    worker: w, nearbyCount: 0, dominantOp: 'N/A',
                    coverage: 'weak', claimedHandoffs: 0, networkFraudScore: 0, fraudWarning: null
                };

                // Count towers within 10km of worker (using frontend Haversine approximation)
                const nearbyTowers = allTowers.filter(t => {
                    const dlat = (t.lat - w.gps!.lat) * 111000;
                    const dlng = (t.lng - w.gps!.lng) * 111000 * Math.cos(w.gps!.lat * Math.PI / 180);
                    return Math.sqrt(dlat * dlat + dlng * dlng) <= 10000;
                });

                const opCount: Record<string, number> = {};
                nearbyTowers.forEach(t => opCount[t.operator] = (opCount[t.operator] || 0) + 1);
                const dominantOp = Object.keys(opCount).sort((a, b) => opCount[b] - opCount[a])[0] || 'None';
                const coverage = nearbyTowers.length >= 15 ? 'strong' : nearbyTowers.length >= 5 ? 'medium' : 'weak';

                // Find claimed handoffs from latest claim
                const wClaim = allClaims.find(c => c.worker_id === w.worker_id);
                const claimedHandoffs = wClaim?.environment?.cell_tower_handoffs
                    ?? wClaim?.sensor_data?.cell_towers_detected ?? 0;

                const { score, warning } = calcNetworkFraudScore(nearbyTowers.length, claimedHandoffs);
                return {
                    worker: w, nearbyCount: nearbyTowers.length, dominantOp,
                    coverage, claimedHandoffs, networkFraudScore: score, fraudWarning: warning
                };
            });

            results.sort((a, b) => b.networkFraudScore - a.networkFraudScore);
            setWorkerResults(results);
            setLastUpdated(new Date());
        } catch (e) {
            console.error('NetworkMap fetch error:', e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAll();
        const t = setInterval(fetchAll, 300000);
        return () => clearInterval(t);
    }, [fetchAll]);

    const mapCenter: [number, number] = [20.5937, 78.9629];

    if (loading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#030712', color: '#9ca3af' }}>
            <Activity style={{ width: 24, height: 24, marginRight: 12, animation: 'spin 1s linear infinite' }} />
            Loading Network Intelligence Matrix...
        </div>
    );

    return (
        <div style={{ display: 'flex', height: '100vh', background: '#030712', overflow: 'hidden' }}>
            {/* ── Map Area ── */}
            <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>

                {/* Header badge */}
                <div style={{ position: 'absolute', top: 12, left: 12, zIndex: 1000, background: 'rgba(17,24,39,0.92)', border: '1px solid #1f2937', borderRadius: 10, padding: '10px 16px', backdropFilter: 'blur(8px)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Radio style={{ color: '#60a5fa', width: 16, height: 16 }} />
                        <span style={{ color: '#f9fafb', fontWeight: 700, fontSize: 14 }}>Network Intelligence</span>
                    </div>
                    <p style={{ color: '#6b7280', fontSize: 11, marginTop: 3 }}>
                        Cell Tower Coverage Map — India
                    </p>
                    <p style={{ color: '#4b5563', fontSize: 10, marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <RefreshCw style={{ width: 10, height: 10 }} />
                        {lastUpdated ? `Updated ${Math.floor((Date.now() - lastUpdated.getTime()) / 60000)}m ago` : 'Loading...'}
                    </p>
                </div>

                {/* Controls — top right */}
                <div style={{ position: 'absolute', top: 12, right: 12, zIndex: 1000, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {[
                        { label: 'Tower Pins', state: showTowers, toggle: () => setShowTowers(p => !p), color: '#3b82f6' },
                        { label: 'Coverage Zones', state: showZones, toggle: () => setShowZones(p => !p), color: '#22c55e' },
                    ].map(({ label, state, toggle, color }) => (
                        <button key={label} onClick={toggle} style={{
                            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                            borderRadius: 8, border: `1px solid ${state ? color : '#374151'}`,
                            background: state ? `${color}22` : 'rgba(17,24,39,0.92)',
                            color: state ? color : '#9ca3af', cursor: 'pointer',
                            fontSize: 12, fontWeight: 600, backdropFilter: 'blur(8px)',
                            boxShadow: state ? `0 0 12px ${color}44` : 'none',
                        }}>
                            <Signal style={{ width: 14, height: 14 }} /> {label}
                        </button>
                    ))}
                </div>

                {/* Operator legend — bottom left */}
                <div style={{ position: 'absolute', bottom: 20, left: 12, zIndex: 1000, background: 'rgba(17,24,39,0.92)', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 16px', backdropFilter: 'blur(8px)' }}>
                    <p style={{ color: '#6b7280', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Network Operators</p>
                    {Object.entries(OP_COLORS).filter(([k]) => k !== 'default').map(([op, color]) => (
                        <div key={op} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                            <div style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
                            <span style={{ fontSize: 11, color: '#d1d5db' }}>{op}</span>
                        </div>
                    ))}
                    <div style={{ borderTop: '1px solid #1f2937', marginTop: 8, paddingTop: 8 }}>
                        <p style={{ color: '#6b7280', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Worker Coverage</p>
                        {[['#22c55e', 'Strong (≥15 towers)'], ['#f97316', 'Medium (5-14)'], ['#3b82f6', 'Weak (<5)']].map(([c, l]) => (
                            <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                <div style={{ width: 12, height: 12, borderRadius: '50%', background: c, border: '2px solid white' }} />
                                <span style={{ fontSize: 11, color: '#d1d5db' }}>{l}</span>
                            </div>
                        ))}
                    </div>
                </div>

                <MapContainer center={mapCenter} zoom={5} style={{ height: '100%', width: '100%' }} zoomControl>
                    <TileLayer
                        url="https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png"
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
                        subdomains={['a', 'b', 'c', 'd'] as any}
                    />

                    {/* Coverage zone circles */}
                    {showZones && CITY_ZONES.map(z => (
                        <Circle key={z.name} center={[z.lat, z.lng]} radius={z.r}
                            pathOptions={{
                                color: z.strong ? '#3b82f6' : '#ef444488',
                                fillColor: z.strong ? '#3b82f6' : '#ef4444',
                                fillOpacity: z.strong ? 0.06 : 0.04,
                                weight: z.strong ? 1.5 : 1,
                                dashArray: z.strong ? undefined : '6 4',
                            }}>
                            <Popup>
                                <div style={{ fontFamily: 'sans-serif', minWidth: 160 }}>
                                    <p style={{ fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{z.name}</p>
                                    <p style={{ fontSize: 12, color: z.strong ? '#2563eb' : '#dc2626', fontWeight: 600 }}>
                                        {z.strong ? '📶 Strong Coverage Zone' : '⚠️ Weak/Rural Zone'}
                                    </p>
                                    <p style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                                        Radius: {(z.r / 1000).toFixed(0)} km from city centre
                                    </p>
                                </div>
                            </Popup>
                        </Circle>
                    ))}

                    {/* Tower pins */}
                    {showTowers && towers.map(t => (
                        <Marker key={t.id} position={[t.lat, t.lng]} icon={towerIcon(t.operator)}>
                            <Popup>
                                <div style={{ fontFamily: 'sans-serif', minWidth: 180 }}>
                                    <p style={{ fontWeight: 700, fontSize: 13, borderBottom: '1px solid #e5e7eb', paddingBottom: 5, marginBottom: 6 }}>
                                        📡 Cell Tower
                                    </p>
                                    <div style={{ fontSize: 12, color: '#374151', lineHeight: 1.8 }}>
                                        <p><b>ID:</b> <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{t.id}</span></p>
                                        <p><b>Operator:</b> <span style={{ color: OP_COLORS[t.operator] || '#000', fontWeight: 700 }}>{t.operator}</span></p>
                                        <p><b>Frequency:</b> {t.frequency}</p>
                                        <p><b>MCC/MNC:</b> {t.mcc}/{t.mnc}</p>
                                        <p><b>GPS:</b> {t.lat.toFixed(5)}, {t.lng.toFixed(5)}</p>
                                    </div>
                                </div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Worker pins with coverage context */}
                    {workerResults.map(r => {
                        if (!r.worker.gps) return null;
                        return (
                            <Marker
                                key={r.worker.worker_id}
                                position={[r.worker.gps.lat, r.worker.gps.lng]}
                                icon={workerIcon(r.coverage)}
                            >
                                <Popup>
                                    <div style={{ fontFamily: 'sans-serif', minWidth: 230 }}>
                                        <p style={{ fontWeight: 700, fontSize: 15, borderBottom: '1px solid #e5e7eb', paddingBottom: 6, marginBottom: 8 }}>
                                            {r.worker.full_name}
                                        </p>
                                        <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
                                            {r.worker.worker_id} · Age {r.worker.age}
                                        </p>

                                        {/* Network stats */}
                                        <div style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: '8px 10px', marginBottom: 10 }}>
                                            <p style={{ fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', marginBottom: 6 }}>Network Analysis</p>
                                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: 12 }}>
                                                <p style={{ color: '#374151' }}><b>Towers nearby:</b></p>
                                                <p style={{ fontFamily: 'monospace', fontWeight: 700, color: '#1d4ed8' }}>{r.nearbyCount}</p>
                                                <p style={{ color: '#374151' }}><b>Dominant op:</b></p>
                                                <p style={{ color: OP_COLORS[r.dominantOp] || '#000', fontWeight: 700 }}>{r.dominantOp}</p>
                                                <p style={{ color: '#374151' }}><b>Coverage:</b></p>
                                                <p style={{ fontWeight: 700, color: r.coverage === 'strong' ? '#16a34a' : r.coverage === 'medium' ? '#ea580c' : '#2563eb' }}>
                                                    {r.coverage.charAt(0).toUpperCase() + r.coverage.slice(1)}
                                                </p>
                                                <p style={{ color: '#374151' }}><b>Claimed handoffs:</b></p>
                                                <p style={{ fontFamily: 'monospace', fontWeight: 700 }}>{r.claimedHandoffs}</p>
                                            </div>
                                        </div>

                                        {/* Fraud warning */}
                                        {r.fraudWarning && (
                                            <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 10px', display: 'flex', gap: 8, marginBottom: 8 }}>
                                                <AlertTriangle style={{ width: 14, height: 14, color: '#ef4444', flexShrink: 0, marginTop: 1 }} />
                                                <p style={{ fontSize: 11, color: '#dc2626', fontWeight: 600 }}>{r.fraudWarning}</p>
                                            </div>
                                        )}

                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                            <p style={{ fontSize: 11, color: '#9ca3af' }}>Network Fraud Score</p>
                                            <span style={{
                                                fontFamily: 'monospace', fontWeight: 700, fontSize: 14,
                                                color: r.networkFraudScore >= 50 ? '#ef4444' : r.networkFraudScore >= 25 ? '#f97316' : '#22c55e'
                                            }}>{r.networkFraudScore}/100</span>
                                        </div>
                                    </div>
                                </Popup>
                            </Marker>
                        );
                    })}
                </MapContainer>
            </div>

            {/* ── Network Fraud Score Sidebar ── */}
            <div style={{ width: 300, borderLeft: '1px solid #1f2937', background: '#0d1117', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ padding: '16px 18px 12px', borderBottom: '1px solid #1f2937' }}>
                    <h2 style={{ color: '#f9fafb', fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.1em', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Signal style={{ color: '#60a5fa', width: 14, height: 14 }} /> Network Fraud Signal
                    </h2>
                    <p style={{ color: '#6b7280', fontSize: 11, marginTop: 4 }}>
                        Workers ranked by handoff vs tower mismatch
                    </p>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {workerResults.map((r, idx) => {
                        const score = r.networkFraudScore;
                        const scoreColor = score >= 50 ? '#ef4444' : score >= 25 ? '#f97316' : '#22c55e';
                        const barWidth = `${score}%`;
                        const coverageColor = r.coverage === 'strong' ? '#22c55e' : r.coverage === 'medium' ? '#f97316' : '#3b82f6';

                        return (
                            <div key={r.worker.worker_id} style={{ padding: '14px 18px', borderBottom: '1px solid #1f2937', background: score >= 50 ? 'rgba(239,68,68,0.04)' : 'transparent' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                                    <div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>#{idx + 1}</span>
                                            <span style={{ fontSize: 13, fontWeight: 700, color: '#f9fafb' }}>{r.worker.full_name}</span>
                                        </div>
                                        <span style={{ fontSize: 10, color: '#6b7280', fontFamily: 'monospace' }}>{r.worker.worker_id}</span>
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                        <span style={{ fontSize: 18, fontWeight: 700, color: scoreColor, fontFamily: 'monospace' }}>{score}</span>
                                        <span style={{ fontSize: 10, color: '#6b7280' }}>/100</span>
                                    </div>
                                </div>

                                {/* Score bar */}
                                <div style={{ height: 4, background: '#1f2937', borderRadius: 2, marginBottom: 8, overflow: 'hidden' }}>
                                    <div style={{ height: '100%', width: barWidth, background: scoreColor, borderRadius: 2, transition: 'width 0.5s ease' }} />
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 8px', fontSize: 11 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: coverageColor }} />
                                        <span style={{ color: '#9ca3af' }}>{r.nearbyCount} towers nearby</span>
                                    </div>
                                    <span style={{ color: '#9ca3af', textAlign: 'right' }}>
                                        {r.claimedHandoffs} claimed
                                    </span>
                                </div>

                                {r.fraudWarning && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6 }}>
                                        <AlertTriangle style={{ width: 11, height: 11, color: '#ef4444', flexShrink: 0 }} />
                                        <span style={{ fontSize: 10, color: '#fca5a5' }}>Handoff anomaly detected</span>
                                    </div>
                                )}

                                {score === 0 && !r.worker.gps && (
                                    <span style={{ fontSize: 10, color: '#4b5563' }}>No GPS data</span>
                                )}
                            </div>
                        );
                    })}
                </div>

                <div style={{ padding: '10px 18px', borderTop: '1px solid #1f2937', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11, color: '#4b5563' }}>{towers.length} towers loaded</span>
                    <button onClick={fetchAll} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer' }}>
                        <RefreshCw style={{ width: 12, height: 12 }} /> Refresh
                    </button>
                </div>
            </div>

            <style>{`
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            `}</style>
        </div>
    );
}
