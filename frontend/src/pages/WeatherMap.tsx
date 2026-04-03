import { useEffect, useState, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
    Cloud, Wind, Droplets, Thermometer,
    Activity, Eye, EyeOff, AlertTriangle, CheckCircle, RefreshCw
} from 'lucide-react';

// Fix Leaflet default icon paths broken by Vite
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const OWM_KEY = import.meta.env.VITE_OPENWEATHER_API_KEY || '';
const HAS_OWM = OWM_KEY && OWM_KEY !== 'YOUR_OPENWEATHERMAP_API_KEY_HERE';

const LAYER_DEFS = [
    { id: 'precipitation', label: 'Precipitation', icon: Droplets, color: '#3b82f6', owm: 'precipitation_new' },
    { id: 'clouds', label: 'Clouds', icon: Cloud, color: '#8b5cf6', owm: 'clouds_new' },
    { id: 'wind', label: 'Wind', icon: Wind, color: '#10b981', owm: 'wind_new' },
    { id: 'temp', label: 'Temperature', icon: Thermometer, color: '#f59e0b', owm: 'temp_new' },
];

interface CityWeather {
    name: string; lat: number; lon: number;
    condition: string; description: string; icon: string;
    temp_c: number; wind_kph: number; humidity: number;
    is_storm: boolean; summary: string;
}
interface WorkerLocation {
    worker_id: string; full_name: string; age: number; phone_number: string;
    gps: { lat: number; lng: number } | null;
    last_seen: string | null; fraud_score: number | null; verdict: string | null;
}
interface ClaimMarker {
    id: string; worker_id: string;
    gps_coords: { lat: number; lng: number };
    gap_finder?: { fraud_score: number; verdict: string };
}

const riskColor = (s: number | null) => {
    if (!s || s === 0) return '#6b7280';
    if (s <= 35) return '#22c55e';
    if (s <= 70) return '#f97316';
    return '#ef4444';
};

const dot = (color: string, size = 18) => L.divIcon({
    className: '',
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2.5px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.6);"></div>`,
    iconSize: [size, size], iconAnchor: [size / 2, size / 2], popupAnchor: [0, -(size / 2 + 4)],
});

// Imperatively manages OWM tile layers inside MapContainer
function WeatherTiles({ layers }: { layers: Set<string> }) {
    const map = useMap();
    const refs = useRef<Record<string, L.TileLayer>>({});
    useEffect(() => {
        LAYER_DEFS.forEach(({ id, owm }) => {
            const url = `https://tile.openweathermap.org/map/${owm}/{z}/{x}/{y}.png?appid=${OWM_KEY}`;
            if (layers.has(id)) {
                if (!refs.current[id]) {
                    refs.current[id] = L.tileLayer(url, { opacity: 0.6 });
                    refs.current[id].addTo(map);
                }
            } else {
                if (refs.current[id]) {
                    map.removeLayer(refs.current[id]);
                    delete refs.current[id];
                }
            }
        });
    }, [layers, map]);
    return null;
}

