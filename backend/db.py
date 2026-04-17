import sqlite3
import os
import bcrypt
from datetime import datetime, timedelta

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')

def get_db_connection():
    """Returns a connection with sqlite3.Row for key-access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------
# INIT DATABASE
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Drop old table (ONLY for development)
    cursor.execute("DROP TABLE IF EXISTS users")

    cursor.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            age INTEGER,
            email TEXT UNIQUE,
            phone_number TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),

            platform TEXT,
            location TEXT,

            is_subscribed INTEGER DEFAULT 0,
            subscription_start TIMESTAMP,
            subscription_end TIMESTAMP,

            last_location_lat REAL,
            last_location_lon REAL,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create AI Claims table
    cursor.execute("DROP TABLE IF EXISTS ai_claims")
    cursor.execute("""
        CREATE TABLE ai_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            location_lat REAL,
            location_lng REAL,
            reason TEXT,
            distress_condition TEXT,
            ai_confidence INTEGER DEFAULT 0,
            risk_score INTEGER DEFAULT 0,
            risk_level TEXT DEFAULT 'LOW' CHECK(risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
            ai_status TEXT DEFAULT 'SAFE' CHECK(ai_status IN ('SAFE', 'WARNING', 'CRITICAL')),
            status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'SENT', 'REJECTED')),
            source TEXT DEFAULT 'AI_GENERATED' CHECK(source IN ('AI_GENERATED', 'MANUAL')),
            detection_signals TEXT,
            admin_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Create worker risk tracking table
    cursor.execute("DROP TABLE IF EXISTS worker_risk_tracking")
    cursor.execute("""
        CREATE TABLE worker_risk_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            current_risk_score INTEGER DEFAULT 0,
            risk_level TEXT DEFAULT 'LOW' CHECK(risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
            ai_status TEXT DEFAULT 'SAFE' CHECK(ai_status IN ('SAFE', 'WARNING', 'CRITICAL')),
            reasons TEXT DEFAULT '[]',
            last_claim_id TEXT,
            last_claim_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Seed Admin
    hashed_admin_pw = bcrypt.hashpw('Admin@123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cursor.execute("""
        INSERT INTO users (full_name, email, password, role)
        VALUES (?, ?, ?, ?)
    """, ('System Admin', 'admin@copguard.com', hashed_admin_pw, 'admin'))

    conn.commit()
    conn.close()


# -----------------------------
# SUBSCRIBE USER (STEP 0)
# -----------------------------
def subscribe_user(name, platform, location):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    start = datetime.utcnow()
    end = start + timedelta(days=7)

    cursor.execute("""
        INSERT INTO users (
            full_name, role, password, platform, location,
            is_subscribed, subscription_start, subscription_end
        )
        VALUES (?, 'worker', 'subscribed_user', ?, ?, 1, ?, ?)
    """, (name, platform, location, start, end))

    user_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "id": user_id,
        "name": name,
        "platform": platform,
        "location": location,
        "subscription_start": str(start),
        "subscription_end": str(end),
        "message": "Subscription activated successfully"
    }


# -----------------------------
# GET USER BY ID
# -----------------------------
def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()

    conn.close()
    return user


# -----------------------------
# UPDATE LAST SEEN
# -----------------------------
def update_last_seen(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET last_seen = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


# -----------------------------
# CHECK ACTIVE SUBSCRIPTION
# -----------------------------
def is_subscription_active(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT subscription_end FROM users WHERE id = ?
    """, (user_id,))

    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        try:
            # End time could be saved as ISO string or something else
            # SQLite format is usually YYYY-MM-DD HH:MM:SS
            end_time = datetime.fromisoformat(result[0])
            return datetime.utcnow() < end_time
        except ValueError:
            # If not ISO, might be standard str(datetime)
            return False

    return False


# ─────────────────────────────────
# AI CLAIMS MANAGEMENT
# ─────────────────────────────────

def create_ai_claim(user_id, worker_id, location_lat, location_lng, reason, distress_condition, ai_confidence, detection_signals=None):
    """Create an autonomous AI-generated claim."""
    import uuid
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    claim_id = f"AIC-{uuid.uuid4().hex[:12].upper()}"
    
    cursor.execute("""
        INSERT INTO ai_claims 
        (claim_id, user_id, worker_id, location_lat, location_lng, reason, distress_condition, ai_confidence, detection_signals, status, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 'AI_GENERATED')
    """, (claim_id, user_id, worker_id, location_lat, location_lng, reason, distress_condition, ai_confidence, detection_signals))
    
    conn.commit()
    claim_row_id = cursor.lastrowid
    conn.close()
    
    return {
        "id": claim_row_id,
        "claim_id": claim_id,
        "user_id": user_id,
        "worker_id": worker_id,
        "status": "PENDING",
        "source": "AI_GENERATED",
        "timestamp": datetime.utcnow().isoformat(),
        "location": {"lat": location_lat, "lng": location_lng},
        "reason": reason,
        "ai_confidence": ai_confidence
    }


