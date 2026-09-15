import sqlite3
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from backend.privacy import encrypt_field, tokenize_identifier

DB_PATH = os.path.join(os.path.dirname(__file__), "meridian.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def hash_password(password: str, salt: str = None) -> tuple:
    """Hash password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return pwd_hash, salt

def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """Verify password against stored PBKDF2 hash using constant-time comparison."""
    if not password or not pwd_hash or not salt:
        return False
    expected_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(expected_hash, pwd_hash)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")

    # 1. districts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS districts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        code TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 2. phcs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS phcs (
        id TEXT PRIMARY KEY,
        district_id TEXT NOT NULL,
        name TEXT NOT NULL,
        code TEXT NOT NULL,
        location TEXT,
        contact_details TEXT,
        operational_status TEXT NOT NULL DEFAULT 'ONLINE',
        last_data_sync_time TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (district_id) REFERENCES districts(id)
    );
    """)

    # 3. users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        employee_id TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL,
        account_status TEXT NOT NULL DEFAULT 'ACTIVE',
        assigned_district_id TEXT,
        assigned_phc_id TEXT,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        last_login TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 4. sessions table (HTTP-only cookie / Bearer session storage)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        remember_me INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # 5. audit_logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        user_name TEXT,
        role TEXT NOT NULL,
        action TEXT NOT NULL,
        target_record TEXT,
        district_scope TEXT,
        phc_scope TEXT,
        timestamp TEXT NOT NULL,
        result TEXT NOT NULL,
        reason TEXT,
        previous_value TEXT,
        new_value TEXT,
        details TEXT
    );
    """)

    # 6. password_reset_tokens table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # 7. medicine_inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS medicine_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
        medicine_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        par_level INTEGER DEFAULT 100,
        daily_usage_history TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(phc_id, medicine_name)
    );
    """)

    # 8. bed_status table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bed_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT UNIQUE,
        district_id TEXT,
        total_beds INTEGER NOT NULL,
        occupied_beds INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 9. staff_members directory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
        staff_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        card_uid TEXT NOT NULL UNIQUE
    );
    """)

    # 10. staff_attendance log table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
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
        date TEXT NOT NULL,
        shift TEXT DEFAULT 'Morning Shift (08:00 - 16:00)',
        department TEXT DEFAULT 'General',
        remarks TEXT,
        operator TEXT DEFAULT 'TERMINAL-PHC-GATE1',
        updated_at TEXT
    );
    """)

    # 11. patient_footfall table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patient_footfall (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
        date TEXT NOT NULL,
        count INTEGER NOT NULL,
        UNIQUE(phc_id, date)
    );
    """)

    # 12. redistribution_transfers table (10-step lifecycle workflow)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redistribution_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_phc TEXT NOT NULL,
        target_phc TEXT NOT NULL,
        source_district_id TEXT,
        target_district_id TEXT,
        medicine_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        eta_mins INTEGER NOT NULL DEFAULT 30,
        urgency TEXT NOT NULL DEFAULT 'NORMAL',
        status TEXT NOT NULL DEFAULT 'Requested',
        underlying_numbers TEXT,
        requested_by TEXT,
        requested_at TEXT,
        approved_by TEXT,
        approved_at TEXT,
        decision_reason TEXT,
        dispatched_by TEXT,
        dispatched_at TEXT,
        delivered_by TEXT,
        delivered_at TEXT,
        completed_at TEXT,
        delay_reason TEXT,
        is_escalated INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    """)

    # 13. messages table (Official communication & notification desk)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        sender_role TEXT NOT NULL,
        recipient_role TEXT,
        recipient_id TEXT,
        district_id TEXT,
        phc_id TEXT,
        transfer_id INTEGER,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'NORMAL',
        sent_at TEXT NOT NULL,
        read_at TEXT,
        acknowledged_at TEXT,
        acknowledged_by TEXT,
        acknowledgement_notes TEXT
    );
    """)

    # 14. stock_transactions table (Immutably records inventory changes)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
        medicine_name TEXT NOT NULL,
        transaction_type TEXT NOT NULL, -- 'RECEIVED' or 'DISPENSED'
        quantity INTEGER NOT NULL,
        batch_number TEXT,
        expiry_date TEXT,
        supplier_source TEXT,
        reason_usage TEXT,
        notes TEXT,
        transaction_date TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # 15. facility_equipment table (Ward resources & equipment tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facility_equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phc_id TEXT NOT NULL,
        district_id TEXT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        operational_status TEXT NOT NULL DEFAULT 'OPERATIONAL', -- 'OPERATIONAL', 'UNDER_MAINTENANCE', 'CRITICAL_DEFICIT', 'STANDBY'
        under_maintenance_count INTEGER NOT NULL DEFAULT 0,
        notes TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(phc_id, name)
    );
    """)

    # -------------------------------------------------------------
    # Schema Migrations: ensure new columns exist in pre-existing DBs
    # -------------------------------------------------------------
    tables_to_add_district_id = [
        "medicine_inventory", "bed_status", "staff_members", 
        "staff_attendance", "patient_footfall"
    ]
    for tbl in tables_to_add_district_id:
        cursor.execute(f"PRAGMA table_info({tbl})")
        cols = [c[1] for c in cursor.fetchall()]
        if "district_id" not in cols:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN district_id TEXT")

    # Migrate audit_logs columns
    cursor.execute("PRAGMA table_info(audit_logs)")
    al_cols = [c[1] for c in cursor.fetchall()]
    if "previous_value" not in al_cols:
        cursor.execute("ALTER TABLE audit_logs ADD COLUMN previous_value TEXT")
    if "new_value" not in al_cols:
        cursor.execute("ALTER TABLE audit_logs ADD COLUMN new_value TEXT")

    # Migrate redistribution_transfers columns
    cursor.execute("PRAGMA table_info(redistribution_transfers)")
    rt_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ("source_district_id", "TEXT"),
        ("target_district_id", "TEXT"),
        ("urgency", "TEXT DEFAULT 'NORMAL'"),
        ("requested_by", "TEXT"),
        ("requested_at", "TEXT"),
        ("approved_by", "TEXT"),
        ("approved_at", "TEXT"),
        ("decision_reason", "TEXT"),
        ("dispatched_by", "TEXT"),
        ("dispatched_at", "TEXT"),
        ("delivered_by", "TEXT"),
        ("delivered_at", "TEXT"),
        ("completed_at", "TEXT"),
        ("delay_reason", "TEXT"),
        ("is_escalated", "INTEGER DEFAULT 0"),
        ("updated_at", "TEXT")
    ]:
        if col_name not in rt_cols:
            cursor.execute(f"ALTER TABLE redistribution_transfers ADD COLUMN {col_name} {col_type}")

    # Migrate staff_attendance columns if missing
    cursor.execute("PRAGMA table_info(staff_attendance)")
    sa_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ("staff_name", "TEXT"), ("role", "TEXT"), ("card_uid", "TEXT"),
        ("status", "TEXT DEFAULT 'CHECKED_IN'"), ("verification_method", "TEXT DEFAULT 'RFID Card Punch'"),
        ("punch_in_time", "TEXT"), ("punch_out_time", "TEXT"),
        ("shift", "TEXT DEFAULT 'Morning Shift (08:00 - 16:00)'"),
        ("department", "TEXT DEFAULT 'General'"), ("remarks", "TEXT"),
        ("operator", "TEXT DEFAULT 'TERMINAL-PHC-GATE1'"), ("updated_at", "TEXT")
    ]:
        if col_name not in sa_cols:
            cursor.execute(f"ALTER TABLE staff_attendance ADD COLUMN {col_name} {col_type}")

    # Migrate patient_footfall columns if missing
    cursor.execute("PRAGMA table_info(patient_footfall)")
    pf_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ("male_count", "INTEGER DEFAULT 0"),
        ("female_count", "INTEGER DEFAULT 0"),
        ("other_count", "INTEGER DEFAULT 0"),
        ("emergency_cases", "INTEGER DEFAULT 0"),
        ("correction_reason", "TEXT"),
        ("updated_at", "TEXT")
    ]:
        if col_name not in pf_cols:
            cursor.execute(f"ALTER TABLE patient_footfall ADD COLUMN {col_name} {col_type}")

    # Migrate bed_status columns if missing
    cursor.execute("PRAGMA table_info(bed_status)")
    bs_cols = [c[1] for c in cursor.fetchall()]
    if "notes" not in bs_cols:
        cursor.execute("ALTER TABLE bed_status ADD COLUMN notes TEXT")

    # Ensure unique index on facility_equipment for idempotent seeding
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_facility_equipment_phc_name ON facility_equipment (phc_id, name)")

    # Backfill district_id in operational tables based on phc_id
    cursor.execute("UPDATE medicine_inventory SET district_id = 'DIST-NORTH' WHERE phc_id IN ('PHC-001', 'PHC-002') AND (district_id IS NULL OR district_id = '')")
    cursor.execute("UPDATE medicine_inventory SET district_id = 'DIST-SOUTH' WHERE phc_id IN ('PHC-003', 'PHC-004') AND (district_id IS NULL OR district_id = '')")
    
    cursor.execute("UPDATE bed_status SET district_id = 'DIST-NORTH' WHERE phc_id IN ('PHC-001', 'PHC-002') AND (district_id IS NULL OR district_id = '')")
    cursor.execute("UPDATE bed_status SET district_id = 'DIST-SOUTH' WHERE phc_id IN ('PHC-003', 'PHC-004') AND (district_id IS NULL OR district_id = '')")

    cursor.execute("UPDATE staff_members SET district_id = 'DIST-NORTH' WHERE phc_id IN ('PHC-001', 'PHC-002') AND (district_id IS NULL OR district_id = '')")
    cursor.execute("UPDATE staff_members SET district_id = 'DIST-SOUTH' WHERE phc_id IN ('PHC-003', 'PHC-004') AND (district_id IS NULL OR district_id = '')")

    cursor.execute("UPDATE staff_attendance SET district_id = 'DIST-NORTH' WHERE phc_id IN ('PHC-001', 'PHC-002') AND (district_id IS NULL OR district_id = '')")
    cursor.execute("UPDATE staff_attendance SET district_id = 'DIST-SOUTH' WHERE phc_id IN ('PHC-003', 'PHC-004') AND (district_id IS NULL OR district_id = '')")

    cursor.execute("UPDATE patient_footfall SET district_id = 'DIST-NORTH' WHERE phc_id IN ('PHC-001', 'PHC-002') AND (district_id IS NULL OR district_id = '')")
    cursor.execute("UPDATE patient_footfall SET district_id = 'DIST-SOUTH' WHERE phc_id IN ('PHC-003', 'PHC-004') AND (district_id IS NULL OR district_id = '')")

    conn.commit()

    # Seed districts and PHCs
    seed_districts_and_phcs(cursor)
    conn.commit()

    # Seed users
    seed_users(cursor)
    conn.commit()

    # Seed operational data if empty
    cursor.execute("SELECT COUNT(*) FROM medicine_inventory")
    if cursor.fetchone()[0] == 0:
        seed_initial_data(cursor)
        conn.commit()

    cursor.execute("SELECT COUNT(*) FROM staff_members")
    if cursor.fetchone()[0] == 0:
        seed_staff_members(cursor)
        conn.commit()

    # Seed facility equipment
    cursor.execute("SELECT COUNT(*) FROM facility_equipment")
    if cursor.fetchone()[0] == 0:
        seed_facility_equipment(cursor)
        conn.commit()

    conn.close()


