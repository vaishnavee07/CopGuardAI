import os
import json
import uuid
import requests
import jwt
import bcrypt
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-copguard-key')

# Enable CORS for the frontend port
CORS(app)

from db import (
    init_db, get_db_connection, subscribe_user, is_subscription_active,
    create_ai_claim, get_all_ai_claims, get_ai_claim_by_id, get_pending_ai_claims,
    update_ai_claim_status, get_claims_by_worker, upsert_worker_risk, get_worker_risk,
    check_duplicate_claim
)
from premium_engine import calculate_premium
from claims_agent import process_worker_state_autonomously
from agentic_engine import process_worker_event, simulate_ai_trigger

# Initialize DB at startup
init_db()

# MOCK_CLAIMS logic removed
claims_db = []

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if Anthropic and os.getenv("ANTHROPIC_API_KEY") else None

@app.route('/api/insurance/subscribe', methods=['POST'])
def subscribe():
    data = request.json

    # Validate input (basic)
    if not all(k in data for k in ("name", "platform", "location")):
        return jsonify({"error": "Missing required fields"}), 400

    # 🔥 Step 0.5 → Premium calculation
    premium_data = calculate_premium(data["location"])

    # 🔥 Step 0 → Subscription
    user = subscribe_user(
        data["name"],
        data["platform"],
        data["location"]
    )

    return jsonify({
        "message": "User subscribed successfully",
        "user": user,
        "insurance": premium_data
    })

def enrich_claims(claims_list):
    if not claims_list:
        return []
        
    conn = get_db_connection()
    users = conn.execute("SELECT id, full_name, age, phone_number, created_at FROM users WHERE role='worker'").fetchall()
    conn.close()
    
    user_map = {f"W-{u['id']}": dict(u) for u in users}
    
    enriched = []
    for c in claims_list:
        cc = dict(c)
        u_info = user_map.get(cc['worker_id'], {})
        cc['worker_name'] = u_info.get('full_name', 'Unknown Worker')
        cc['worker_age'] = u_info.get('age', 'N/A')
        cc['worker_phone'] = u_info.get('phone_number', 'N/A')
        cc['worker_registered_at'] = u_info.get('created_at', 'N/A')
        enriched.append(cc)
    
    return enriched

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['id']
            current_user_role = data['role']
        except Exception as e:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user_id, current_user_role, *args, **kwargs)
    return decorated


