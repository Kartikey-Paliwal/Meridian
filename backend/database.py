import sqlite3
import json
import os
from datetime import datetime, timedelta
from backend.privacy import encrypt_field, tokenize_identifier

DB_PATH = os.path.join(os.path.dirname(__file__), "meridian.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. medicine_inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS medicine_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        medicine_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        par_level INTEGER DEFAULT 100,
        daily_usage_history TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(phc_id, medicine_name)
    );
    """)

    # 2. bed_status table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bed_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT UNIQUE,
        total_beds INTEGER NOT NULL,
        occupied_beds INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 3. staff_attendance table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        staff_id TEXT NOT NULL,
        staff_id_encrypted TEXT,
        staff_token TEXT,
        present INTEGER NOT NULL,
        date TEXT NOT NULL
    );
    """)

    # 4. patient_footfall table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patient_footfall (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        date TEXT NOT NULL,
        count INTEGER NOT NULL,
        UNIQUE(phc_id, date)
    );
    """)

    # 5. redistribution_transfers table (Human-in-the-loop audit log)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redistribution_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_phc TEXT NOT NULL,
        target_phc TEXT NOT NULL,
        medicine_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        eta_mins INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        underlying_numbers TEXT,
        created_at TEXT NOT NULL
    );
    """)

    conn.commit()

    # Seed initial data if tables are empty
    cursor.execute("SELECT COUNT(*) FROM medicine_inventory")
    if cursor.fetchone()[0] == 0:
        seed_initial_data(cursor)
        conn.commit()

    conn.close()

def seed_initial_data(cursor):
    today = datetime.now()
    
    phcs = [
        {"id": "PHC-001", "name": "Alpha Sector PHC", "district": "District-North", "is_brics": False, "country": "India"},
        {"id": "PHC-002", "name": "Beta Central PHC", "district": "District-North", "is_brics": False, "country": "India"},
        {"id": "PHC-003", "name": "Gamma Rural PHC", "district": "District-South", "is_brics": True, "country": "Brazil (Simulated)"},
        {"id": "PHC-004", "name": "Delta Community PHC", "district": "District-South", "is_brics": True, "country": "South Africa (Simulated)"}
    ]

    medicines = ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg", "Insulin Vials", "Zinc Supplements"]

    # 1. Seed Medicine Inventory (with 14 days of realistic usage history)
    # PHC-001 has a sudden outbreak spike leading to near stock-out for ORS & Paracetamol
    for phc in phcs:
        p_id = phc["id"]
        for med in medicines:
            if p_id == "PHC-001" and med == "ORS Packets":
                current_qty = 15  # Very low stock! Par level 100
                daily_usage = [12, 14, 15, 18, 22, 28, 35, 40, 42, 45, 48, 52, 55, 60] # Spiking
            elif p_id == "PHC-001" and med == "Paracetamol 500mg":
                current_qty = 25  # Low stock
                daily_usage = [10, 12, 11, 14, 16, 20, 22, 25, 27, 30, 32, 35, 38, 40]
            elif p_id == "PHC-002" and med == "ORS Packets":
                current_qty = 320 # High Surplus!
                daily_usage = [10, 8, 9, 11, 10, 9, 10, 12, 11, 10, 9, 8, 10, 11]
            elif p_id == "PHC-002" and med == "Paracetamol 500mg":
                current_qty = 280 # Surplus
                daily_usage = [15, 14, 16, 15, 14, 15, 16, 15, 14, 15, 14, 15, 16, 15]
            else:
                current_qty = 120
                daily_usage = [8, 9, 10, 8, 9, 10, 9, 8, 10, 9, 8, 9, 10, 9]

            cursor.execute("""
            INSERT INTO medicine_inventory (phc_id, medicine_name, quantity, par_level, daily_usage_history, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (p_id, med, current_qty, 100, json.dumps(daily_usage), today.isoformat()))

    # 2. Seed Beds
    beds_data = [
        ("PHC-001", 30, 26), # High occupancy
        ("PHC-002", 40, 18),
        ("PHC-003", 25, 12),
        ("PHC-004", 35, 20)
    ]
    for p_id, total, occ in beds_data:
        cursor.execute("""
        INSERT INTO bed_status (phc_id, total_beds, occupied_beds, updated_at)
        VALUES (?, ?, ?, ?)
        """, (p_id, total, occ, today.isoformat()))

    # 3. Seed Staff Attendance (with encrypted staff_id & SHA-256 token)
    raw_staff = [
        ("PHC-001", "STF-101", 1),
        ("PHC-001", "STF-102", 1),
        ("PHC-001", "STF-103", 0),
        ("PHC-002", "STF-201", 1),
        ("PHC-002", "STF-202", 1),
        ("PHC-003", "STF-301", 1),
        ("PHC-004", "STF-401", 1)
    ]
    date_str = today.strftime("%Y-%m-%d")
    for p_id, s_id, pres in raw_staff:
        enc_id = encrypt_field(s_id)
        tok_id = tokenize_identifier(s_id)
        cursor.execute("""
        INSERT INTO staff_attendance (phc_id, staff_id, staff_id_encrypted, staff_token, present, date)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (p_id, s_id, enc_id, tok_id, pres, date_str))

    # 4. Seed Patient Footfall for last 7 days
    for phc in phcs:
        p_id = phc["id"]
        base_count = 80 if p_id == "PHC-001" else 45
        for i in range(7):
            day_date = (today - timedelta(days=6-i)).strftime("%Y-%m-%d")
            c = base_count + (i * 12 if p_id == "PHC-001" else (i % 3) * 5)
            cursor.execute("""
            INSERT INTO patient_footfall (phc_id, date, count)
            VALUES (?, ?, ?)
            """, (p_id, day_date, c))
