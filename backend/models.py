from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any

# ---------------------------------------------------------
# AUTHENTICATION & USER MANAGEMENT SCHEMAS
# ---------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., description="Email, Employee ID, or username alias")
    password: str = Field(..., min_length=1)
    remember_me: bool = False

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6)

class CreateUserRequest(BaseModel):
    full_name: str
    email: str
    employee_id: Optional[str] = None
    role: str # "DISTRICT_OFFICER" or "PHC_STAFF"
    assigned_district_id: Optional[str] = None
    assigned_phc_id: Optional[str] = None
    initial_password: Optional[str] = "Meridian@2026"

class UpdateUserStatusRequest(BaseModel):
    account_status: str # "ACTIVE" or "DISABLED"

class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    employee_id: Optional[str] = None
    role: str
    account_status: str
    assigned_district_id: Optional[str] = None
    assigned_phc_id: Optional[str] = None
    must_change_password: bool
    last_login: Optional[str] = None
    created_at: str

class AdminOverrideRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory audit justification for operational override")
    confirm: bool = True

# ---------------------------------------------------------
# OPERATIONAL SCHEMAS (WITH OVERRIDE & SCOPING SUPPORT)
# ---------------------------------------------------------

class InventoryUpdate(BaseModel):
    phc_id: str
    medicine_name: str
    quantity: int
    par_level: Optional[int] = 100
    daily_consumption: Optional[int] = None
    override_reason: Optional[str] = None # Required if performed by National Admin

class BedStatusUpdate(BaseModel):
    phc_id: str
    total_beds: int
    occupied_beds: int
    override_reason: Optional[str] = None # Required if performed by National Admin

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
    override_reason: Optional[str] = None

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
    override_reason: Optional[str] = None

class PatientFootfallCreate(BaseModel):
    phc_id: str
    date: str
    count: int
    override_reason: Optional[str] = None

# Action model for Human-in-the-loop Redistribution
class TransferActionRequest(BaseModel):
    transfer_id: Optional[int] = None
    source_phc: str
    target_phc: str
    medicine_name: str
    quantity: int
    action: str  # "APPROVE" or "REJECT" or "OVERRIDE"
    decision_reason: Optional[str] = None
