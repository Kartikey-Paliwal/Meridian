#!/usr/bin/env python3
"""
=============================================================================
MERIDIAN PUBLIC HEALTH SUPPLY CHAIN PLATFORM - DEMO DATA RESET CLI
=============================================================================
Safely resets the local demonstration database to its initial, predictable
state for repeatable hackathon demonstrations.

Requirements:
- Works only when DEMO_MODE is true (or when --force is supplied)
- Resets only demo-owned tables
- Preserves SQLite database file integrity (does NOT delete file)
- Automatically records a DEMO_DATA_RESET audit log entry
=============================================================================
Usage:
    python backend/reset_demo.py
    python backend/reset_demo.py --force
=============================================================================
"""

import sys
import os
import argparse

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.database import reset_demo_data

def main():
    parser = argparse.ArgumentParser(
        description="Reset Meridian Demo Environment to Predictable Hackathon State"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force demonstration reset even if DEMO_MODE environment variable is not true"
    )

    args = parser.parse_args()

    print("[*] Meridian Demonstration Data Reset Utility")
    print(f"[*] Working Directory: {PROJECT_ROOT}")

    try:
        result = reset_demo_data(caller_info={"id": "SYSTEM_CLI", "full_name": "CLI Administrator", "role": "NATIONAL_ADMIN"}, force=args.force)
        print(f"[SUCCESS] {result['message']}")
        print(f"[*] Reset Timestamp: {result['timestamp']}")
        print("[*] Verifying baseline state:")
        print("    - PHC-001 (Alpha): ORS Packets = 15 (Critical Shortage)")
        print("    - PHC-002 (Beta):  ORS Packets = 320 (Safe Surplus)")
        print("    - Transfer 1: ORS Packets (60 units) - Pending Review")
        print("    - Transfer 2: Paracetamol (40 units) - Delayed in Transit")
        print("    - Transfer 3: Amoxicillin (30 units) - Completed")
        print("    - Transfer 4: IV Fluids   (20 units) - Approved awaiting dispatch")
        print("    - Audit entry logged: DEMO_DATA_RESET")
        print("\nReady for presentation!")
    except PermissionError as pe:
        print(f"\n[BLOCKED] {pe}", file=sys.stderr)
        print("Tip: Enable demo mode via DEMO_MODE=true or pass --force for manual override.", file=sys.stderr)
        sys.exit(2)
    except Exception as ex:
        print(f"\n[ERROR] Demo reset failed: {ex}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
