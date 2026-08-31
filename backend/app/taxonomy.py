import re

TAXONOMY_VERSION = "cohesive-v1"

PACKAGE_ORDER = {
    "Design Basis and Standards": 1,
    "Protection and Control System": 2,
    "Process Bus and Instrument Interfaces": 3,
    "Station Communications Network": 4,
    "HMI, SCADA and Automation": 5,
    "Panels and Auxiliary Electrical Systems": 6,
    "Metering and Monitoring": 7,
    "Engineering and Project Services": 8,
    "Verification and Acceptance": 9,
    "Generic / Unclassified": 10,
}

SUBSECTION_ORDER = {
    "System intent and architecture": 10,
    "Products and allocation": 20,
    "Functional requirements": 30,
    "Performance and ratings": 40,
    "Electrical and system interfaces": 50,
    "Redundancy and availability": 60,
    "Cybersecurity and time synchronization": 70,
    "Construction and environment": 80,
    "Configuration and engineering": 90,
    "Testing and acceptance": 100,
    "Engineering deliverables": 110,
    "Generic / Other": 120,
}


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _package(text: str, category: str) -> str:
    if _has(text, r"\b(fat|sat|factory acceptance|site acceptance|commissioning test|dielectric test|inspection and tests?)\b"):
        return "Verification and Acceptance"
    if _has(
        text,
        r"\b(submit|submission|drawing|document|manual|as[- ]built|test report|training|"
        r"installation supervisor|commissioning supervisor|warranty|spare parts?|packing|shipment)\b",
    ):
        return "Engineering and Project Services"
    if _has(text, r"\b(hmi|scada|gateway|operator console|engineering work ?station|data server|annunciator)\b"):
        return "HMI, SCADA and Automation"
    if _has(text, r"\b(meter|metering|transducer|kwh|kvarh|power quality|fault record(?:er|ing))\b"):
        return "Metering and Monitoring"
    if _has(text, r"\b(merging unit|process bus|sampled values?|\bsv\b|ncit|non-conventional instrument)\b"):
        return "Process Bus and Instrument Interfaces"
    if _has(
        text,
        r"\b(ethernet|network switch|station bus|teleprotection|fiber|fibre|optical|router|"
        r"snmp|vlan|rstp|prp|hsr|goose|\bmms\b|dnp3|modbus|iec\s*61850)\b",
    ):
        return "Station Communications Network"
    if _has(
        text,
        r"\b(panel|switchboard|marshalling|terminal block|wiring|wire|enclosure|cabinet|"
        r"grounding bus|earthing|dc supply|battery|trip circuit|close circuit|test switch)\b",
    ):
        return "Panels and Auxiliary Electrical Systems"
    if _has(
        text,
        r"\b(relay|protection|breaker failure|distance|differential|overcurrent|busbar|"
        r"bay control|interlock|trip(?:ping)?)\b",
    ):
        return "Protection and Control System"
    if _has(text, r"\b(code|standard|ambient|temperature|humidity|altitude|seismic|climatic|environmental)\b"):
        return "Design Basis and Standards"

    category_fallback = {
        "Protection and Control": "Protection and Control System",
        "Panel Construction": "Panels and Auxiliary Electrical Systems",
        "Electrical Interface": "Panels and Auxiliary Electrical Systems",
        "Communications": "Station Communications Network",
        "Documentation": "Engineering and Project Services",
        "Testing": "Verification and Acceptance",
    }
    return category_fallback.get(category, "Generic / Unclassified")


def _subcategory(text: str, package: str) -> str:
    if package == "Engineering and Project Services" or _has(
        text, r"\b(submit|submission|drawing|document|manual|as[- ]built|signal list|ssd|scd|icd|cid)\b"
    ):
        return "Engineering deliverables"
    if package == "Verification and Acceptance" or _has(
        text, r"\b(test|testing|inspection|fat|sat|commissioning|secondary injection|dielectric)\b"
    ):
        return "Testing and acceptance"
    if _has(text, r"\b(configure|configuration|setting|programmable logic|engineering work)\b"):
        return "Configuration and engineering"
    if _has(
        text,
        r"\b(password|authentication|authorization|cyber|security|snmpv3|irig-b|ntp|ptp|"
        r"time synchroni[sz]|gps receiver)\b",
    ):
        return "Cybersecurity and time synchronization"
    if _has(text, r"\b(redundan|independent|duplicate|two separate|primary and backup|availability)\b"):
        return "Redundancy and availability"
    if _has(
        text,
        r"\b(interface|interconnection|connect|connection|ct circuit|vt circuit|current circuit|"
        r"potential circuit|trip circuit|dc supply|ac supply|protocol|port)\b",
    ):
        return "Electrical and system interfaces"
    if _has(
        text,
        r"\b(rated|rating|accuracy|range|burden|withstand|bandwidth|latency|speed|capacity|"
        r"temperature|humidity|voltage|current|frequency|[mg]bps)\b",
    ):
        return "Performance and ratings"
    if _has(
        text,
        r"\b(enclosure|cabinet|panel|switchboard|fabricat|material|mount|door|hinge|lock|"
        r"grounding|earthing|climatic|environmental)\b",
    ):
        return "Construction and environment"
    if _has(text, r"\b(design a complete|architecture|topology|system shall|coordinate with|integration)\b"):
        return "System intent and architecture"
    if _has(text, r"\b(provide|supply|include|consist of|comprised|quantity|quantities)\b"):
        return "Products and allocation"
    if _has(text, r"\b(shall support|shall perform|function|capable|control|protect|monitor|detect)\b"):
        return "Functional requirements"
    return "Generic / Other"