PHC_GIS_DATA = {
    "PHC-001": {
        "id": "PHC-001",
        "name": "Alpha Sector PHC",
        "district": "DIST-NORTH",
        "district_name": "North Capital District",
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
        "district": "DIST-NORTH",
        "district_name": "North Capital District",
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
        "district": "DIST-SOUTH",
        "district_name": "Southern Health Corridor",
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
        "district": "DIST-SOUTH",
        "district_name": "Southern Health Corridor",
        "country": "South Africa (Simulated)",
        "lat": -25.7479,
        "lng": 28.2293,
        "address": "Gauteng Corridor, Pretoria",
        "cold_chain_capable": True,
        "transport_tier": "Cold-Chain Express"
    }
}

def get_phc_gis_data(phc_id: str = None):
    if phc_id:
        return PHC_GIS_DATA.get(phc_id)
    return list(PHC_GIS_DATA.values())


def seed_districts_and_phcs(cursor):
    now = datetime.now().isoformat()
    districts = [
        ("DIST-NORTH", "North Capital District", "ND-01", "ACTIVE", now, now),
        ("DIST-SOUTH", "Southern Health Corridor", "SD-02", "ACTIVE", now, now)
    ]
    for dist in districts:
        cursor.execute("""
        INSERT OR REPLACE INTO districts (id, name, code, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, dist)

    phcs = [
        ("PHC-001", "DIST-NORTH", "Alpha Sector PHC", "PHC-ALP-01", "Connaught Place, New Delhi", "+91 11 2334 0001", "ONLINE", now, now, now),
        ("PHC-002", "DIST-NORTH", "Beta Central PHC", "PHC-BET-02", "Sector 62, Noida Hub", "+91 120 445 0002", "ONLINE", now, now, now),
        ("PHC-003", "DIST-SOUTH", "Gamma Rural PHC", "PHC-GAM-03", "Brasília Rural Grid", "+55 61 3312 0003", "ONLINE", now, now, now),
        ("PHC-004", "DIST-SOUTH", "Delta Community PHC", "PHC-DEL-04", "Pretoria Gauteng Center", "+27 12 314 0004", "ONLINE", now, now, now)
    ]
    for phc in phcs:
        cursor.execute("""
        INSERT OR REPLACE INTO phcs (id, district_id, name, code, location, contact_details, operational_status, last_data_sync_time, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, phc)


def seed_users(cursor):
    """Seed documented accounts for hackathon evaluation and RBAC testing."""
    now = datetime.now().isoformat()

    users_seed = [
        # 1. National Admin
        {
            "id": "USR-NAT-001",
            "full_name": "Dr. Sunita Deshmukh",
            "email": "admin@meridian.health",
            "employee_id": "EMP-NAT-01",
            "raw_password": "Admin@123",
            "role": "NATIONAL_ADMIN",
            "account_status": "ACTIVE",
            "assigned_district_id": None,
            "assigned_phc_id": None,
            "must_change_password": 0,
            "created_by": "SYSTEM_INIT"
        },
        # 2. District Officer (North)
        {
            "id": "USR-DST-001",
            "full_name": "Vikramaditya Rao",
            "email": "officer.north@meridian.health",
            "employee_id": "EMP-DST-01",
            "raw_password": "Officer@123",
            "role": "DISTRICT_OFFICER",
            "account_status": "ACTIVE",
            "assigned_district_id": "DIST-NORTH",
            "assigned_phc_id": None,
            "must_change_password": 0,
            "created_by": "USR-NAT-001"
        },
        # 3. District Officer (South)
        {
            "id": "USR-DST-002",
            "full_name": "Maria Santos",
            "email": "officer.south@meridian.health",
            "employee_id": "EMP-DST-02",
            "raw_password": "Officer@123",
            "role": "DISTRICT_OFFICER",
            "account_status": "ACTIVE",
            "assigned_district_id": "DIST-SOUTH",
            "assigned_phc_id": None,
            "must_change_password": 0,
            "created_by": "USR-NAT-001"
        },
        # 4. PHC Staff (Alpha Sector, PHC-001)
        {
            "id": "USR-PHC-001",
            "full_name": "Nurse Anita Sharma",
            "email": "staff.alpha@meridian.health",
            "employee_id": "EMP-PHC-01",
            "raw_password": "Staff@123",
            "role": "PHC_STAFF",
            "account_status": "ACTIVE",
            "assigned_district_id": "DIST-NORTH",
            "assigned_phc_id": "PHC-001",
            "must_change_password": 0,
            "created_by": "USR-DST-001"
        },
        # 5. PHC Staff (Beta Central, PHC-002)
        {
            "id": "USR-PHC-002",
            "full_name": "Dr. Amit Patel",
            "email": "staff.beta@meridian.health",
            "employee_id": "EMP-PHC-02",
            "raw_password": "Staff@123",
            "role": "PHC_STAFF",
            "account_status": "ACTIVE",
            "assigned_district_id": "DIST-NORTH",
            "assigned_phc_id": "PHC-002",
            "must_change_password": 0,
            "created_by": "USR-DST-001"
        },
        # 6. Temporary Password User (Requires password change upon login)
        {
            "id": "USR-TMP-001",
            "full_name": "Priya Verma (New Recruit)",
            "email": "temp.staff@meridian.health",
            "employee_id": "EMP-PHC-03",
            "raw_password": "TempPassword@123",
            "role": "PHC_STAFF",
            "account_status": "ACTIVE",
            "assigned_district_id": "DIST-NORTH",
            "assigned_phc_id": "PHC-001",
            "must_change_password": 1,
            "created_by": "USR-DST-001"
        },
        # 7. Disabled Account (Tests account lockout/disabled state)
        {
            "id": "USR-DIS-001",
            "full_name": "Rohan Mehta (Former Staff)",
            "email": "disabled.user@meridian.health",
            "employee_id": "EMP-PHC-04",
            "raw_password": "Disabled@123",
            "role": "PHC_STAFF",
            "account_status": "DISABLED",
            "assigned_district_id": "DIST-NORTH",
            "assigned_phc_id": "PHC-001",
            "must_change_password": 0,
            "created_by": "USR-DST-001"
        }
    ]

    for u in users_seed:
        pwd_hash, salt = hash_password(u["raw_password"])
        cursor.execute("""
        INSERT OR REPLACE INTO users (
            id, full_name, email, employee_id, password_hash, salt, role,
            account_status, assigned_district_id, assigned_phc_id,
            must_change_password, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u["id"], u["full_name"], u["email"], u["employee_id"],
            pwd_hash, salt, u["role"], u["account_status"],
            u["assigned_district_id"], u["assigned_phc_id"],
            u["must_change_password"], u["created_by"], now, now
        ))


def seed_staff_members(cursor):
    today = datetime.now()
    raw_members = [
        ("PHC-001", "DIST-NORTH", "STF-101", "Nurse Anita Sharma", "Senior Staff Nurse (ICU)", "RFID-10101"),
        ("PHC-001", "DIST-NORTH", "STF-102", "Nurse Sunita Devi", "Staff Nurse (Emergency)", "RFID-10102"),
        ("PHC-001", "DIST-NORTH", "STF-103", "Dr. Rajesh Kumar", "Medical Officer in Charge", "RFID-10103"),
        ("PHC-001", "DIST-NORTH", "STF-104", "Vikram Singh", "Chief Pharmacist", "RFID-10104"),
        ("PHC-001", "DIST-NORTH", "STF-105", "Priya Verma", "Lab Technician", "RFID-10105"),
        ("PHC-001", "DIST-NORTH", "STF-106", "Nurse Pooja Mehra", "Staff Nurse (OPD)", "RFID-10106"),
        ("PHC-001", "DIST-NORTH", "STF-107", "Ramesh Yadav", "Emergency Transport Paramedic", "RFID-10107"),
        ("PHC-001", "DIST-NORTH", "STF-108", "Dr. Alok Verma", "Pediatric Specialist", "RFID-10108"),
        ("PHC-002", "DIST-NORTH", "STF-201", "Nurse Kavita Rao", "Staff Nurse (General)", "RFID-20201"),
        ("PHC-002", "DIST-NORTH", "STF-202", "Dr. Amit Patel", "Medical Officer", "RFID-20202"),
        ("PHC-002", "DIST-NORTH", "STF-203", "Rohan Mehta", "Pharmacist", "RFID-20203"),
        ("PHC-003", "DIST-SOUTH", "STF-301", "Nurse Meena Kumari", "Staff Nurse", "RFID-30301"),
        ("PHC-003", "DIST-SOUTH", "STF-302", "Dr. Suresh Nair", "Community Health Officer", "RFID-30302"),
        ("PHC-004", "DIST-SOUTH", "STF-401", "Nurse Pooja Sharma", "Staff Nurse", "RFID-40401"),
        ("PHC-004", "DIST-SOUTH", "STF-402", "Dr. Neha Gupta", "Medical Officer", "RFID-40402")
    ]
    for p_id, d_id, s_id, s_name, s_role, c_uid in raw_members:
        cursor.execute("""
        INSERT OR REPLACE INTO staff_members (phc_id, district_id, staff_id, name, role, card_uid)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (p_id, d_id, s_id, s_name, s_role, c_uid))

    raw_attendance = [
        ("PHC-001", "DIST-NORTH", "STF-101", "Nurse Anita Sharma", "Senior Staff Nurse (ICU)", "RFID-10101", 1, "CHECKED_IN", "RFID Card Punch", "08:15 AM", None, "Morning Shift (08:00 - 16:00)", "Intensive Care Unit (ICU)", "Routine ICU morning shift", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "DIST-NORTH", "STF-102", "Nurse Sunita Devi", "Staff Nurse (Emergency)", "RFID-10102", 1, "CHECKED_IN", "RFID Card Punch", "08:30 AM", None, "Morning Shift (08:00 - 16:00)", "Emergency & Trauma", "Assigned triage zone A", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "DIST-NORTH", "STF-103", "Dr. Rajesh Kumar", "Medical Officer in Charge", "RFID-10103", 1, "CHECKED_IN", "RFID Card Punch", "09:00 AM", None, "Morning Shift (08:00 - 16:00)", "General OPD", "Supervising clinical floor", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "DIST-NORTH", "STF-104", "Vikram Singh", "Chief Pharmacist", "RFID-10104", 1, "CHECKED_IN", "Manual Kiosk", "08:45 AM", None, "Morning Shift (08:00 - 16:00)", "Central Pharmacy", "Morning drug dispatch inventory", "KIOSK-MAIN-OPD"),
        ("PHC-001", "DIST-NORTH", "STF-105", "Priya Verma", "Lab Technician", "RFID-10105", 0, "ABSENT", "N/A", None, None, "Morning Shift (08:00 - 16:00)", "Pathology Lab", "Unscheduled absence - cover requested", "SUPERVISOR-OVERRIDE"),
        ("PHC-001", "DIST-NORTH", "STF-106", "Nurse Pooja Mehra", "Staff Nurse (OPD)", "RFID-10106", 0, "ON_LEAVE", "Supervisor Sanction", None, None, "Evening Shift (16:00 - 00:00)", "Outpatient Dept (OPD)", "Sanctioned medical leave (2 days)", "DR-RAJESH-MOIC"),
        ("PHC-001", "DIST-NORTH", "STF-107", "Ramesh Yadav", "Emergency Transport Paramedic", "RFID-10107", 1, "LATE", "RFID Card Punch", "09:15 AM", None, "Morning Shift (08:00 - 16:00)", "Ambulance Logistics", "Delayed due to route diversion", "TERMINAL-PHC-GATE1"),
        ("PHC-001", "DIST-NORTH", "STF-108", "Dr. Alok Verma", "Pediatric Specialist", "RFID-10108", 1, "CHECKED_OUT", "RFID Card Punch", "07:45 AM", "12:30 PM", "Morning Shift (08:00 - 16:00)", "Pediatrics", "Half-day clinic completed", "TERMINAL-PHC-GATE1"),
        ("PHC-002", "DIST-NORTH", "STF-201", "Nurse Kavita Rao", "Staff Nurse (General)", "RFID-20201", 1, "CHECKED_IN", "RFID Card Punch", "08:20 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "General nursing", "TERMINAL-PHC2-GATE"),
        ("PHC-002", "DIST-NORTH", "STF-202", "Dr. Amit Patel", "Medical Officer", "RFID-20202", 1, "CHECKED_IN", "RFID Card Punch", "08:50 AM", None, "Morning Shift (08:00 - 16:00)", "OPD", "Clinical consultation", "TERMINAL-PHC2-GATE"),
        ("PHC-003", "DIST-SOUTH", "STF-301", "Nurse Meena Kumari", "Staff Nurse", "RFID-30301", 1, "CHECKED_IN", "RFID Card Punch", "08:10 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "Routine ward round", "TERMINAL-PHC3-GATE"),
        ("PHC-004", "DIST-SOUTH", "STF-401", "Nurse Pooja Sharma", "Staff Nurse", "RFID-40401", 1, "CHECKED_IN", "RFID Card Punch", "08:25 AM", None, "Morning Shift (08:00 - 16:00)", "General Ward", "Ward coverage", "TERMINAL-PHC4-GATE")
    ]
    date_str = today.strftime("%Y-%m-%d")
    for p_id, d_id, s_id, s_name, s_role, c_uid, pres, status, v_method, p_in, p_out, shift, dept, remarks, oper in raw_attendance:
        enc_id = encrypt_field(s_id)
        tok_id = tokenize_identifier(s_id)
        cursor.execute("""
        INSERT OR REPLACE INTO staff_attendance (
            phc_id, district_id, staff_id, staff_name, role, card_uid, 
            staff_id_encrypted, staff_token, present, status, verification_method, 
            punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p_id, d_id, s_id, s_name, s_role, c_uid, enc_id, tok_id, 
            pres, status, v_method, p_in, p_out, date_str, shift, dept, remarks, oper, today.isoformat()
        ))


def seed_facility_equipment(cursor):
    today = datetime.now().isoformat()
    phcs = [
        ("PHC-001", "DIST-NORTH"),
        ("PHC-002", "DIST-NORTH"),
        ("PHC-003", "DIST-SOUTH"),
        ("PHC-004", "DIST-SOUTH"),
    ]
    eq_templates = [
        ("Central Medical Oxygen Cylinders", "Respiratory Support", 6, "OPERATIONAL", 0, "6x 40L manifold cylinders connected"),
        ("Emergency Ambulance Van (DL-01-AMB)", "Emergency Transport", 1, "OPERATIONAL", 0, "Stationed on standby at Gate 2"),
        ("Neonatal Radiant Warmer (Zone B)", "Maternal & Child Health", 1, "OPERATIONAL", 0, "Calibrated and functional in triage"),
        ("Diesel Generator Fuel Level (Reserve)", "Power Backup", 1, "OPERATIONAL", 0, "68% Capacity - 72-hour fuel buffer maintained"),
    ]
    for p_id, d_id in phcs:
        for name, cat, qty, status, maint_count, notes in eq_templates:
            cursor.execute("""
            INSERT OR IGNORE INTO facility_equipment (
                phc_id, district_id, name, category, quantity, 
                operational_status, under_maintenance_count, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p_id, d_id, name, cat, qty, status, maint_count, notes, today))


def seed_initial_data(cursor):
    today = datetime.now()

    # 1. Seed Medicine Inventory with spiking usage history for PHC-001 (ORS Packets)
    phcs = [
        {"id": "PHC-001", "district_id": "DIST-NORTH", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg", "IV fluids (RL)", "Iron folic acid", "Chlorine tablets"]},
        {"id": "PHC-002", "district_id": "DIST-NORTH", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg", "IV fluids (RL)"]},
        {"id": "PHC-003", "district_id": "DIST-SOUTH", "meds": ["ORS Packets", "Paracetamol 500mg", "Chlorine tablets"]},
        {"id": "PHC-004", "district_id": "DIST-SOUTH", "meds": ["ORS Packets", "Paracetamol 500mg", "Amoxicillin 250mg"]}
    ]

    for phc in phcs:
        p_id = phc["id"]
        d_id = phc["district_id"]
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
            INSERT OR REPLACE INTO medicine_inventory (phc_id, district_id, medicine_name, quantity, par_level, daily_usage_history, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (p_id, d_id, med, current_qty, 100, json.dumps(daily_usage), today.isoformat()))

    # 2. Seed Beds
    beds_data = [
        ("PHC-001", "DIST-NORTH", 30, 26), # High occupancy
        ("PHC-002", "DIST-NORTH", 40, 18),
        ("PHC-003", "DIST-SOUTH", 25, 12),
        ("PHC-004", "DIST-SOUTH", 35, 20)
    ]
    for p_id, d_id, total, occ in beds_data:
        cursor.execute("""
        INSERT OR REPLACE INTO bed_status (phc_id, district_id, total_beds, occupied_beds, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """, (p_id, d_id, total, occ, today.isoformat()))

    # 3. Seed Patient Footfall for last 7 days
    for phc in phcs:
        p_id = phc["id"]
        d_id = phc["district_id"]
        base_count = 80 if p_id == "PHC-001" else 45
        for i in range(7):
            day_date = (today - timedelta(days=6-i)).strftime("%Y-%m-%d")
            c = base_count + (i * 12 if p_id == "PHC-001" else (i % 3) * 5)
            cursor.execute("""
            INSERT OR REPLACE INTO patient_footfall (phc_id, district_id, date, count)
            VALUES (?, ?, ?, ?)
            """, (p_id, d_id, day_date, c))

    # 4. Seed Redistribution Transfers
    now_iso = today.isoformat()
    two_hours_ago = (today - timedelta(hours=2)).isoformat()
    four_hours_ago = (today - timedelta(hours=4)).isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()

    cursor.execute("SELECT COUNT(*) FROM redistribution_transfers")
    if cursor.fetchone()[0] == 0:
        seed_transfers = [
            # 1. Critical shortage request pending review
            (
                "PHC-002", "PHC-001", "DIST-NORTH", "DIST-NORTH",
                "ORS Packets", 60, 25, "CRITICAL", "Requested",
                json.dumps({"source_surplus": 220, "target_deficit": 85}),
                "staff.alpha@meridian.health", two_hours_ago,
                None, None, None,
                None, None, None, None, None, None, 0,
                two_hours_ago, two_hours_ago
            ),
            # 2. Approved transfer currently in transit (slightly delayed past ETA to demo accountability indicators)
            (
                "PHC-002", "PHC-001", "DIST-NORTH", "DIST-NORTH",
                "Paracetamol 500mg", 40, 20, "HIGH", "In Transit",
                json.dumps({"source_surplus": 180, "target_deficit": 75}),
                "staff.alpha@meridian.health", four_hours_ago,
                "officer.north@meridian.health", (today - timedelta(hours=3, minutes=30)).isoformat(),
                "Approved emergency redistribution from Beta surplus",
                "staff.beta@meridian.health", (today - timedelta(hours=2, minutes=45)).isoformat(),
                None, None, None, "Route slowdown due to road work", 1,
                four_hours_ago, (today - timedelta(hours=2, minutes=45)).isoformat()
            ),
            # 3. Completed transfer from yesterday
            (
                "PHC-002", "PHC-001", "DIST-NORTH", "DIST-NORTH",
                "Amoxicillin 250mg", 30, 30, "NORMAL", "Completed",
                json.dumps({"source_surplus": 150, "target_deficit": 50}),
                "staff.alpha@meridian.health", yesterday_iso,
                "officer.north@meridian.health", yesterday_iso,
                "Routine stock balancing approval",
                "staff.beta@meridian.health", yesterday_iso,
                "staff.alpha@meridian.health", yesterday_iso,
                yesterday_iso, None, 0,
                yesterday_iso, yesterday_iso
            )
        ]
        for tr in seed_transfers:
            cursor.execute("""
            INSERT INTO redistribution_transfers (
                source_phc, target_phc, source_district_id, target_district_id,
                medicine_name, quantity, eta_mins, urgency, status,
                underlying_numbers, requested_by, requested_at,
                approved_by, approved_at, decision_reason,
                dispatched_by, dispatched_at, delivered_by, delivered_at,
                completed_at, delay_reason, is_escalated, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tr)

    # 5. Seed Messages (Official Communication Desk)
    cursor.execute("SELECT COUNT(*) FROM messages")
    if cursor.fetchone()[0] == 0:
        seed_messages = [
            # 1. National Admin -> District Officers (Acknowledged by Dist-North, Pending by Dist-South)
            (
                "admin@meridian.health", "Dr. Ananya Sharma", "NATIONAL_ADMIN",
                "DISTRICT_OFFICER", None, "DIST-NORTH", None, None,
                "URGENT: Monsoon Epidemic Preparedness & ORS Buffer Stocking",
                "All District Officers must verify buffer stocks of ORS, Chlorine tablets, and IV fluids across vulnerable riverine PHCs. Ensure daily reporting sync by 17:00.",
                "URGENT", four_hours_ago, (today - timedelta(hours=3)).isoformat(),
                (today - timedelta(hours=3)).isoformat(), "Rajesh Kumar",
                "Acknowledged and directives forwarded to all North district facilities."
            ),
            (
                "admin@meridian.health", "Dr. Ananya Sharma", "NATIONAL_ADMIN",
                "DISTRICT_OFFICER", None, "DIST-SOUTH", None, None,
                "URGENT: Monsoon Epidemic Preparedness & ORS Buffer Stocking",
                "All District Officers must verify buffer stocks of ORS, Chlorine tablets, and IV fluids across vulnerable riverine PHCs. Ensure daily reporting sync by 17:00.",
                "URGENT", four_hours_ago, None,
                None, None, None
            ),
            # 2. District Officer North -> PHC-001 Staff (Action Required)
            (
                "officer.north@meridian.health", "Rajesh Kumar", "DISTRICT_OFFICER",
                "PHC_STAFF", None, "DIST-NORTH", "PHC-001", 1,
                "ACTION REQUIRED: Confirm receipt & inspect batch seal for ORS transfer",
                "Transfer #1 has been approved and dispatch initiated from PHC-002 Beta. Confirm physical receipt and batch integrity immediately upon arrival.",
                "URGENT", two_hours_ago, (today - timedelta(hours=1, minutes=30)).isoformat(),
                None, None, None
            ),
            # 3. PHC-001 Staff -> District Officer North
            (
                "staff.alpha@meridian.health", "Sunita Verma", "PHC_STAFF",
                "DISTRICT_OFFICER", "officer.north@meridian.health", "DIST-NORTH", "PHC-001", None,
                "Reporting: Elevated OPD Footfall & Paediatric Dehydration Inflow",
                "Observed 35% surge in paediatric diarrhoeal presentations since morning shift. Rapid diagnostic kits currently adequate, but ORS sachet reserves are critical.",
                "HIGH", (today - timedelta(hours=1)).isoformat(), (today - timedelta(minutes=40)).isoformat(),
                (today - timedelta(minutes=35)).isoformat(), "Rajesh Kumar",
                "Noted. Expedited Beta transfer and alerted mobile supply van."
            )
        ]
        for msg in seed_messages:
            cursor.execute("""
            INSERT INTO messages (
                sender_id, sender_name, sender_role, recipient_role, recipient_id,
                district_id, phc_id, transfer_id, subject, message, priority,
                sent_at, read_at, acknowledged_at, acknowledged_by, acknowledgement_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, msg)
