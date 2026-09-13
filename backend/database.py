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

    # 3. staff_members directory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        staff_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        card_uid TEXT NOT NULL UNIQUE
    );
    """)

    # 4. staff_attendance log table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        staff_id TEXT NOT NULL,
        staff_name TEXT,
        role TEXT,
        card_uid TEXT,
        staff_id_encrypted TEXT,
        staff_token TEXT,
        present INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'CHECKED_IN',
        verification_method TEXT DEFAULT 'RFID Card Punch',
        punch_in_time TEXT,
        punch_out_time TEXT,
        date TEXT NOT NULL
    );
    """)

    # Migrate columns if existing database table lacks new columns
    cursor.execute("PRAGMA table_info(staff_attendance)")
    columns = [col[1] for col in cursor.fetchall()]
    if "staff_name" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN staff_name TEXT")
    if "role" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN role TEXT")
    if "card_uid" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN card_uid TEXT")
    if "status" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN status TEXT DEFAULT 'CHECKED_IN'")
    if "verification_method" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN verification_method TEXT DEFAULT 'RFID Card Punch'")
    if "punch_in_time" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN punch_in_time TEXT")
    if "punch_out_time" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN punch_out_time TEXT")
    if "shift" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN shift TEXT DEFAULT 'Morning Shift (08:00 - 16:00)'")
    if "department" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN department TEXT DEFAULT 'General'")
    if "remarks" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN remarks TEXT")
    if "operator" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN operator TEXT DEFAULT 'TERMINAL-PHC-GATE1'")
    if "updated_at" not in columns:
        cursor.execute("ALTER TABLE staff_attendance ADD COLUMN updated_at TEXT")

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

    # Always seed staff members if staff_members table is empty
    cursor.execute("SELECT COUNT(*) FROM staff_members")
    if cursor.fetchone()[0] == 0:
        seed_staff_members(cursor)
        conn.commit()

    conn.close()

PHC_GIS_DATA = {
    "PHC-001": {
        "id": "PHC-001",
        "name": "Alpha Sector PHC",
        "district": "District-North",
        "country": "India",
        "lat": 28.6139,
        "lng": 77.2090,
        "address": "Connaught Place, New Delhi",
        "cold_chain_capable": True,
        "transport_tier": "Cold-Chain Express"
    },
    "PHC-002": {
        "id": "PHC-002",
        "name": "Beta Central PHC",
        "district": "District-North",
        "country": "India",
        "lat": 28.5355,
        "lng": 77.3910,
        "address": "Sector 62, Noida Hub",
        "cold_chain_capable": True,
        "transport_tier": "Standard Logistics"
    },
    "PHC-003": {
        "id": "PHC-003",
        "name": "Gamma Rural PHC",
        "district": "District-South",
        "country": "Brazil (Simulated)",
        "lat": -15.7975,
        "lng": -47.8919,
        "address": "Federal District, Brasília",
        "cold_chain_capable": False,
        "transport_tier": "Rural Courier"
    },
    "PHC-004": {
        "id": "PHC-004",
        "name": "Delta Community PHC",
        "district": "District-South",
        "country": "South Africa (Simulated)",
        "lat": -25.7479,
        "lng": 28.2293,
        "address": "Gauteng Corridor, Pretoria",
        "cold_chain_capable": True,
        "transport_tier": "Cold-Chain Express"
    }
}

def get_phc_gis_data(phc_id: str | None = None):
    if phc_id:
        return PHC_GIS_DATA.get(phc_id)
    return list(PHC_GIS_DATA.values())

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

