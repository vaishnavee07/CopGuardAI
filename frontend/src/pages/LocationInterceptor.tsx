import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapPin, ShieldAlert } from 'lucide-react';

export default function LocationInterceptor() {
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    useEffect(() => {
        if (!localStorage.getItem('token')) {
            navigate('/');
        }
    }, [navigate]);

    const handleEnable = () => {
        setLoading(true);
        setError('');

        if (!navigator.geolocation) {
            setError('Geolocation is not supported by your browser.');
            setLoading(false);
            return;
        }

        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const { latitude, longitude } = position.coords;
                localStorage.setItem('lat', latitude.toString());
                localStorage.setItem('lon', longitude.toString());

                try {
                    await fetch(`${import.meta.env.VITE_API_URL}/api/auth/update-location`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${localStorage.getItem('token')}`
                        },
                        body: JSON.stringify({ lat: latitude, lng: longitude })
                    });

                    localStorage.setItem('location_granted', 'true');
                    const role = localStorage.getItem('role');
                    navigate(role === 'admin' ? '/dashboard' : '/worker-dashboard');
                } catch (err) {
                    setError('Failed to sync location to server. Please try again.');
                    setLoading(false);
                }
            },
            (geoError) => {
                setError('Location access is required. You cannot use CopGuard without it.');
                setLoading(false);
            }
        );
    };

    const handleDeny = () => {
        setError('Location access is required. You cannot use CopGuard without it.');
    };

    // Development mode: mock location for localhost testing
    const handleMockLocation = async () => {
        setLoading(true);
        const mockLat = 13.0827;
        const mockLon = 80.2707;
        
        localStorage.setItem('lat', mockLat.toString());
        localStorage.setItem('lon', mockLon.toString());
        localStorage.setItem('location_granted', 'true');

        try {
            await fetch(`${import.meta.env.VITE_API_URL}/api/auth/update-location`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                },
                body: JSON.stringify({ lat: mockLat, lng: mockLon })
            });
        } catch (err) {
            console.log('Mock location set (API sync optional for dev)');
        }

        const role = localStorage.getItem('role');
        navigate(role === 'admin' ? '/dashboard' : '/worker-dashboard');
    };

    const isDevelopment = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

    return (
        <div className="min-h-screen bg-gray-950 flex flex-col items-center justify-center p-6 text-gray-100 font-sans">
            <div className="w-full max-w-lg bg-gray-900 border border-gray-800 rounded-xl px-8 py-10 shadow-2xl text-center">

                <div className="flex justify-center mb-6">
                    <div className="bg-blue-500/10 p-4 rounded-full">
                        <MapPin className="text-blue-500 w-12 h-12" />
                    </div>
                </div>

                <h2 className="text-2xl font-bold text-white mb-4">Location Required</h2>

                <p className="text-gray-400 mb-8 leading-relaxed">
                    CopGuard needs your live location to verify claims and detect GPS spoofing. Please enable location access to continue.
                </p>

                {error && (
                    <div className="bg-red-500/10 border border-red-500 text-red-500 px-4 py-3 rounded mb-8 flex items-center justify-center space-x-2">
                        <ShieldAlert className="w-5 h-5" />
                        <span>{error}</span>
                    </div>
                )}

                <div className="flex flex-col space-y-4">
                    <button
                        onClick={handleEnable}
                        disabled={loading}
                        className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-lg transition-colors flex items-center justify-center"
                    >
                        {loading ? 'Obtaining GPS...' : 'Enable Location'}
                    </button>

                    {isDevelopment && (
                        <button
                            onClick={handleMockLocation}
                            disabled={loading}
                            className="w-full bg-green-700 hover:bg-green-800 text-white font-bold py-3 rounded-lg transition-colors flex items-center justify-center"
                        >
                            {loading ? 'Loading...' : '🚀 Skip (Dev Mode)'}
                        </button>
                    )}

                    <button
                        onClick={handleDeny}
                        disabled={loading}
                        className="w-full bg-transparent border border-gray-700 hover:bg-gray-800 text-gray-300 font-semibold py-3 rounded-lg transition-colors"
                    >
                        Deny Access
                    </button>
                </div>
            </div>
        </div>
    );
}
