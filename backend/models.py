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
    present: int  # 1 for present, 0 for absent
    date: str

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