def _object(text: str, package: str) -> str:
    choices = (
        (r"\bmerging unit", "Merging unit"),
        (r"\b(ethernet|network) switch", "Ethernet switch"),
        (r"\b(distance|differential|overcurrent|protective|numerical|digital|static) relay", "Protection relay / IED"),
        (r"\bbay control unit|\bbcu\b", "Bay control unit"),
        (r"\b(hmi|operator console)", "HMI / operator console"),
        (r"\b(data server|engineering work ?station)", "Station computer / server"),
        (r"\bgateway", "Gateway"),
        (r"\b(meter|kwh|kvarh)", "Meter"),
        (r"\btransducer", "Transducer"),
        (r"\b(panel|switchboard|cabinet|enclosure)", "Panel / switchboard"),
        (r"\b(terminal block|terminal)", "Terminal system"),
        (r"\b(ct|current transformer|vt|voltage transformer|ncit)", "Instrument transformer interface"),
        (r"\b(network|station bus|process bus)", "Communication network"),
        (r"\b(drawing|document|manual|ssd|scd|icd|cid|signal list)", "Engineering package"),
        (r"\b(test|testing|inspection|fat|sat)", "Verification activity"),
        (r"\b(installation|commissioning|supervisor)", "Site service"),
    )
    for pattern, label in choices:
        if _has(text, pattern):
            return label
    return package.replace(" and ", " / ")


def _lifecycle(text: str, subsection: str) -> str:
    if _has(text, r"\b(as[- ]built|final drawing|final document)\b"):
        return "As-built"
    if _has(text, r"\b(commissioning|field test|site acceptance|\bsat\b)\b"):
        return "Commissioning"
    if _has(text, r"\b(installation|erection|site work)\b"):
        return "Installation"
    if _has(text, r"\b(factory acceptance|\bfat\b|factory test|dielectric test|inspection)\b"):
        return "FAT"
    if subsection in {"System intent and architecture", "Configuration and engineering", "Engineering deliverables"}:
        return "Detailed design"
    if _has(text, r"\b(provide|supply|furnish|include|equipment shall)\b"):
        return "Supply"
    return "Design and supply"


def _evidence_scope(text: str, package: str, subsection: str) -> tuple[str, str, int]:
    if package == "Verification and Acceptance" or subsection == "Testing and acceptance":
        return "test_report", "Test procedure and signed test report", 0
    if package == "Engineering and Project Services" or subsection == "Engineering deliverables":
        return "engineering_deliverable", "Submitted engineering package or supplier commitment", 0
    if subsection in {"System intent and architecture", "Configuration and engineering"}:
        return "system_design", "System architecture, schematic or configuration design", 0
    if subsection == "Redundancy and availability":
        return "hybrid", "Product manual plus system architecture drawing", 1
    if package == "Generic / Unclassified":
        return "engineer_confirmation", "Engineer confirmation", 0
    return "product_manual", "Product manual or certified datasheet", 1


def classify_requirement(requirement: dict) -> dict:
    text = " ".join(
        str(requirement.get(field) or "")
        for field in ("section_name", "section", "requirement_text", "source_quote")
    )
    category = str(requirement.get("category") or "Technical")
    package = _package(text, category)
    subsection = _subcategory(text, package)
    evidence_scope, expected_evidence, manual_match_applicable = _evidence_scope(
        text, package, subsection
    )
    return {
        "solution_package": package,
        "package_order": PACKAGE_ORDER[package],
        "subcategory": subsection,
        "subcategory_order": SUBSECTION_ORDER[subsection],
        "compliance_object": _object(text, package),
        "requirement_type": subsection,
        "lifecycle_phase": _lifecycle(text, subsection),
        "evidence_scope": evidence_scope,
        "expected_evidence": expected_evidence,
        "manual_match_applicable": manual_match_applicable,
        "classification_version": TAXONOMY_VERSION,
    }
