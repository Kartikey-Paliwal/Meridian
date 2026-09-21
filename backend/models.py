from pydantic import BaseModel, Field, EmailStr, model_validator
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
    phc_id: Optional[str] = None
    total_beds: int = Field(..., ge=0)
    occupied_beds: int = Field(..., ge=0)
    notes: Optional[str] = None
    override_reason: Optional[str] = None # Required if performed by National Admin

class EquipmentUpdate(BaseModel):
    phc_id: Optional[str] = None
    equipment_id: Optional[int] = None
    name: str
    category: Optional[str] = "General"
    quantity: int = Field(..., ge=0)
    operational_status: str = Field("OPERATIONAL", description="OPERATIONAL, UNDER_MAINTENANCE, CRITICAL_DEFICIT, STANDBY")
    under_maintenance_count: int = Field(0, ge=0)
    notes: Optional[str] = None
    override_reason: Optional[str] = None

class StaffAttendanceCreate(BaseModel):
    phc_id: Optional[str] = None
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
    action: str  # "CHECK_OUT", "CHECK_IN", "MARK_LEAVE", "MARK_ABSENT", "CORRECTION"
    phc_id: Optional[str] = "PHC-001"
    remarks: Optional[str] = None
    operator: Optional[str] = "Supervisor Override"
    override_reason: Optional[str] = None

class PatientFootfallCreate(BaseModel):
    phc_id: Optional[str] = None
    date: str
    count: int = Field(..., ge=0)
    male_count: Optional[int] = Field(0, ge=0)
    female_count: Optional[int] = Field(0, ge=0)
    other_count: Optional[int] = Field(0, ge=0)
    emergency_cases: Optional[int] = Field(0, ge=0)
    correction_reason: Optional[str] = None
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

# ---------------------------------------------------------
# 10-STEP REDISTRIBUTION LIFECYCLE SCHEMAS
# ---------------------------------------------------------

class TransferCreateRequest(BaseModel):
    medicine_name: str
    quantity: int = Field(..., gt=0)
    urgency: str = "NORMAL"  # "NORMAL", "URGENT", "CRITICAL"
    reason: Optional[str] = None
    donor_phc: Optional[str] = None  # Optional: specific donor or let system match
    target_phc: Optional[str] = None
    phc_id: Optional[str] = None
    required_by: Optional[str] = None
    notes: Optional[str] = None

class TransferReviewRequest(BaseModel):
    action: str  # "APPROVE", "MODIFY_AND_APPROVE", "REJECT"
    modified_quantity: Optional[int] = None
    alternative_donor_phc: Optional[str] = None
    decision_reason: Optional[str] = None

class TransferDispatchConfirmRequest(BaseModel):
    notes: Optional[str] = None
    batch_number: Optional[str] = None

class TransferDeliverConfirmRequest(BaseModel):
    received_quantity: Optional[int] = None
    notes: Optional[str] = None

class TransferEscalateRequest(BaseModel):
    reason: str = Field(..., min_length=3)

# ---------------------------------------------------------
# OFFICIAL COMMUNICATION & NOTIFICATION SCHEMAS
# ---------------------------------------------------------

class SendMessageRequest(BaseModel):
    recipient_role: Optional[str] = None  # "DISTRICT_OFFICER", "PHC_STAFF", "NATIONAL_ADMIN", "ALL"
    recipient_id: Optional[str] = None
    district_id: Optional[str] = None
    phc_id: Optional[str] = None
    transfer_id: Optional[int] = None
    subject: str = Field(..., min_length=2)
    message: str = Field(..., min_length=2)
    priority: str = "NORMAL"  # "NORMAL", "URGENT", "EMERGENCY"

class AcknowledgeMessageRequest(BaseModel):
    notes: Optional[str] = None

# ---------------------------------------------------------
# FAST PHC OPERATIONAL ENTRY SCHEMAS
# ---------------------------------------------------------

class StockReceivedRequest(BaseModel):
    phc_id: Optional[str] = None
    medicine_name: str
    quantity: int = Field(..., gt=0)
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    supplier: Optional[str] = "District Central Medical Depot"
    received_date: Optional[str] = None
    notes: Optional[str] = None
    override_reason: Optional[str] = None

class StockConsumedRequest(BaseModel):
    phc_id: Optional[str] = None
    medicine_name: str
    quantity: int = Field(..., gt=0)
    reason: Optional[str] = "Routine Dispensation"
    date: Optional[str] = None
    notes: Optional[str] = None
    override_reason: Optional[str] = None

# Backward-compatible and semantic alias
class StockDispensedRequest(StockConsumedRequest):
    pass


# ---------------------------------------------------------
# FEDERATED LEARNING & EVALUATION SCHEMAS
# ---------------------------------------------------------

class FederatedTrainRequest(BaseModel):
    confirm: bool = Field(False, description="Explicit confirmation required to trigger federated aggregation")
    horizon_days: int = Field(7, ge=1, le=30)
    notes: Optional[str] = None

class ModelEvaluationRequest(BaseModel):
    model_version: Optional[str] = "v2.4-FedAvg"
    test_days: Optional[int] = Field(None, ge=7, le=90, description="Evaluation window days requested by frontend/tests")
    window_days: Optional[int] = Field(None, ge=7, le=90, description="Backward-compatible window days")

    @model_validator(mode="before")
    @classmethod
    def reconcile_days(cls, data: Any) -> Any:
        if isinstance(data, dict):
            td = data.get("test_days")
            wd = data.get("window_days")
            if td is not None and wd is None:
                data["window_days"] = td
            elif wd is not None and td is None:
                data["test_days"] = wd
            elif td is None and wd is None:
                data["window_days"] = 30
                data["test_days"] = 30
        return data

    @property
    def canonical_window_days(self) -> int:
        return self.window_days or self.test_days or 30

class FhirExportRequest(BaseModel):
    format: str = Field("json", description="Export format: json or ndjson")
    scope: str = Field("NATIONAL", description="Jurisdictional scope: NATIONAL or district ID")
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class DemoResetRequest(BaseModel):
    confirm: bool = Field(False, description="Explicit confirmation to reset demo records back to initial baseline")




