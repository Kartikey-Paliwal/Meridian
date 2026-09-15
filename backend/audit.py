import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

from backend.database import get_db_connection

def log_audit_event(
    user_id: str,
    user_name: Optional[str],
    role: str,
    action: str,
    target_record: Optional[str] = None,
    district_scope: Optional[str] = None,
    phc_scope: Optional[str] = None,
    result: str = "SUCCESS",
    reason: Optional[str] = None,
    previous_value: Optional[str] = None,
    new_value: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Persists a structured audit trail event.
    Captures actor, role, district, PHC, action, previous value, new value, reason, timestamp, and result.
    Automatically scrubs passwords, tokens, and secret keys from details before writing.
    """
    try:
        clean_details = {}
        if details:
            for k, v in details.items():
                low = k.lower()
                if any(sec in low for sec in ["pass", "token", "secret", "cookie", "key"]):
                    clean_details[k] = "[REDACTED]"
                else:
                    clean_details[k] = v

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO audit_logs (
            user_id, user_name, role, action, target_record, 
            district_scope, phc_scope, timestamp, result, reason,
            previous_value, new_value, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            user_name or "Unknown",
            role,
            action,
            target_record or "N/A",
            district_scope,
            phc_scope,
            datetime.now().isoformat(),
            result,
            reason,
            str(previous_value) if previous_value is not None else None,
            str(new_value) if new_value is not None else None,
            json.dumps(clean_details) if clean_details else None
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to log event: {e}")
