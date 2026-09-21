from datetime import datetime
from typing import Dict, Any, List

def convert_to_fhir_location(phc_id: str) -> Dict[str, Any]:
    """
    Converts a Meridian primary health centre facility into an HL7 FHIR R4 Location resource.
    """
    return {
        "resourceType": "Location",
        "id": f"Location-{phc_id}",
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/Location"],
            "lastUpdated": datetime.now().isoformat()
        },
        "status": "active",
        "name": f"Primary Health Centre {phc_id}",
        "mode": "instance",
        "type": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                "code": "COMM",
                "display": "Community Health Center"
            }]
        }],
        "physicalType": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                "code": "bu",
                "display": "Building"
            }]
        }
    }

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
    """Generates an HL7 FHIR R4 Bundle containing MedicationStatement and Location resources."""
    entries = []
    seen_phcs = set()

    # 1. Add Location resource for each distinct facility
    for item in inventory_list:
        p_id = item.get("phc_id")
        if p_id and p_id not in seen_phcs:
            seen_phcs.add(p_id)
            loc = convert_to_fhir_location(p_id)
            entries.append({
                "fullUrl": f"urn:uuid:Location-{p_id}",
                "resource": loc
            })

    # 2. Add MedicationStatement resource for each inventory record
    for item in inventory_list:
        stmt = convert_to_fhir_medication_statement(item)
        entries.append({
            "fullUrl": f"urn:uuid:{stmt['id']}",
            "resource": stmt
        })

    return {
        "resourceType": "Bundle",
        "id": "meridian-fhir-bundle-001",
        "type": "searchset",
        "timestamp": datetime.now().isoformat(),
        "total": len(entries),
        "meridian_compliance_notice": "FHIR-Compatible Demo Export (HL7 FHIR R4 demonstration export; not formally ABDM certified)",
        "entry": entries
    }
