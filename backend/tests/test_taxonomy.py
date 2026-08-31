from app.taxonomy import classify_requirement


def classify(text: str, section: str = "Technical specifications") -> dict:
    return classify_requirement(
        {
            "section_name": section,
            "requirement_text": text,
            "source_quote": text,
            "category": "Technical",
        }
    )


def test_redundant_merging_units_require_hybrid_evidence() -> None:
    result = classify("Two independent merging units shall provide redundant sampled values.")

    assert result["solution_package"] == "Process Bus and Instrument Interfaces"
    assert result["subcategory"] == "Redundancy and availability"
    assert result["evidence_scope"] == "hybrid"
    assert result["manual_match_applicable"] == 1


def test_engineering_files_are_routed_to_deliverable_review() -> None:
    result = classify("The supplier shall submit SCD and ICD files with the final drawings.")

    assert result["solution_package"] == "Engineering and Project Services"
    assert result["subcategory"] == "Engineering deliverables"
    assert result["evidence_scope"] == "engineering_deliverable"
    assert result["manual_match_applicable"] == 0


def test_acceptance_test_is_not_matched_to_a_product_manual() -> None:
    result = classify("The completed panel shall pass the factory dielectric test.")

    assert result["solution_package"] == "Verification and Acceptance"
    assert result["subcategory"] == "Testing and acceptance"
    assert result["evidence_scope"] == "test_report"
    assert result["manual_match_applicable"] == 0


def test_network_switch_rating_is_product_manual_evidence() -> None:
    result = classify("The Ethernet switch shall provide 24 fiber ports at 1 Gbps.")

    assert result["solution_package"] == "Station Communications Network"
    assert result["subcategory"] == "Performance and ratings"
    assert result["evidence_scope"] == "product_manual"
    assert result["manual_match_applicable"] == 1
