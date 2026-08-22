from pathlib import Path


DOCUMENT_PATH = (
    Path(__file__).parents[1]
    / "research"
    / "ibm_fez_calibration_source_feasibility.md"
)


def test_ibm_fez_calibration_note_defines_source_freshness_and_aer_limits() -> None:
    document = DOCUMENT_PATH.read_text(encoding="utf-8")
    normalized_document = " ".join(document.split())

    required_sections = (
        "## Feasibility",
        "## Provenance",
        "## Freshness Rules",
        "## IBM-to-Aer Mapping Limitations",
    )
    for section in required_sections:
        assert section in document

    required_provenance_fields = (
        "`backend_name`",
        "`provider`",
        "`source`",
        "`calibration_snapshot`",
        "`last_update_date`",
        "`retrieved_at`",
        "`circuit_context`",
    )
    for field in required_provenance_fields:
        assert field in document

    freshness_contract = (
        "`fresh` | Calibration update is no more than 24 hours old",
        "retrieval is no more than 24 hours old",
        "`aging` | Either age is over 24 hours but no more than 7 days",
        "`stale` | Either age is over 7 days",
        "`undated` | IBM omits `last_update_date` or the timestamp cannot be parsed",
        "never silently call it fresh",
    )
    for rule in freshness_contract:
        assert rule in document

    aer_mapping_labels = (
        "`supported`",
        "`approximate`",
        "`unsupported`",
        "Aer with an IBM-derived approximate noise model",
    )
    for label in aer_mapping_labels:
        assert label in document

    benchmark_preservation_boundary = (
        "It does not change benchmark behavior",
        "live scheduling",
        "execution policy",
        "provider calls in scheduled benchmarks",
    )
    for boundary in benchmark_preservation_boundary:
        assert boundary in normalized_document