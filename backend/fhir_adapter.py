from datetime import datetime
from typing import Dict, Any, List

def convert_to_fhir_medication_statement(inventory_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts a Meridian medicine inventory record into a standard HL7 FHIR R4 MedicationStatement resource JSON.
    """
    med_name = inventory_item.get("medicine_name", "Unknown Medicine")
    phc_id = inventory_item.get("phc_id", "PHC-UNKNOWN")
    qty = inventory_item.get("quantity", 0)

    return {
        "resourceType": "MedicationStatement",
        "id": f"fhir-med-{phc_id}-{med_name.replace(' ', '-').lower()}",
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/MedicationStatement"],
            "lastUpdated": datetime.now().isoformat()
        },
        "status": "active",
        "category": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/medication-statement-category",
                "code": "inpatient",
                "display": "Inpatient Supply Inventory"
            }]
        },
        "medicationCodeableConcept": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "372665008",
                "display": med_name
            }],
            "text": med_name
        },
        "subject": {
            "reference": f"Location/{phc_id}",
            "display": f"Primary Health Centre {phc_id}"
        },
        "dosage": [{
            "doseAndRate": [{
                "doseQuantity": {
                    "value": qty,
                    "unit": "units",
                    "system": "http://unitsofmeasure.org",
                    "code": "U"
                }
            }]
        }]
    }

def generate_fhir_bundle(inventory_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates an HL7 FHIR R4 Bundle containing all inventory resources."""
    entries = []
    for item in inventory_list:
        stmt = convert_to_fhir_medication_statement(item)
        entries.append({
            "fullUrl": f"urn:uuid:{stmt['id']}",
            "resource": stmt
        })

    return {
        "resourceType": "Bundle",
        "id": "meridian-fhir-bundle-001",
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "total": len(entries),
        "entry": entries
    }
