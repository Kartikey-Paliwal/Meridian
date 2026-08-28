import os
import hashlib
import time
from typing import Dict, Any, Optional

SECRET_SALT = "MERIDIAN_ENTERPRISE_SECRET_KEY_2026"

# Demo Users and Roles
USERS_DB = {
    "phc_nurse": {"username": "phc_nurse", "password_hash": hashlib.sha256("nurse123".encode()).hexdigest(), "role": "PHC_STAFF", "phc_id": "PHC-001"},
    "district_officer": {"username": "district_officer", "password_hash": hashlib.sha256("officer123".encode()).hexdigest(), "role": "DISTRICT_OFFICER", "phc_id": "ALL"},
    "national_admin": {"username": "national_admin", "password_hash": hashlib.sha256("admin123".encode()).hexdigest(), "role": "NATIONAL_ADMIN", "phc_id": "ALL"}
}

def authenticate_user(username: str, password_raw: str) -> Optional[Dict[str, Any]]:
    user = USERS_DB.get(username)
    if not user:
        return None
    pwd_hash = hashlib.sha256(password_raw.encode()).hexdigest()
    if user["password_hash"] == pwd_hash:
        # Create lightweight session token
        token = f"TOKEN-{username}-{int(time.time())}"
        return {
            "status": "success",
            "access_token": token,
            "token_type": "bearer",
            "username": user["username"],
            "role": user["role"],
            "assigned_phc": user["phc_id"]
        }
    return None

def verify_role_permissions(role: str, required_level: str) -> bool:
    role_hierarchy = {"PHC_STAFF": 1, "DISTRICT_OFFICER": 2, "NATIONAL_ADMIN": 3}
    user_level = role_hierarchy.get(role, 0)
    req_level = role_hierarchy.get(required_level, 0)
    return user_level >= req_level
