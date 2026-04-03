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

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully with mock data.")