@app.route('/api/auth/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ? AND role = 'admin'", (email,)).fetchone()
    conn.close()
    
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        token = jwt.encode({
            'id': user['id'],
            'role': user['role'],
            'exp': datetime.utcnow() + timedelta(days=1)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({'status': 'success', 'token': token, 'role': user['role']})
    
    return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@app.route('/api/auth/worker/login', methods=['POST'])
def worker_login():
    data = request.json
    phone_number = data.get('phone_number')
    password = data.get('password')
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE phone_number = ? AND role = 'worker'", (phone_number,)).fetchone()
    conn.close()
    
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        token = jwt.encode({
            'id': user['id'],
            'role': user['role'],
            'exp': datetime.utcnow() + timedelta(days=1)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({'status': 'success', 'token': token, 'role': user['role']})
    
    return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@app.route('/api/auth/worker/register', methods=['POST'])
def worker_register():
    data = request.json
    full_name = data.get('full_name', '').strip()
    phone_number = str(data.get('phone_number', '')).strip()
    password = data.get('password', '').strip()
    age = data.get('age')
    
    # Validate full name
    if not full_name:
        return jsonify({'status': 'error', 'message': 'Full name is required'}), 400
    
    # Validate password
    if not password or len(password) < 6:
        return jsonify({'status': 'error', 'message': 'Password must be at least 6 characters'}), 400
    
    # Validate age
    try:
        age_int = int(age)
        if age_int < 18 or age_int > 60:
            return jsonify({'status': 'error', 'message': 'Age must be between 18 and 60'}), 400
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Valid age is required'}), 400
    
    # Validate phone number (remove any non-digits, then check length)
    phone_digits = ''.join(filter(str.isdigit, phone_number))
    if len(phone_digits) != 10:
        return jsonify({'status': 'error', 'message': 'Phone number must be exactly 10 digits'}), 400
    
    # Initialize conn to None to prevent UnboundLocalError
    conn = None
    try:
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn = get_db_connection()
        conn.execute("INSERT INTO users (full_name, age, phone_number, password, role) VALUES (?, ?, ?, ?, 'worker')",
                     (full_name, age_int, phone_digits, hashed_pw))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success', 'message': 'Registration successful'})
    except Exception as e:
        if conn:
            conn.close()
        error_msg = str(e).lower()
        if 'unique' in error_msg or 'phone_number' in error_msg:
            return jsonify({'status': 'error', 'message': 'Phone number already registered'}), 400
        return jsonify({'status': 'error', 'message': f'Registration failed: {str(e)}'}), 400

@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_me(user_id, role):
    conn = get_db_connection()
    user = conn.execute("SELECT id, full_name, email, phone_number, role, last_location_lat, last_location_lon FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    return jsonify({'status': 'success', 'user': dict(user)})

@app.route('/api/workers/locations', methods=['GET'])
@token_required
def get_worker_locations(user_id, role):
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
        
    conn = get_db_connection()
    workers = conn.execute("SELECT id, full_name, age, phone_number, last_location_lat, last_location_lon, last_seen FROM users WHERE role='worker'").fetchall()
    conn.close()
    
    locations = []
    for w in workers:
        w_dict = dict(w)
        raw_w_id = str(w_dict['id'])
        w_id = f"W-{w_dict['id']}"
        
        # Check if worker is actively simulated
        active = ACTIVE_WORKERS.get(raw_w_id)
        if active:
            lat = active['route']['current_lat']
            lng = active['route']['current_lng']
        else:
            lat = w_dict['last_location_lat']
            lng = w_dict['last_location_lon']
            
        # Provide default location for workers without GPS data yet
        if not lat or not lng:
            lat = 20.5937  # Center of India
            lng = 78.9629

        fraud_score = 0
        verdict = 'low'
        
        # Get AI score if available from trigger check
        ai_data = TRIGGERED_EVENTS.get(raw_w_id)
        if ai_data and 'ai_result' in ai_data:
            fraud_score = ai_data['ai_result'].get('fraud_score', 0)
            verdict = ai_data['ai_result'].get('verdict', 'low')

        locations.append({
            'worker_id': w_id,
            'full_name': w_dict['full_name'],
            'age': w_dict['age'],
            'phone_number': w_dict['phone_number'],
            'gps': {'lat': lat, 'lng': lng},
            'last_seen': w_dict['last_seen'],
            'fraud_score': fraud_score,
            'verdict': verdict
        })
        
    return jsonify({'status': 'success', 'workers': locations})

@app.route('/api/auth/update-location', methods=['POST'])
@token_required
def update_location(user_id, role):
    data = request.json
    lat = data.get('lat')
    lon = data.get('lng') if 'lng' in data else data.get('lon')
    
    conn = get_db_connection()
    conn.execute("UPDATE users SET last_location_lat = ?, last_location_lon = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?", (lat, lon, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success'})

@app.route('/api/claims/my', methods=['GET'])
@token_required
def get_my_claims(user_id, role):
    target_w_id = f"W-{user_id}"
    my_claims = [c for c in claims_db if c["worker_id"] == target_w_id]
    
    # If the worker has no mock claims, generate one on the fly so they have a baseline
    if not my_claims:
        from mock_data import build_dynamic_claim, INDIAN_CITIES
        import random
        from datetime import datetime
        new_claim = build_dynamic_claim("genuine", datetime.utcnow(), 0, random.choice(INDIAN_CITIES))
        new_claim["worker_id"] = target_w_id
        claims_db.insert(0, new_claim)
        my_claims = [new_claim]
        
    return jsonify(enrich_claims(my_claims))


@app.route('/api/claims', methods=['GET'])
@token_required
def get_claims(user_id, role):
    return jsonify(enrich_claims(claims_db))

@app.route('/api/claims/<id>', methods=['GET'])
@token_required
def get_single_claim(user_id, role, id):
    claim = next((c for c in claims_db if c["id"] == id), None)
    if not claim:
        return jsonify({"status": "error", "message": "Claim not found."}), 404
    return jsonify(enrich_claims([claim])[0])

@app.route('/api/syndicate', methods=['GET'])
@token_required
def get_syndicate_clusters(user_id, role):
    groups = {}
    for c in claims_db:
        key = f"{c['gps_coords']['lat']:.3f},{c['gps_coords']['lng']:.3f}"
        if key not in groups:
            groups[key] = []
        groups[key].append(c)
    
    syndicate_clusters = []
    for loc, arr in groups.items():
        if len(arr) < 5:
            continue
        
        # Sort claims by timestamp
        arr.sort(key=lambda x: x['timestamp'])
        
        # Find 5+ claims within 3 mins (180 seconds)
        from datetime import datetime
        cluster_found = False
        for i in range(len(arr) - 4):
            t1 = datetime.fromisoformat(arr[i]['timestamp'].replace("Z", "+00:00"))
            t5 = datetime.fromisoformat(arr[i+4]['timestamp'].replace("Z", "+00:00"))
            if (t5 - t1).total_seconds() <= 180:
                cluster_found = True
                break
        
        if cluster_found:
            syndicate_clusters.append([loc, enrich_claims(arr)])
            
    return jsonify(syndicate_clusters)

# ── Cell Tower Network Data ─────────────────────────────────────────────────
import math

OPERATORS = ['Jio', 'Airtel', 'Vi', 'BSNL']
FREQUENCIES = ['850 MHz', '900 MHz', '1800 MHz', '2100 MHz', '2300 MHz', '2500 MHz']

def _generate_towers_for_city(city_name, city_lat, city_lon, count, op_weights):
    """Generate realistic tower positions scattered around a city center."""
    import random
    random.seed(int(city_lat * 1000 + city_lon * 1000))  # deterministic per city
    towers = []
    for i in range(count):
        # Scatter towers within ~20km radius
        dlat = (random.random() - 0.5) * 0.36
        dlng = (random.random() - 0.5) * 0.36
        op_idx = random.choices(range(len(OPERATORS)), weights=op_weights)[0]
        towers.append({
            'id': f"T{int(city_lat*10):04d}{int(city_lon*10):04d}{i:03d}",
            'lat': round(city_lat + dlat, 5),
            'lng': round(city_lon + dlng, 5),
            'operator': OPERATORS[op_idx],
            'frequency': random.choice(FREQUENCIES),
            'mcc': 404,
            'mnc': [1, 10, 20, 5][op_idx],
        })
    return towers

# Pre-build the tower dataset at startup
_TOWER_DATASET = []
_CITY_TOWER_CONFIGS = [
    # (name, lat, lon, count, [Jio%, Airtel%, Vi%, BSNL%])
    ("Mumbai",     19.0760, 72.8777, 28, [35, 30, 25, 10]),
    ("Delhi",      28.6139, 77.2090, 30, [33, 32, 22, 13]),
    ("Bangalore",  12.9716, 77.5946, 26, [36, 31, 23, 10]),
    ("Chennai",    13.0827, 80.2707, 24, [34, 29, 24, 13]),
    ("Hyderabad",  17.3850, 78.4867, 22, [35, 30, 20, 15]),
    ("Kolkata",    22.5726, 88.3639, 20, [32, 28, 22, 18]),
    ("Pune",       18.5204, 73.8567, 18, [36, 30, 22, 12]),
    ("Ahmedabad",  23.0225, 72.5714, 16, [34, 31, 20, 15]),
    ("Jaipur",     26.9124, 75.7873, 14, [33, 28, 20, 19]),
    ("Surat",      21.1702, 72.8311, 12, [35, 30, 20, 15]),
    ("Lucknow",    26.8467, 80.9462, 12, [32, 27, 18, 23]),
    ("Patna",      25.5941, 85.1376, 10, [30, 25, 15, 30]),
    ("Bhopal",     23.2599, 77.4126, 10, [33, 28, 20, 19]),
    ("Nagpur",     21.1458, 79.0882, 10, [34, 29, 20, 17]),
    ("Coimbatore", 11.0168, 76.9558,  8, [35, 30, 22, 13]),
    ("Kochi",       9.9312, 76.2673,  8, [34, 29, 22, 15]),
    ("Visakhapatnam",17.6868,83.2185, 8, [33, 28, 18, 21]),
    ("Indore",     22.7196, 75.8577,  8, [34, 29, 20, 17]),
    ("Bhubaneswar",20.2961, 85.8189,  6, [31, 26, 16, 27]),
    ("Chandigarh", 30.7333, 76.7794,  6, [33, 30, 18, 19]),
]

for cfg in _CITY_TOWER_CONFIGS:
    _TOWER_DATASET.extend(_generate_towers_for_city(*cfg))

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.asin(math.sqrt(a))

@app.route('/api/network/towers', methods=['GET'])
@token_required
def get_network_towers(user_id, role):
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', default=500, type=int)

    # Return all towers for map rendering (no lat/lon = full dataset)
    if lat is None or lon is None:
        return jsonify({'status': 'success', 'towers': _TOWER_DATASET, 'total': len(_TOWER_DATASET)})

    # Filter by radius
    nearby = [
        t for t in _TOWER_DATASET
        if _haversine_m(lat, lon, t['lat'], t['lng']) <= radius
    ]
    op_counts = {}
    for t in nearby:
        op_counts[t['operator']] = op_counts.get(t['operator'], 0) + 1
    dominant_op = max(op_counts, key=op_counts.get) if op_counts else 'None'

    coverage = 'strong' if len(nearby) >= 5 else 'medium' if len(nearby) >= 2 else 'weak'

    return jsonify({
        'status': 'success',
        'count': len(nearby),
        'dominant_operator': dominant_op,
        'coverage': coverage,
        'operator_breakdown': op_counts,
        'towers': nearby
    })

# ── Weather cache (5-min TTL) ──────────────────────────────────────────────
_weather_cache = {}  # key: str  →  { 'data': ..., 'ts': float }
WEATHER_TTL = 300    # 5 minutes

STORM_CONDITIONS = {'thunderstorm', 'tornado', 'squall', 'drizzle', 'heavy intensity rain',
                    'very heavy rain', 'extreme rain', 'heavy snow', 'heavy shower rain'}

def _is_storm(condition: str) -> bool:
    c = condition.lower()
    return any(s in c for s in STORM_CONDITIONS)

def _fetch_owm_weather(lat, lon, api_key):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}"
    res = requests.get(url, timeout=6)
    d = res.json()
    condition = d['weather'][0]['main']
    description = d['weather'][0]['description'].title()
    icon = d['weather'][0]['icon']
    temp = round(d['main']['temp'] - 273.15, 1)
    wind_kph = round(d['wind']['speed'] * 3.6, 1)
    humidity = d['main']['humidity']
    return {
        'condition': condition,
        'description': description,
        'icon': icon,
        'temp_c': temp,
        'wind_kph': wind_kph,
        'humidity': humidity,
        'is_storm': _is_storm(condition) or _is_storm(description),
        'summary': f"{description}, {temp}°C, Wind {wind_kph} km/h, Humidity {humidity}%"
    }

@app.route('/api/weather/<lat>/<lon>', methods=['GET'])
@token_required
def get_weather(user_id, role, lat, lon):
    import time
    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    if not api_key or api_key == "YOUR_OPENWEATHERMAP_API_KEY_HERE":
        return jsonify({"status": "success", "data": f"Clear skies, 24°C. (Mocked for {lat}, {lon})",
                        "condition": "Clear", "temp_c": 24, "wind_kph": 10, "humidity": 40, "is_storm": False,
                        "icon": "01d", "description": "Clear Sky"})
    cache_key = f"{float(lat):.3f},{float(lon):.3f}"
    cached = _weather_cache.get(cache_key)
    if cached and (time.time() - cached['ts']) < WEATHER_TTL:
        return jsonify({"status": "success", **cached['data']})
    try:
        w = _fetch_owm_weather(lat, lon, api_key)
        _weather_cache[cache_key] = {'data': w, 'ts': time.time()}
        return jsonify({"status": "success", **w})
    except Exception as e:
        return jsonify({"status": "success", "data": "Weather data unavailable", "is_storm": False})

INDIAN_MAJOR_CITIES = [
    {"name": "Chennai",    "lat": 13.0827, "lon": 80.2707},
    {"name": "Mumbai",     "lat": 19.0760, "lon": 72.8777},
    {"name": "Delhi",      "lat": 28.6139, "lon": 77.2090},
    {"name": "Bangalore",  "lat": 12.9716, "lon": 77.5946},
    {"name": "Hyderabad",  "lat": 17.3850, "lon": 78.4867},
    {"name": "Kolkata",    "lat": 22.5726, "lon": 88.3639},
    {"name": "Pune",       "lat": 18.5204, "lon": 73.8567},
]

_cities_cache = {'data': None, 'ts': 0}

@app.route('/api/weather/cities', methods=['GET'])
@token_required
def get_city_weather(user_id, role):
    import time
    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    now = time.time()
    if _cities_cache['data'] and (now - _cities_cache['ts']) < WEATHER_TTL:
        return jsonify({"status": "success", "cities": _cities_cache['data']})

    results = []
    for city in INDIAN_MAJOR_CITIES:
        entry = dict(city)
        if not api_key or api_key == "YOUR_OPENWEATHERMAP_API_KEY_HERE":
            # Realistic mock data
            entry.update({'condition': 'Clear', 'description': 'Clear Sky', 'icon': '01d',
                          'temp_c': 28, 'wind_kph': 12, 'humidity': 55, 'is_storm': False,
                          'summary': 'Clear Sky, 28°C'})
        else:
            try:
                entry.update(_fetch_owm_weather(city['lat'], city['lon'], api_key))
            except Exception:
                entry.update({'condition': 'Unknown', 'description': 'Unavailable', 'icon': '01d',
                              'temp_c': 0, 'wind_kph': 0, 'humidity': 0, 'is_storm': False,
                              'summary': 'Data unavailable'})
        results.append(entry)

    _cities_cache['data'] = results
    _cities_cache['ts'] = now
    return jsonify({"status": "success", "cities": results})

@app.route('/api/analyse/<id>', methods=['POST'])
@token_required
def analyze_existing_claim(user_id, role, id):
    claim = next((c for c in claims_db if c["id"] == id), None)
    
    if not claim:
        return jsonify({"status": "error", "message": "Claim not found."}), 404

    # CHANGE 7: Attach worker's real GPS coordinates from database 
    conn = get_db_connection()
    try:
        w_id = int(claim['worker_id'].replace('W-', ''))
        db_user = conn.execute("SELECT last_location_lat, last_location_lon FROM users WHERE id = ?", (w_id,)).fetchone()
        if db_user and db_user['last_location_lat'] is not None:
            claim['gps_coords']['lat'] = db_user['last_location_lat']
            claim['gps_coords']['lng'] = db_user['last_location_lon']
    except Exception as em:
        pass
    finally:
        conn.close()

    # Fetch weather for context just before analysis
    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    if api_key and api_key != "YOUR_OPENWEATHERMAP_API_KEY_HERE":
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={claim['gps_coords']['lat']}&lon={claim['gps_coords']['lng']}&appid={api_key}"
            res = requests.get(url, timeout=5)
            data = res.json()
            weather_desc = data['weather'][0]['description'].title()
            claim["environment"]["weather_api_data"] = f"{weather_desc}, {round(data['main']['temp'] - 273.15, 1)}°C"
        except:
            pass

    # Run Gap Finder AI logic
    analysis = run_gap_finder_ai(claim)
    claim["gap_finder"] = analysis
    
    return jsonify({"status": "success", "claim": enrich_claims([claim])[0]})


# =====================================================================
# FEATURE 1 & 2: Worker Active State & Route Simulation Engine
# =====================================================================
import random

# In-memory dictionary to track active workers and their mock routes
# Structure: { user_id_str: { "status": "active", "route": {...} } }
ACTIVE_WORKERS = {}

@app.route('/api/worker/activate', methods=['POST'])
def activate_worker():
    """FEATURE 1: Worker Activation Engine"""
    data = request.json
    user_id = str(data.get("user_id"))
    pickup = data.get("pickup_location", "Unknown Pickup")
    drop = data.get("drop_location", "Unknown Drop")

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    # Generate a simulated route for the worker
    route = {
        "pickup": pickup,
        "drop": drop,
        "distance_km": round(random.uniform(2.0, 10.0), 1),
        "eta_minutes": random.randint(10, 30),
        "start_time": datetime.utcnow().isoformat(),
        "status": "ongoing",
        # Base origin point for simulation later
        "current_lat": 13.0827 + random.uniform(-0.02, 0.02),  # Base: Chennai
        "current_lng": 80.2707 + random.uniform(-0.02, 0.02)
    }

    # Store active state
    ACTIVE_WORKERS[user_id] = {
        "status": "active",
        "route": route
    }

    return jsonify({
        "message": "Worker activated successfully",
        "worker_state": ACTIVE_WORKERS[user_id]
    }), 200

@app.route('/api/worker/status/<user_id>', methods=['GET'])
def get_worker_status(user_id):
    """FEATURE 3: Worker Status API (Enhanced with Feature 1)"""
    user_id = str(user_id)
    
    if user_id in ACTIVE_WORKERS:
        state = ACTIVE_WORKERS[user_id]
        
        # FEATURE 1: Check if trigger exists
        trigger_info = {"active": False}
        if user_id in TRIGGERED_EVENTS:
            evt = TRIGGERED_EVENTS[user_id]
            trigger_info = {
                "active": True,
                "event": evt["event"],
                "condition": evt["condition"],
                "severity": evt["severity"]
            }

        return jsonify({
            "status": state["status"],
            "route": {
                "pickup": state["route"]["pickup"],
                "drop": state["route"]["drop"],
                "distance_km": state["route"]["distance_km"],
                "eta_minutes": state["route"]["eta_minutes"],
                "status": state["route"]["status"]
            },
            "trigger": trigger_info
        }), 200
    
    # Not active
    return jsonify({"status": "idle", "trigger": {"active": False}}), 200

# =====================================================================
# WORKER STATE TRACKING FOR AUTONOMOUS AGENT
# =====================================================================

# Track worker history for movement and inactivity calculations
WORKER_STATE = {}  # { user_id: { "prev_lat", "prev_lng", "last_update", "inactivity_start", ... } }

@app.route('/api/worker/location/<user_id>', methods=['GET'])
def get_worker_location(user_id):
    """FEATURE 4: Worker Location Simulation with Agentic AI Claims Processing"""
    user_id = str(user_id)
    
    if user_id not in ACTIVE_WORKERS:
        return jsonify({"error": "Worker not active or not found"}), 404

    state = ACTIVE_WORKERS[user_id]
    route = state["route"]

    # Simulate minor movement on every poll
    delta_lat = random.uniform(-0.0005, 0.0005)
    delta_lng = random.uniform(-0.0005, 0.0005)
    
    route["current_lat"] += delta_lat
    route["current_lng"] += delta_lng
    
    curr_lat = round(route["current_lat"], 5)
    curr_lng = round(route["current_lng"], 5)

    # ════════════════════════════════════════════════════════════════
    # AGENTIC AI: AUTONOMOUS CLAIM PROCESSING
    # ════════════════════════════════════════════════════════════════
    
    # Initialize worker state if not present
    if user_id not in WORKER_STATE:
        WORKER_STATE[user_id] = {
            "prev_lat": curr_lat,
            "prev_lng": curr_lng,
            "last_update": datetime.utcnow(),
            "prev_update": datetime.utcnow(),
            "inactivity_start": None
        }
    
    worker_state_record = WORKER_STATE[user_id]
    now = datetime.utcnow()
    time_delta = (now - worker_state_record["last_update"]).total_seconds()
    
    # Calculate movement metrics
    import math
    lat_diff = curr_lat - worker_state_record["prev_lat"]
    lng_diff = curr_lng - worker_state_record["prev_lng"]
    distance_m = _haversine_m(
        worker_state_record["prev_lat"], 
        worker_state_record["prev_lng"],
        curr_lat, 
        curr_lng
    )
    
    # Calculate inactivity
    if distance_m < 10:  # Less than 10m movement
        if worker_state_record["inactivity_start"] is None:
            worker_state_record["inactivity_start"] = now
        inactivity_minutes = (now - worker_state_record["inactivity_start"]).total_seconds() / 60
    else:
        worker_state_record["inactivity_start"] = None
        inactivity_minutes = 0
    
    # Update state
    worker_state_record["prev_lat"] = curr_lat
    worker_state_record["prev_lng"] = curr_lng
    worker_state_record["prev_update"] = worker_state_record["last_update"]
    worker_state_record["last_update"] = now
    
    # Prepare data for agentic processing
    movement_data = {
        "distance_traveled_m": distance_m,
        "duration_seconds": time_delta,
        "speed_kmh": (distance_m / max(time_delta, 1)) * 3.6
    }
    
    # Fetch weather data for current location
    weather_data = None
    try:
        api_key = os.getenv("OPENWEATHERMAP_API_KEY")
        if api_key and api_key != "YOUR_OPENWEATHERMAP_API_KEY_HERE":
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={curr_lat}&lon={curr_lng}&appid={api_key}"
            res = requests.get(url, timeout=5)
            w = res.json()
            weather_data = {
                "condition": w.get('weather', [{}])[0].get('main', 'Unknown'),
                "description": w.get('weather', [{}])[0].get('description', 'Unknown'),
                "temp_c": round(w.get('main', {}).get('temp', 0) - 273.15, 1),
                "is_storm": any(
                    keyword in str(w.get('weather', [{}])[0].get('main', '')).lower()
                    for keyword in ['thunderstorm', 'tornado', 'rain', 'snow']
                )
            }
    except Exception as e:
        print(f"[WEATHER FETCH] Error for worker {user_id}: {e}")
    
    # Get actual user_id from database to link to worker
    try:
        actual_user_id = int(user_id) if user_id.isdigit() else None
    except:
        actual_user_id = None
    
    # Process autonomous claim if conditions warrant it
    agent_result = None
    claim_triggered = False
    
    if actual_user_id:
        try:
            agent_result = process_worker_state_autonomously(
                worker_id=f"W-{user_id}",
                user_id=actual_user_id,
                location=(curr_lat, curr_lng),
                movement_data=movement_data,
                weather_data=weather_data,
                inactivity_minutes=inactivity_minutes
            )
            
            claim_triggered = agent_result.get("claim_triggered", False)
            
            if claim_triggered:
                print(f"[AUTONOMOUS CLAIM] Generated for worker {user_id}: {agent_result.get('claim_id')}")
                print(f"  Signals: {agent_result.get('signals')}")
                print(f"  Confidence: {agent_result.get('confidence')}%")
        
        except Exception as e:
            print(f"[AGENT ERROR] Processing worker {user_id}: {e}")

    # FEATURE 2: Auto Trigger Check Hook (existing rain-based system)
    trigger_flag = False
    condition_str = "clear"

    # FEATURE 5: Ensure Idempotency (Don't check if already triggered)
    if user_id in TRIGGERED_EVENTS:
        trigger_flag = True
        condition_str = TRIGGERED_EVENTS[user_id]["condition"]
    else:
        # Run detection
        risk = detect_rain_risk(curr_lat, curr_lng)
        if risk["trigger"]:
            # Store event in TRIGGERED_EVENTS
            TRIGGERED_EVENTS[user_id] = {
                "event": "rain_trigger",
                "condition": risk["condition"],
                "severity": risk["severity"],
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "location": {"lat": curr_lat, "lng": curr_lng}
            }
            trigger_flag = True
            condition_str = risk["condition"]
            # FEATURE 4: Trigger Logging
            print(f"[TRIGGER] Worker {user_id} → {condition_str} detected at {curr_lat},{curr_lng}")
        else:
            # FEATURE 4: Check Logging
            print(f"[CHECK] Worker {user_id} → No risk detected")

    response = {
        "lat": curr_lat,
        "lng": curr_lng,
        "status": "moving",
        "trigger": trigger_flag,
        "condition": condition_str
    }
    
    # Include agent status in response
    if agent_result:
        response["agent"] = {
            "claim_triggered": claim_triggered,
            "claim_id": agent_result.get("claim_id"),
            "distress_detected": agent_result.get("distress_detected"),
            "confidence": agent_result.get("confidence"),
            "signals": agent_result.get("signals", []),
            "action": agent_result.get("action_taken")
        }

    return jsonify(response), 200
# =====================================================================
# STEP 2: Rain Trigger Engine (Parametric Event Detection)
# =====================================================================

# FEATURE 2: Event Storage
TRIGGERED_EVENTS = {}

def detect_rain_risk(lat, lng):
    """FEATURE 1: Weather Risk Detection Function"""
    chance = random.random()  # 0.0 to 1.0
    
    if chance < 0.10:  # 10% chance
        return {
            "condition": "storm",
            "severity": "high",
            "trigger": True
        }
    elif chance < 0.40:  # 30% chance (up to 40%)
        return {
            "condition": "rain",
            "severity": "medium",
            "trigger": True
        }
    else:  # 60% chance
        return {
            "condition": "clear",
            "severity": "low",
            "trigger": False
        }

@app.route('/api/trigger/check/<user_id>', methods=['GET'])
def check_rain_trigger(user_id):
    """FEATURE 3: Trigger Check API"""
    user_id = str(user_id)
    
    # Check if worker is active
    if user_id not in ACTIVE_WORKERS:
        return jsonify({"triggered": False}), 200

    state = ACTIVE_WORKERS[user_id]
    route = state["route"]
    
    # Run risk detection on current coords
    risk = detect_rain_risk(route["current_lat"], route["current_lng"])
    
    if risk["trigger"]:
        event_data = {
            "event": "rain_trigger",
            "condition": risk["condition"],
            "severity": risk["severity"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "location": {
                "lat": round(route["current_lat"], 5),
                "lng": round(route["current_lng"], 5)
            }
        }
        
        # Store event
        TRIGGERED_EVENTS[user_id] = event_data
        
        return jsonify({
            "triggered": True,
            "event": event_data["event"],
            "condition": event_data["condition"],
            "severity": event_data["severity"]
        }), 200

    return jsonify({"triggered": False}), 200

@app.route('/api/trigger/status/<user_id>', methods=['GET'])
def get_trigger_status(user_id):
    """FEATURE 4: Event Status API"""
    user_id = str(user_id)
    
    if user_id in TRIGGERED_EVENTS:
        event = TRIGGERED_EVENTS[user_id]
        return jsonify({
            "event": event["event"],
            "condition": event["condition"],
            "severity": event["severity"],
            "timestamp": event["timestamp"]
        }), 200

    return jsonify({"event": None}), 200

@app.route('/api/trigger/force', methods=['POST'])
def force_trigger():
    """FEATURE 3: Debug Trigger API"""
    data = request.json
    user_id = str(data.get("user_id"))
    condition = data.get("condition", "rain")

    # Force insert trigger
    event_data = {
        "event": "rain_trigger",
        "condition": condition,
        "severity": "high" if condition == "storm" else "medium",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "location": {"lat": 13.0827, "lng": 80.2707} # Default/generic for force
    }

    # If worker is active, use authentic coords
    if user_id in ACTIVE_WORKERS:
        route = ACTIVE_WORKERS[user_id]["route"]
        event_data["location"] = {
            "lat": round(route["current_lat"], 5),
            "lng": round(route["current_lng"], 5)
        }

    TRIGGERED_EVENTS[user_id] = event_data
    print(f"[TRIGGER FORCED] Worker {user_id} → {condition} forced")

    return jsonify({
        "message": "Trigger forced",
        "event": event_data
    }), 200

# =====================================================================
# PART 3 — LIGHTWEIGHT RAG: Fraud Knowledge Base
# =====================================================================

# ADD: Static retrieval knowledge base (no vector DB needed)
FRAUD_KNOWLEDGE_BASE = [
    "Low accelerometer variance indicates spoofing",          # index 0
    "No cell tower handoff suggests stationary device",       # index 1
    "Rain mismatch with location indicates false claim",      # index 2
    "Repeated claims indicate potential fraud pattern"        # index 3
]

def retrieve_context(signals: dict) -> list:
    """ADD: Retrieves relevant fraud context entries based on signal flags."""
    context = []
    if signals.get("accelerometer", 1.0) < 0.1:
        context.append(FRAUD_KNOWLEDGE_BASE[0])
    if not signals.get("network_switch", False):
        context.append(FRAUD_KNOWLEDGE_BASE[1])
    if not signals.get("rain_confirmed", False):
        context.append(FRAUD_KNOWLEDGE_BASE[2])
    if signals.get("repeat_claim", False):
        context.append(FRAUD_KNOWLEDGE_BASE[3])
    return context

# =====================================================================
# PART 2 — SIGNAL-BASED GAP FINDER (no external API dependency)
# =====================================================================

def run_gap_finder_local(claim_data: dict) -> dict:
    """ADD: Rule-based risk scoring from signals. Does NOT touch existing run_gap_finder_ai."""
    signals = claim_data.get("signals", {})
    score = 0
    reasons = []

    # Movement validation
    if signals.get("accelerometer", 1.0) < 0.1:
        score += 30
        reasons.append("Low movement detected")

    # Network validation
    if not signals.get("network_switch", False):
        score += 20
        reasons.append("No network switching")

    # Weather validation
    if not signals.get("rain_confirmed", False):
        score += 25
        reasons.append("No rain detected in region")

    # Behavioral pattern
    if signals.get("repeat_claim", False):
        score += 25
        reasons.append("Repeated claim pattern")

    capped = min(score, 100)
    return {
        "risk_score": capped,
        "reasons": reasons,
        "verdict": "high" if capped > 70 else "medium" if capped > 35 else "low"
    }

# =====================================================================
# DEBUG / VERIFICATION ENDPOINT (PART 4 — AI + RAG combined)
# =====================================================================

@app.route('/api/debug/full-status/<user_id>', methods=['GET'])
def debug_full_status(user_id):
    """Run AI-powered fraud detection using the new run_gap_finder_ai function."""
    user_id = str(user_id)

    worker = ACTIVE_WORKERS.get(user_id)
    if not worker:
        return jsonify({"error": "Worker not active"}), 404

    location = {
        "lat": worker["route"]["current_lat"],
        "lng": worker["route"]["current_lng"]
    }

    # Build a realistic claim object for AI analysis
    claim_data = {
        "gps_coords": location,
        "activity_status": "active",
        "movement_pattern": {
            "distance_travel_meters": random.uniform(50, 500),
            "duration_seconds": random.uniform(30, 300)
        },
        "network_proximity": {
            "towers_in_range": random.randint(1, 8)
        },
        "environment": {
            "weather_api_data": "Clear sky" if random.random() > 0.3 else "Light rain, 28°C"
        }
    }

    # Call the new Claude AI-powered fraud detection
    ai_result = run_gap_finder_ai(claim_data)

    return jsonify({
        "worker": worker,
        "location": location,
        "trigger_check": ai_result,
        "ai": {
            "fraud_score": ai_result.get("fraud_score", 0),
            "risk_level": ai_result.get("verdict", "low"),
            "trigger": ai_result.get("trigger", False),
            "reason": ai_result.get("reason", "No risk detected")
        }
    }), 200



# Lightweight RAG: In-memory fraud pattern knowledge base
FRAUD_PATTERNS = [
    "sudden teleport location change (>100km without movement time)",
    "no network towers nearby but GPS reports movement",
    "bad weather but worker still moving at delivery speed",
    "inactive worker status but sending location updates",
    "repeated identical routes with same timestamps",
    "gps drift beyond typical device error margins",
    "movement speed exceeds vehicle capability"
]

def select_relevant_patterns(claim_data):
    """Select 2-3 relevant fraud patterns based on claim context (lightweight RAG)."""
    selected = []
    
    # Pattern matching logic
    if claim_data.get("activity_status") == "inactive" and claim_data.get("movement_pattern", {}).get("distance_travel_meters", 0) > 100:
        selected.append(FRAUD_PATTERNS[3])  # inactive but moving
    
    weather = claim_data.get("environment", {}).get("weather_api_data", "").lower()
    if any(cond in weather for cond in ["rain", "storm", "thunderstorm", "heavy"]):
        selected.append(FRAUD_PATTERNS[2])  # bad weather context
    
    if not claim_data.get("network_proximity", {}).get("towers_in_range", 0) and claim_data.get("gps_coords"):
        selected.append(FRAUD_PATTERNS[1])  # no towers but gps active
    
    return selected[:3]  # Return max 3 patterns

def run_gap_finder_ai(claim_data):
    """AI-based fraud detection using Claude Haiku with lightweight RAG."""
    
    # Fallback if API not configured
    if not anthropic_client:
        return {
            "fraud_score": 15,
            "trigger": False,
            "verdict": "low",
            "reason": "API unavailable - baseline analysis shows low risk signals."
        }
    
    try:
        # Extract and structure claim data for AI
        ai_input = {
            "location": {
                "lat": claim_data.get("gps_coords", {}).get("lat"),
                "lng": claim_data.get("gps_coords", {}).get("lng")
            },
            "weather": claim_data.get("environment", {}).get("weather_api_data", "unknown"),
            "network": f"towers_nearby: {claim_data.get('network_proximity', {}).get('towers_in_range', 0)}",
            "movement_pattern": f"distance: {claim_data.get('movement_pattern', {}).get('distance_travel_meters', 0)}m, duration: {claim_data.get('movement_pattern', {}).get('duration_seconds', 0)}s",
            "activity_status": claim_data.get("activity_status", "unknown"),
            "context_patterns": select_relevant_patterns(claim_data)
        }
        
        # System prompt for Claude
        SYSTEM_PROMPT = """You are a fraud detection AI analyzing worker activity in a logistics platform.
You must detect anomalies using reasoning, not rules. Analyze the provided signals and return ONLY valid JSON."""
        
        # Build user prompt
        user_prompt = f"""Analyze this worker claim for GPS spoofing or fraud indicators.

Patterns to consider: {', '.join(ai_input['context_patterns'])}

Claim context: {json.dumps(ai_input)}

Return ONLY this JSON with no markdown or extra text:
{{"fraud_score": <0-100>, "risk_level": "low"|"medium"|"high", "trigger": true/false, "reasoning": "<brief explanation>"}}"""
        
        # Call Claude Haiku API
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        # Parse response safely
        text = response.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        ai_output = json.loads(text)
        
        # Return in required format
        return {
            "fraud_score": ai_output.get("fraud_score", 25),
            "trigger": ai_output.get("trigger", False),
            "verdict": ai_output.get("risk_level", "low"),
            "reason": ai_output.get("reasoning", "AI analysis complete.")
        }
        
    except Exception as e:
        # Fallback safety: return conservative safe values on any error
        print(f"AI ERROR: {e}")
        return {
            "fraud_score": 30,
            "trigger": False,
            "verdict": "medium",
            "reason": "AI analysis skipped due to error. Manual review recommended."
        }

# ═══════════════════════════════════════════════════════════════════════════
# ADMIN API: AUTONOMOUS AI CLAIMS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/admin/claims', methods=['GET'])
@token_required
def get_admin_claims(user_id, role):
    """Get all AI-generated autonomous claims."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        claims = get_all_ai_claims()
        
        # Enrich with worker details
        enriched_claims = []
        for claim in claims:
            enriched = dict(claim)
            # Format location
            enriched['location'] = {
                'lat': claim['location_lat'],
                'lng': claim['location_lng']
            }
            enriched_claims.append(enriched)
        
        return jsonify({
            'status': 'success',
            'total': len(enriched_claims),
            'claims': enriched_claims
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Getting admin claims: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/pending', methods=['GET'])
@token_required
def get_pending_claims(user_id, role):
    """Get only pending claims awaiting admin review."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        claims = get_pending_ai_claims()
        
        enriched_claims = []
        for claim in claims:
            enriched = dict(claim)
            enriched['location'] = {
                'lat': claim['location_lat'],
                'lng': claim['location_lng']
            }
            enriched_claims.append(enriched)
        
        return jsonify({
            'status': 'success',
            'pending_count': len(enriched_claims),
            'claims': enriched_claims
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Getting pending claims: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/<claim_id>', methods=['GET'])
@token_required
def get_single_ai_claim(user_id, role, claim_id):
    """Get details of a specific AI-generated claim."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        claim = get_ai_claim_by_id(claim_id)
        
        if not claim:
            return jsonify({'status': 'error', 'message': 'Claim not found'}), 404
        
        # Enrich with location
        claim_data = dict(claim)
        claim_data['location'] = {
            'lat': claim['location_lat'],
            'lng': claim['location_lng']
        }
        
        # Parse detection signals if JSON
        if claim['detection_signals']:
            try:
                claim_data['detection_signals_parsed'] = json.loads(claim['detection_signals'])
            except:
                claim_data['detection_signals_parsed'] = claim['detection_signals']
        
        return jsonify({
            'status': 'success',
            'claim': claim_data
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Getting claim {claim_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/<claim_id>/approve', methods=['POST'])
@token_required
def approve_claim(user_id, role, claim_id):
    """Admin approves a pending claim for insurance payout."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        data = request.json or {}
        admin_notes = data.get('notes', '')
        
        # Update claim status
        updated_claim = update_ai_claim_status(claim_id, 'approved', admin_notes)
        
        if not updated_claim:
            return jsonify({'status': 'error', 'message': 'Claim not found'}), 404
        
        # Log approval
        print(f"[CLAIM APPROVED] {claim_id} by admin {user_id}")
        
        return jsonify({
            'status': 'success',
            'message': 'Claim approved successfully',
            'claim': dict(updated_claim)
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Approving claim {claim_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/<claim_id>/reject', methods=['POST'])
@token_required
def reject_claim(user_id, role, claim_id):
    """Admin rejects a pending claim."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        data = request.json or {}
        admin_notes = data.get('notes', 'No reason provided')
        
        # Update claim status
        updated_claim = update_ai_claim_status(claim_id, 'rejected', admin_notes)
        
        if not updated_claim:
            return jsonify({'status': 'error', 'message': 'Claim not found'}), 404
        
        # Log rejection
        print(f"[CLAIM REJECTED] {claim_id} by admin {user_id}")
        
        return jsonify({
            'status': 'success',
            'message': 'Claim rejected',
            'claim': dict(updated_claim)
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Rejecting claim {claim_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/worker/<worker_id>', methods=['GET'])
@token_required
def get_admin_worker_claims(user_id, role, worker_id):
    """Get all AI-generated claims for a specific worker."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        claims = get_claims_by_worker(worker_id)
        
        enriched_claims = []
        for claim in claims:
            enriched = dict(claim)
            enriched['location'] = {
                'lat': claim['location_lat'],
                'lng': claim['location_lng']
            }
            enriched_claims.append(enriched)
        
        return jsonify({
            'status': 'success',
            'worker_id': worker_id,
            'claim_count': len(enriched_claims),
            'claims': enriched_claims
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Getting claims for worker {worker_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/claims/stats', methods=['GET'])
@token_required
def get_claims_stats(user_id, role):
    """Get statistics on AI-generated claims."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    try:
        all_claims = get_all_ai_claims()
        pending = [c for c in all_claims if c['status'] == 'pending']
        approved = [c for c in all_claims if c['status'] == 'approved']
        rejected = [c for c in all_claims if c['status'] == 'rejected']
        
        # Group by condition
        conditions = {}
        for claim in all_claims:
            condition = claim.get('distress_condition', 'unknown')
            conditions[condition] = conditions.get(condition, 0) + 1
        
        return jsonify({
            'status': 'success',
            'total_claims': len(all_claims),
            'pending': len(pending),
            'approved': len(approved),
            'rejected': len(rejected),
            'conditions': conditions,
            'approval_rate': round(len(approved) / max(len(approved) + len(rejected), 1) * 100, 2)
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Getting claims stats: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════
# AGENTIC AI - WORKER RISK MONITORING & AUTO-CLAIM TRIGGERING
# All claims processing now routes through agentic_engine.py
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/worker/<int:worker_id>/risk', methods=['GET'])
@token_required
def get_worker_risk_status(user_id, role, worker_id):
    """Get current risk score and status for a worker."""
    # For demo, check if user is requesting their own risk
    if user_id != worker_id and role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    
    # Try to fetch from database
    risk_data = get_worker_risk(worker_id)
    
    if risk_data:
        import json
        reasons = json.loads(risk_data.get('reasons', '[]')) if isinstance(risk_data.get('reasons'), str) else risk_data.get('reasons', [])
        return jsonify({
            'status': 'success',
            'risk_score': risk_data['current_risk_score'],
            'risk_level': risk_data['risk_level'],
            'ai_status': risk_data['ai_status'],
            'reasons': reasons,
            'updated_at': risk_data['updated_at']
        }), 200
    
    # Default safe status
    return jsonify({
        'status': 'success',
        'risk_score': 0,
        'risk_level': 'LOW',
        'ai_status': 'SAFE',
        'reasons': [],
        'updated_at': datetime.utcnow().isoformat()
    }), 200


@app.route('/api/worker/<int:worker_id>/risk/update', methods=['POST'])
@token_required
def update_worker_risk(user_id, role, worker_id):
    """Update worker risk score with various signals via Agentic AI pipeline."""
    data = request.json
    
    # Extract signals
    inactivity_minutes = data.get('inactivity_minutes', 0)
    has_movement_anomaly = data.get('has_movement_anomaly', False)
    is_in_danger_zone = data.get('is_in_danger_zone', False)
    location_lat = data.get('location_lat', 0.0)
    location_lng = data.get('location_lng', 0.0)
    
    # Route through Agentic AI processing pipeline
    result = process_worker_event(
        worker_id=worker_id,
        user_id=worker_id,
        location_lat=location_lat,
        location_lng=location_lng,
        inactivity_minutes=inactivity_minutes,
        has_movement_anomaly=has_movement_anomaly,
        is_in_danger_zone=is_in_danger_zone
    )
    
    if result['status'] == 'error':
        return jsonify(result), 500
    
    return jsonify({
        'status': 'success',
        'risk_score': result['risk_score'],
        'risk_level': result['risk_level'],
        'ai_status': result['ai_status'],
        'reasons': result['risk_factors'],
        'claim_triggered': result['claim_triggered'],
        'claim_id': result['claim_id'],
        'decision': result['decision'],
        'message': 'AI processing complete' if not result['claim_triggered'] else 'Emergency detected. AI initiated insurance claim...'
    }), 200


@app.route('/api/worker/<int:worker_id>/claims', methods=['GET'])
@token_required
def get_worker_claims(user_id, role, worker_id):
    """Get all claims for a specific worker with optional filtering."""
    # Ensure user can only see their own claims unless admin
    if user_id != worker_id and role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    
    status_filter = request.args.get('status', 'ALL').upper()
    
    # Fetch all claims for this worker
    all_claims = get_claims_by_worker(f"W-{worker_id}")
    
    # Apply status filter
    if status_filter == 'ALL':
        filtered_claims = all_claims
    elif status_filter in ['PENDING', 'SENT', 'REJECTED']:
        filtered_claims = [c for c in all_claims if c.get('status') == status_filter]
    else:
        return jsonify({'status': 'error', 'message': 'Invalid status filter'}), 400
    
    # Format response
    claims_list = []
    for claim in filtered_claims:
        claims_list.append({
            'claim_id': claim.get('claim_id'),
            'timestamp': claim.get('created_at'),
            'risk_score': claim.get('risk_score', claim.get('ai_confidence', 0)),
            'status': claim.get('status'),
            'reason': claim.get('reason'),
            'location': {
                'lat': claim.get('location_lat'),
                'lng': claim.get('location_lng')
            }
        })
    
    return jsonify({
        'status': 'success',
        'filter': status_filter,
        'total': len(claims_list),
        'claims': claims_list
    }), 200


@app.route('/api/claims/auto-trigger', methods=['POST'])
@token_required
def auto_trigger_claim(user_id, role):
    """Internally called when AI detects high risk and needs to trigger a claim."""
    data = request.json
    
    worker_id = data.get('worker_id')
    risk_score = data.get('risk_score', 75)
    reasons = data.get('reasons', [])
    location_lat = data.get('location_lat', 0)
    location_lng = data.get('location_lng', 0)
    
    # Prevent duplicates
    duplicate = check_duplicate_claim(user_id, time_window_minutes=5)
    if duplicate:
        return jsonify({
            'status': 'success',
            'message': 'Duplicate claim prevented',
            'claim_id': duplicate['claim_id']
        }), 200
    
    import json
    # Create the claim
    claim = create_ai_claim(
        user_id=user_id,
        worker_id=worker_id,
        location_lat=location_lat,
        location_lng=location_lng,
        reason="; ".join(reasons) if isinstance(reasons, list) else reasons,
        distress_condition="AI_EMERGENCY_TRIGGER",
        ai_confidence=min(100, risk_score),
        detection_signals=json.dumps(reasons) if isinstance(reasons, list) else reasons
    )
    
    return jsonify({
        'status': 'success',
        'claim_id': claim['claim_id'],
        'message': 'Emergency claim auto-triggered'
    }), 201


@app.route('/api/claims/<claim_id>/status', methods=['PUT'])
@token_required
def update_claim_status(user_id, role, claim_id):
    """Update claim status (PENDING -> SENT/REJECTED)."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    data = request.json
    new_status = data.get('status', '').upper()
    admin_notes = data.get('admin_notes', '')
    
    if new_status not in ['SENT', 'REJECTED']:
        return jsonify({'status': 'error', 'message': 'Invalid status. Must be SENT or REJECTED'}), 400
    
    # Update the claim
    updated_claim = update_ai_claim_status(claim_id, new_status, admin_notes)
    
    if not updated_claim:
        return jsonify({'status': 'error', 'message': 'Claim not found'}), 404
    
    return jsonify({
        'status': 'success',
        'claim_id': claim_id,
        'new_status': new_status,
        'message': f'Claim status updated to {new_status}'
    }), 200


@app.route('/api/worker/simulate-emergency', methods=['POST'])
@token_required
def simulate_emergency(user_id, role):
    """Simulate emergency via Agentic AI pipeline for demo purposes."""
    data = request.json if request.json else {}
    location_lat = data.get('location_lat', 20.5937)
    location_lng = data.get('location_lng', 78.9629)
    
    # Route through Agentic AI pipeline
    result = simulate_ai_trigger(
        worker_id=user_id,
        user_id=user_id,
        location_lat=location_lat,
        location_lng=location_lng
    )
    
    if result['status'] == 'error':
        return jsonify(result), 500
    
    return jsonify({
        'status': 'success',
        'message': 'Emergency simulated successfully via AI pipeline',
        'risk_score': result['risk_score'],
        'risk_level': result['risk_level'],
        'ai_status': result['ai_status'],
        'reasons': result['risk_factors'],
        'claim_triggered': result['claim_triggered'],
        'claim_id': result['claim_id']
    }), 200


@app.route('/api/simulate-ai-trigger/<int:worker_id>', methods=['POST'])
@token_required
def simulate_ai_trigger_endpoint(user_id, role, worker_id):
    """Test endpoint to simulate high-risk scenario and force AI claim creation."""
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    data = request.json if request.json else {}
    location_lat = data.get('location_lat', 20.5937)
    location_lng = data.get('location_lng', 78.9629)
    
    # Route through Agentic AI pipeline with maximum risk signals
    result = simulate_ai_trigger(
        worker_id=worker_id,
        user_id=worker_id,
        location_lat=location_lat,
        location_lng=location_lng
    )
    
    if result['status'] == 'error':
        return jsonify(result), 500
    
    return jsonify({
        'status': 'success',
        'message': 'AI trigger test completed',
        'worker_id': worker_id,
        'risk_score': result['risk_score'],
        'risk_level': result['risk_level'],
        'ai_status': result['ai_status'],
        'risk_factors': result['risk_factors'],
        'claim_triggered': result['claim_triggered'],
        'claim_id': result['claim_id'],
        'decision': result['decision'],
        'timestamp': result['timestamp']
    }), 200


if __name__ == '__main__':
    # You can specify a different port if needed. Port 5000 is default.
    app.run(port=5000, debug=True)