def seed_staff_members(cursor):
    today = datetime.now()
    raw_members = [
        ("PHC-001", "STF-101", "Nurse Anita Sharma", "Senior Staff Nurse (ICU)", "RFID-10101"),
        ("PHC-001", "STF-102", "Nurse Sunita Devi", "Staff Nurse (Emergency)", "RFID-10102"),
        ("PHC-001", "STF-103", "Dr. Rajesh Kumar", "Medical Officer in Charge", "RFID-10103"),
        ("PHC-001", "STF-104", "Vikram Singh", "Chief Pharmacist", "RFID-10104"),
        ("PHC-001", "STF-105", "Priya Verma", "Lab Technician", "RFID-10105"),
        ("PHC-001", "STF-106", "Nurse Pooja Mehra", "Staff Nurse (OPD)", "RFID-10106"),
        ("PHC-001", "STF-107", "Ramesh Yadav", "Emergency Transport Paramedic", "RFID-10107"),
        ("PHC-001", "STF-108", "Dr. Alok Verma", "Pediatric Specialist", "RFID-10108"),
        ("PHC-002", "STF-201", "Nurse Kavita Rao", "Staff Nurse (General)", "RFID-20201"),
        ("PHC-002", "STF-202", "Dr. Amit Patel", "Medical Officer", "RFID-20202"),
        ("PHC-002", "STF-203", "Rohan Mehta", "Pharmacist", "RFID-20203"),
        ("PHC-003", "STF-301", "Nurse Meena Kumari", "Staff Nurse", "RFID-30301"),
        ("PHC-003", "STF-302", "Dr. Suresh Nair", "Community Health Officer", "RFID-30302"),
        ("PHC-004", "STF-401", "Nurse Pooja Sharma", "Staff Nurse", "RFID-40401"),
        ("PHC-004", "STF-402", "Dr. Neha Gupta", "Medical Officer", "RFID-40402")
    ]
    for p_id, s_id, s_name, s_role, c_uid in raw_members:
        cursor.execute("""
        INSERT OR IGNORE INTO staff_members (phc_id, staff_id, name, role, card_uid)
        VALUES (?, ?, ?, ?, ?)
        """, (p_id, s_id, s_name, s_role, c_uid))

    raw_attendance = [
        ("PHC-001", "STF-101", "Nurse Anita Sharma", "Senior Staff Nurse (ICU)", "RFID-10101", 1, "CHECKED_IN", "RFID Card Punch", "08:15 AM", None, "Morning Shift (08:00 - 16:00)", "Intensive Care Unit (ICU)", "Routine ICU morning shift", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "STF-102", "Nurse Sunita Devi", "Staff Nurse (Emergency)", "RFID-10102", 1, "CHECKED_IN", "RFID Card Punch", "08:30 AM", None, "Morning Shift (08:00 - 16:00)", "Emergency & Trauma", "Assigned triage zone A", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "STF-103", "Dr. Rajesh Kumar", "Medical Officer in Charge", "RFID-10103", 1, "CHECKED_IN", "RFID Card Punch", "09:00 AM", None, "Morning Shift (08:00 - 16:00)", "General OPD", "Supervising clinical floor", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "STF-104", "Vikram Singh", "Chief Pharmacist", "RFID-10104", 1, "CHECKED_IN", "Manual Kiosk", "08:45 AM", None, "Morning Shift (08:00 - 16:00)", "Central Pharmacy", "Morning drug dispatch inventory", "KIOSK-MAIN-OPD"),
        ("PHC-001", "STF-105", "Priya Verma", "Lab Technician", "RFID-10105", 0, "ABSENT", "N/A", None, None, "Morning Shift (08:00 - 16:00)", "Pathology Lab", "Unscheduled absence - cover requested", "SUPERVISOR-OVERRIDE"),
        ("PHC-001", "STF-106", "Nurse Pooja Mehra", "Staff Nurse (OPD)", "RFID-10106", 0, "ON_LEAVE", "Supervisor Sanction", None, None, "Evening Shift (16:00 - 00:00)", "Outpatient Dept (OPD)", "Sanctioned medical leave (2 days)", "DR-RAJESH-MOIC"),
        ("PHC-001", "STF-107", "Ramesh Yadav", "Emergency Transport Paramedic", "RFID-10107", 1, "LATE", "RFID Card Punch", "09:15 AM", None, "Morning Shift (08:00 - 16:00)", "Ambulance Logistics", "Delayed due to route diversion", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "STF-108", "Dr. Alok Verma", "Pediatric Specialist", "RFID-10108", 1, "CHECKED_OUT", "RFID Card Punch", "07:45 AM", "12:30 PM", "Morning Shift (08:00 - 16:00)", "Pediatrics", "Half-day clinic completed", "TERMINAL-PHC-GATE1"),
        ("PHC-002", "STF-201", "Nurse Kavita Rao", "Staff Nurse (General)", "RFID-20201", 1, "CHECKED_IN", "RFID Card Punch", "08:20 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "General nursing", "TERMINAL-PHC2-GATE"),
        ("PHC-002", "STF-202", "Dr. Amit Patel", "Medical Officer", "RFID-20202", 1, "CHECKED_IN", "RFID Card Punch", "08:50 AM", None, "Morning Shift (08:00 - 16:00)", "OPD", "Clinical consultation", "TERMINAL-PHC2-GATE"),
        ("PHC-003", "STF-301", "Nurse Meena Kumari", "Staff Nurse", "RFID-30301", 1, "CHECKED_IN", "RFID Card Punch", "08:10 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "Routine ward round", "TERMINAL-PHC3-GATE"),
        ("PHC-004", "STF-401", "Nurse Pooja Sharma", "Staff Nurse", "RFID-40401", 1, "CHECKED_IN", "RFID Card Punch", "08:25 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "Ward coverage", "TERMINAL-PHC4-GATE")
    ]
    date_str = today.strftime("%Y-%m-%d")
    for p_id, s_id, s_name, s_role, c_uid, pres, status, v_method, p_in, p_out, shift, dept, remarks, oper in raw_attendance:
        enc_id = encrypt_field(s_id)
        tok_id = tokenize_identifier(s_id)
        cursor.execute("""
        INSERT INTO staff_attendance (phc_id, staff_id, staff_name, role, card_uid, staff_id_encrypted, staff_token, present, status, verification_method, punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (p_id, s_id, s_name, s_role, c_uid, enc_id, tok_id, pres, status, v_method, p_in, p_out, date_str, shift, dept, remarks, oper, today.isoformat()))

def seed_initial_data(cursor):
    today = datetime.now()

    # 1. Seed Medicine Inventory with spiking usage history for PHC-001 (ORS Packets)
    phcs = [
        {"id": "PHC-001", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg", "IV fluids (RL)", "Iron folic acid", "Chlorine tablets"]},
        {"id": "PHC-002", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg", "IV fluids (RL)"]},
        {"id": "PHC-003", "meds": ["ORS Packets", "Paracetamol 500mg", "Chlorine tablets"]},
        {"id": "PHC-004", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg"]}
    ]

    for phc in phcs:
        p_id = phc["id"]
        for med in phc["meds"]:
            if p_id == "PHC-001" and med == "ORS Packets":
                current_qty = 15  # Shortage / Critical!
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

    # Seed staff members
    seed_staff_members(cursor)

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
