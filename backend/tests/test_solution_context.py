from app.agents import build_solution_context


def test_solution_context_preserves_counts_and_bounds_detail() -> None:
    requirements = [
        {
            "id": f"req-{index}",
            "requirement_key": f"REQ-{index:03d}",
            "requirement_text": f"Relay capability {index} shall be provided.",
            "solution_package": "Protection and Control System",
            "subcategory": "Functional requirements",
            "compliance_object": "Protection relay / IED",
            "expected_evidence": "Product manual or certified datasheet",
        }
        for index in range(20)
    ]
    assessments = [
        {
            "requirement_id": f"req-{index}",
            "decision": "Compliant" if index < 10 else "Unknown",
            "product_name": "UR relay",
            "rationale": "Controlled decision.",
            "evidence": [],
        }
        for index in range(20)
    ]

    context = build_solution_context(requirements, assessments)

    assert len(context) == 1
    assert context[0]["decision_counts"] == {"Compliant": 10, "Unknown": 10}
    assert len(context[0]["sample_requirements"]) == 4
    assert len(context[0]["unresolved_requirements"]) == 6
    assert context[0]["offered_products"] == ["UR relay"]