export default function WeatherMap() {
    const [cities, setCities] = useState<CityWeather[]>([]);
    const [workers, setWorkers] = useState<WorkerLocation[]>([]);
    const [claims, setClaims] = useState<ClaimMarker[]>([]);
    const [showClaims, setShowClaims] = useState(false);
    const [activeLayers, setActiveLayers] = useState<Set<string>>(new Set(['precipitation', 'clouds']));
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [loading, setLoading] = useState(true);

    const fetchAll = useCallback(async () => {
        const token = localStorage.getItem('token');
        const headers = { Authorization: `Bearer ${token}` };
        try {
            const [cR, wR, clR] = await Promise.all([
                fetch(`${import.meta.env.VITE_API_URL}/api/weather/cities`, { headers }),
                fetch(`${import.meta.env.VITE_API_URL}/api/workers/locations`, { headers }),
                fetch(`${import.meta.env.VITE_API_URL}/api/claims`, { headers }),
            ]);
            const cd = await cR.json();
            const wd = await wR.json();
            const cld = await clR.json();
            setCities(cd.cities || []);
            setWorkers(wd.workers || []);
            setClaims(Array.isArray(cld) ? cld : []);
            setLastUpdated(new Date());
        } catch (e) {
            console.error('WeatherMap fetch error:', e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAll();
        const t = setInterval(fetchAll, 300000);
        return () => clearInterval(t);
    }, [fetchAll]);

    const toggleLayer = (id: string) => {
        setActiveLayers(prev => {
            const n = new Set(prev);
            n.has(id) ? n.delete(id) : n.add(id);
            return n;
        });
    };

    const stormCities = cities.filter(c => c.is_storm);
    const minutesAgo = lastUpdated ? Math.floor((Date.now() - lastUpdated.getTime()) / 60000) : null;
    const mapCenter: [number, number] = [20.5937, 78.9629];

    if (loading) return (
        <div className="flex items-center justify-center h-screen bg-gray-950 text-gray-400">
            <Activity className="animate-spin mr-3 w-6 h-6" /> Loading Weather Intelligence Matrix...
        </div>
    );

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#030712', overflow: 'hidden' }}>

            {/* ── Storm Alert Banner ── */}
            {stormCities.length > 0 ? (
                <div style={{ background: 'rgba(220,38,38,0.15)', borderBottom: '1px solid #ef4444', padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                    <AlertTriangle style={{ color: '#ef4444', width: 20, height: 20 }} />
                    <span style={{ color: '#ef4444', fontWeight: 700, fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                        ⚡ ACTIVE STORM ZONES DETECTED —&nbsp;
                    </span>
                    <span style={{ color: '#fca5a5', fontSize: 13 }}>
                        Cross-reference worker claims in: <strong>{stormCities.map(c => c.name).join(', ')}</strong>
                    </span>
                </div>
            ) : (
                <div style={{ background: 'rgba(34,197,94,0.08)', borderBottom: '1px solid #16a34a', padding: '8px 20px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                    <CheckCircle style={{ color: '#22c55e', width: 16, height: 16 }} />
                    <span style={{ color: '#4ade80', fontSize: 13, fontWeight: 600 }}>All clear — No active storm zones detected across monitored regions</span>
                </div>
            )}

            {/* ── Main row ── */}
            <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

                {/* ── Map area ── */}
                <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>

                    {/* Layer toggles — top right */}
                    <div style={{ position: 'absolute', top: 12, right: 12, zIndex: 1000, display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {LAYER_DEFS.map(({ id, label, icon: Icon, color }) => {
                            const on = activeLayers.has(id);
                            return (
                                <button key={id} onClick={() => toggleLayer(id)} style={{
                                    display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                                    borderRadius: 8, border: `1px solid ${on ? color : '#374151'}`,
                                    background: on ? `${color}22` : 'rgba(17,24,39,0.92)',
                                    color: on ? color : '#9ca3af',
                                    cursor: 'pointer', fontSize: 12, fontWeight: 600,
                                    backdropFilter: 'blur(8px)', transition: 'all 0.2s',
                                    boxShadow: on ? `0 0 12px ${color}44` : 'none',
                                }}>
                                    <Icon style={{ width: 14, height: 14 }} /> {label}
                                </button>
                            );
                        })}

                        <div style={{ height: 1, background: '#374151', margin: '2px 0' }} />

                        <button onClick={() => setShowClaims(p => !p)} style={{
                            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                            borderRadius: 8, border: `1px solid ${showClaims ? '#f59e0b' : '#374151'}`,
                            background: showClaims ? 'rgba(245,158,11,0.15)' : 'rgba(17,24,39,0.92)',
                            color: showClaims ? '#f59e0b' : '#9ca3af',
                            cursor: 'pointer', fontSize: 12, fontWeight: 600,
                            backdropFilter: 'blur(8px)', transition: 'all 0.2s',
                        }}>
                            {showClaims ? <Eye style={{ width: 14, height: 14 }} /> : <EyeOff style={{ width: 14, height: 14 }} />}
                            Active Claims
                        </button>
                    </div>

                    {/* Header label — top left */}
                    <div style={{ position: 'absolute', top: 12, left: 12, zIndex: 1000, background: 'rgba(17,24,39,0.92)', border: '1px solid #1f2937', borderRadius: 10, padding: '10px 16px', backdropFilter: 'blur(8px)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Cloud style={{ color: '#60a5fa', width: 16, height: 16 }} />
                            <span style={{ color: '#f9fafb', fontWeight: 700, fontSize: 14 }}>Weather Intel</span>
                            {!HAS_OWM && <span style={{ fontSize: 10, background: 'rgba(161,98,7,0.3)', color: '#fbbf24', border: '1px solid #92400e', padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace' }}>MOCK DATA</span>}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                            <RefreshCw style={{ color: '#6b7280', width: 11, height: 11 }} />
                            <span style={{ color: '#9ca3af', fontSize: 11 }}>
                                {minutesAgo === 0 ? 'Just updated' : minutesAgo !== null ? `Updated ${minutesAgo}m ago` : 'Loading...'}
                            </span>
                        </div>
                    </div>

                    {/* Claim legend — bottom left */}
                    {showClaims && (
                        <div style={{ position: 'absolute', bottom: 20, left: 12, zIndex: 1000, background: 'rgba(17,24,39,0.92)', border: '1px solid #1f2937', borderRadius: 10, padding: '12px 16px', backdropFilter: 'blur(8px)' }}>
                            <p style={{ color: '#6b7280', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Claim Verification</p>
                            {[['#22c55e', 'Storm confirmed — genuine signal'], ['#ef4444', 'No weather event — fraud signal']].map(([c, l]) => (
                                <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                    <div style={{ width: 11, height: 11, borderRadius: '50%', background: c, border: '2px solid white' }} />
                                    <span style={{ color: '#d1d5db', fontSize: 11 }}>{l}</span>
                                </div>
                            ))}
                        </div>
                    )}

                    <MapContainer center={mapCenter} zoom={5} style={{ height: '100%', width: '100%' }} zoomControl>
                        {/* CartoDB Dark Matter basemap */}
                        <TileLayer
                            url="https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png"
                            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
                            subdomains={['a', 'b', 'c', 'd'] as any}
                        />

                        {/* OWM overlay layers */}
                        {HAS_OWM && <WeatherTiles layers={activeLayers} />}

                        {/* Worker pins */}
                        {workers.map(w => {
                            if (!w.gps) return null;
                            const color = riskColor(w.fraud_score);
                            return (
                                <Marker key={w.worker_id} position={[w.gps.lat, w.gps.lng]} icon={dot(color)}>
                                    <Popup>
                                        <div style={{ minWidth: 200, fontFamily: 'sans-serif' }}>
                                            <p style={{ fontWeight: 700, fontSize: 14, borderBottom: '1px solid #e5e7eb', paddingBottom: 6, marginBottom: 8 }}>{w.full_name}</p>
                                            <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
                                                <span style={{ fontFamily: 'monospace' }}>{w.worker_id}</span> · Age {w.age}
                                            </p>
                                            <div style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: '8px 10px', marginBottom: 8 }}>
                                                <p style={{ fontSize: 11, color: '#9ca3af', fontWeight: 700, marginBottom: 4, textTransform: 'uppercase' }}>Fraud Status</p>
                                                {w.fraud_score ? (
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                        <span style={{ fontFamily: 'monospace', fontWeight: 700, color }}>Score: {w.fraud_score}/100</span>
                                                        <span style={{ fontSize: 11, background: '#e5e7eb', padding: '2px 6px', borderRadius: 4, fontWeight: 700, textTransform: 'uppercase' }}>{w.verdict?.replace('_', ' ')}</span>
                                                    </div>
                                                ) : <p style={{ fontSize: 12, color: '#9ca3af', fontStyle: 'italic' }}>No active claims</p>}
                                            </div>
                                            {w.last_seen && <p style={{ fontSize: 10, color: '#9ca3af' }}>🕐 {new Date(w.last_seen + 'Z').toLocaleString()}</p>}
                                        </div>
                                    </Popup>
                                </Marker>
                            );
                        })}

                        {/* Claims overlay */}
                        {showClaims && claims.map(c => {
                            const hasStorm = stormCities.some(city => Math.abs(city.lat - c.gps_coords.lat) < 2 && Math.abs(city.lon - c.gps_coords.lng) < 2);
                            const claimColor = hasStorm ? '#22c55e' : '#ef4444';
                            return (
                                <Circle key={c.id} center={[c.gps_coords.lat, c.gps_coords.lng]} radius={6000}
                                    pathOptions={{ color: claimColor, fillColor: claimColor, fillOpacity: 0.25, weight: 1.5 }}>
                                    <Popup>
                                        <div style={{ minWidth: 180, fontFamily: 'sans-serif' }}>
                                            <p style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>Claim {c.id}</p>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                                                <div style={{ width: 10, height: 10, borderRadius: '50%', background: claimColor }} />
                                                <span style={{ fontSize: 12, fontWeight: 600, color: claimColor }}>
                                                    {hasStorm ? '✓ Storm confirmed — likely genuine' : '⚠ No storm detected — investigate'}
                                                </span>
                                            </div>
                                            {c.gap_finder && <p style={{ fontSize: 12, color: '#6b7280' }}>Score: {c.gap_finder.fraud_score}/100 · {c.gap_finder.verdict?.replace('_', ' ')}</p>}
                                        </div>
                                    </Popup>
                                </Circle>
                            );
                        })}
                    </MapContainer>
                </div>

                {/* ── City Weather Sidebar ── */}
                <div style={{ width: 300, borderLeft: '1px solid #1f2937', background: '#0d1117', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{ padding: '16px 18px 12px', borderBottom: '1px solid #1f2937' }}>
                        <h2 style={{ color: '#f9fafb', fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.1em', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Cloud style={{ color: '#60a5fa', width: 14, height: 14 }} /> City Weather Intel
                        </h2>
                        <p style={{ color: '#6b7280', fontSize: 11, marginTop: 4 }}>Major Indian cities — live conditions</p>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto' }}>
                        {cities.map(city => {
                            const alert = city.is_storm;
                            const lBorder = alert ? '#ef4444' : city.condition === 'Clear' ? '#22c55e' : '#1f2937';
                            const bg = alert ? 'rgba(220,38,38,0.07)' : city.condition === 'Clear' ? 'rgba(34,197,94,0.04)' : 'transparent';
                            return (
                                <div key={city.name} style={{ padding: '14px 18px', borderBottom: '1px solid #1f2937', borderLeft: `3px solid ${lBorder}`, background: bg }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                            <img
                                                src={`https://openweathermap.org/img/wn/${city.icon}@2x.png`}
                                                alt={city.condition}
                                                style={{ width: 36, height: 36 }}
                                                onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                            />
                                            <div>
                                                <p style={{ fontWeight: 700, fontSize: 14, color: '#f9fafb' }}>{city.name}</p>
                                                <p style={{ fontSize: 11, color: alert ? '#fca5a5' : '#9ca3af', marginTop: 2 }}>{city.description}</p>
                                            </div>
                                        </div>
                                        <div style={{ textAlign: 'right' }}>
                                            <p style={{ fontSize: 22, fontWeight: 700, color: '#f9fafb', lineHeight: 1 }}>{city.temp_c}°</p>
                                            {alert && <span style={{ fontSize: 10, fontWeight: 700, color: '#ef4444', textTransform: 'uppercase' }}>⚡ STORM</span>}
                                        </div>
                                    </div>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                            <Wind style={{ width: 11, height: 11, color: '#60a5fa' }} />
                                            <span style={{ fontSize: 11, color: '#9ca3af' }}>{city.wind_kph} km/h</span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                            <Droplets style={{ width: 11, height: 11, color: '#818cf8' }} />
                                            <span style={{ fontSize: 11, color: '#9ca3af' }}>{city.humidity}%</span>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                    <div style={{ padding: '10px 18px', borderTop: '1px solid #1f2937', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 11, color: '#4b5563' }}>Auto-refresh every 5 min</span>
                        <button onClick={fetchAll} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer' }}>
                            <RefreshCw style={{ width: 12, height: 12 }} /> Refresh now
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
