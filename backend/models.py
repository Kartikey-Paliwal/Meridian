from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# Medicine Inventory CRUD Models
class InventoryUpdate(BaseModel):
    phc_id: str
    medicine_name: str
    quantity: int
    par_level: Optional[int] = 100
    daily_consumption: Optional[int] = None # Optional incremental usage log

class BedStatusUpdate(BaseModel):
    phc_id: str
    total_beds: int
    occupied_beds: int

class StaffAttendanceCreate(BaseModel):
    phc_id: str
    staff_id: str
    staff_name: Optional[str] = None
    role: Optional[str] = None
    card_uid: Optional[str] = None
    present: int = 1  # 1 for present, 0 for absent
    status: Optional[str] = "CHECKED_IN"
    verification_method: Optional[str] = "Manual Kiosk"
    shift: Optional[str] = "Morning Shift (08:00 - 16:00)"
    department: Optional[str] = "General"
    remarks: Optional[str] = None
    operator: Optional[str] = "Manual Kiosk"
    punch_in_time: Optional[str] = None
    punch_out_time: Optional[str] = None
    date: Optional[str] = None

class CardPunchRequest(BaseModel):
    card_uid: str
    phc_id: Optional[str] = "PHC-001"
    verification_method: Optional[str] = "RFID Card Punch"
    operator: Optional[str] = "TERMINAL-PHC-GATE1"

class StaffActionRequest(BaseModel):
    staff_id: str
    action: str  # "CHECK_OUT", "CHECK_IN", "MARK_LEAVE", "MARK_ABSENT"
    phc_id: Optional[str] = "PHC-001"
    remarks: Optional[str] = None
    operator: Optional[str] = "Supervisor Override"

class PatientFootfallCreate(BaseModel):
    phc_id: str
    date: str
    count: int

# Action model for Human-in-the-loop Redistribution
class TransferActionRequest(BaseModel):
    transfer_id: Optional[int] = None
    source_phc: str
    target_phc: str
    medicine_name: str
    quantity: int
    action: str  # "APPROVE" or "REJECT" or "OVERRIDE"