def get_all_ai_claims():
    """Retrieve all AI-generated autonomous claims (source='AI_GENERATED')."""
    conn = get_db_connection()
    
    claims = conn.execute("""
        SELECT 
            ac.id, ac.claim_id, ac.user_id, ac.worker_id, ac.timestamp,
            ac.location_lat, ac.location_lng, ac.reason, ac.distress_condition,
            ac.ai_confidence, ac.risk_score, ac.risk_level, ac.ai_status,
            ac.status, ac.source, ac.detection_signals, ac.admin_notes,
            ac.created_at, ac.updated_at,
            u.full_name, u.age, u.phone_number
        FROM ai_claims ac
        LEFT JOIN users u ON ac.user_id = u.id
        WHERE ac.source = 'AI_GENERATED'
        ORDER BY ac.created_at DESC
    """).fetchall()
    
    conn.close()
    
    return [dict(c) for c in claims]


def get_ai_claim_by_id(claim_id):
    """Get a specific AI claim by claim_id."""
    conn = get_db_connection()
    
    claim = conn.execute("""
        SELECT 
            ac.id, ac.claim_id, ac.user_id, ac.worker_id, ac.timestamp,
            ac.location_lat, ac.location_lng, ac.reason, ac.distress_condition,
            ac.ai_confidence, ac.status, ac.detection_signals, ac.admin_notes,
            ac.created_at, ac.updated_at,
            u.full_name, u.age, u.phone_number
        FROM ai_claims ac
        LEFT JOIN users u ON ac.user_id = u.id
        WHERE ac.claim_id = ?
    """, (claim_id,)).fetchone()
    
    conn.close()
    
    return dict(claim) if claim else None


def get_pending_ai_claims():
    """Retrieve only pending AI-GENERATED claims for admin review."""
    conn = get_db_connection()
    
    claims = conn.execute("""
        SELECT 
            ac.id, ac.claim_id, ac.user_id, ac.worker_id, ac.timestamp,
            ac.location_lat, ac.location_lng, ac.reason, ac.distress_condition,
            ac.ai_confidence, ac.risk_score, ac.risk_level, ac.ai_status,
            ac.status, ac.source, ac.detection_signals, ac.admin_notes,
            ac.created_at, ac.updated_at,
            u.full_name, u.age, u.phone_number
        FROM ai_claims ac
        LEFT JOIN users u ON ac.user_id = u.id
        WHERE ac.status = 'PENDING' AND ac.source = 'AI_GENERATED'
        ORDER BY ac.created_at DESC
    """).fetchall()
    
    conn.close()
    
    return [dict(c) for c in claims]


def update_ai_claim_status(claim_id, new_status, admin_notes=None):
    """Update claim status (approved/rejected) with optional admin notes."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE ai_claims 
        SET status = ?, admin_notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE claim_id = ?
    """, (new_status, admin_notes, claim_id))
    
    conn.commit()
    conn.close()
    
    return get_ai_claim_by_id(claim_id)


def get_claims_by_worker(worker_id):
    """Get all AI-GENERATED claims for a specific worker."""
    conn = get_db_connection()
    
    claims = conn.execute("""
        SELECT 
            ac.id, ac.claim_id, ac.user_id, ac.worker_id, ac.timestamp,
            ac.location_lat, ac.location_lng, ac.reason, ac.distress_condition,
            ac.ai_confidence, ac.risk_score, ac.risk_level, ac.ai_status,
            ac.status, ac.source, ac.detection_signals, ac.admin_notes,
            ac.created_at, ac.updated_at,
            u.full_name, u.age, u.phone_number
        FROM ai_claims ac
        LEFT JOIN users u ON ac.user_id = u.id
        WHERE ac.worker_id = ? AND ac.source = 'AI_GENERATED'
        ORDER BY ac.created_at DESC
    """, (worker_id,)).fetchall()
    
    conn.close()
    
    return [dict(c) for c in claims]


# ─────────────────────────────────
# WORKER RISK TRACKING
# ─────────────────────────────────

def upsert_worker_risk(user_id, risk_score, risk_level, ai_status, reasons):
    """Update or create worker risk tracking record."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO worker_risk_tracking 
        (user_id, current_risk_score, risk_level, ai_status, reasons, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        current_risk_score = excluded.current_risk_score,
        risk_level = excluded.risk_level,
        ai_status = excluded.ai_status,
        reasons = excluded.reasons,
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, risk_score, risk_level, ai_status, reasons))
    
    conn.commit()
    conn.close()


def get_worker_risk(user_id):
    """Get current risk status for a worker."""
    conn = get_db_connection()
    
    risk = conn.execute("""
        SELECT 
            user_id, current_risk_score, risk_level, ai_status, reasons,
            last_claim_id, last_claim_time, updated_at
        FROM worker_risk_tracking
        WHERE user_id = ?
    """, (user_id,)).fetchone()
    
    conn.close()
    
    if risk:
        return dict(risk)
    return None


def check_duplicate_claim(user_id, time_window_minutes=5):
    """Check if worker has a claim created within the specified time window."""
    conn = get_db_connection()
    
    cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
    
    claim = conn.execute("""
        SELECT claim_id, created_at FROM ai_claims
        WHERE user_id = ? AND status = 'PENDING' AND created_at > ?
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, cutoff_time)).fetchone()
    
    conn.close()
    
    return dict(claim) if claim else None


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully with mock data.")
