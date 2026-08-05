"""Tests for tenant-screening response normalisation and FCRA data minimisation.

Normalisation is a pure function, so these run without a network or a database.
"""

from app.utils.screening_client import (
    build_adverse_action,
    coerce_credit_score,
    normalize_recommendation,
    normalize_screening_response,
    normalize_status,
    summarize_report,
)

# A provider payload deliberately stuffed with regulated PII that must not be
# persisted, alongside the decision fields that may be.
RAW_DECLINE = {
    "id": "rpt_9f2",
    "status": "complete",
    "decision": "DENIED",
    "credit_score": 512,
    "credit_score_band": "poor",
    "eviction_records_found": 2,
    "collections_count": 4,
    "decision_reasons": ["EVICTION_HISTORY", "SERIOUS_DELINQUENCY"],
    "agency_name": "Example Screening Bureau",
    "agency_phone": "1-800-555-0100",
    "agency_address": "1 Bureau Way, Springfield",
    # Must never survive into report_data.
    "ssn": "123-45-6789",
    "date_of_birth": "1984-03-11",
    "current_address": "42 Applicant Lane",
    "tradelines": [{"creditor": "Bank", "balance": 9000}],
    "raw_report": "<xml>full consumer report</xml>",
}

# Fields that are PII or raw report content and must never be stored.
FORBIDDEN_KEYS = (
    "ssn",
    "date_of_birth",
    "current_address",
    "tradelines",
    "raw_report",
)


def _flatten(value, out):
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(str(k))
            _flatten(v, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _flatten(item, out)
    return out


# ── Recommendation / status vocabularies ────────────────────────────────────

def test_recommendation_aliases_map_to_canonical_values():
    assert normalize_recommendation("APPROVED") == "accept"
    assert normalize_recommendation("Conditionally Approved") == "review"
    assert normalize_recommendation("denied") == "decline"
    assert normalize_recommendation("pass") == "accept"


def test_unknown_recommendation_is_not_guessed():
    assert normalize_recommendation("banana") == "unknown"
    assert normalize_recommendation(None) == "unknown"
    assert normalize_recommendation("") == "unknown"


def test_status_aliases_map_to_canonical_values():
    assert normalize_status("complete") == "completed"
    assert normalize_status("IN-PROGRESS") == "pending"
    assert normalize_status("failed") == "error"


def test_unknown_status_is_treated_as_pending():
    assert normalize_status("weird") == "pending"


# ── Credit score coercion ───────────────────────────────────────────────────

def test_credit_score_accepts_in_range_values():
    assert coerce_credit_score(720) == 720
    assert coerce_credit_score("681") == 681
    assert coerce_credit_score(699.4) == 699


def test_credit_score_rejects_sentinels_and_junk():
    assert coerce_credit_score(0) is None
    assert coerce_credit_score(-1) is None
    assert coerce_credit_score(9999) is None
    assert coerce_credit_score("n/a") is None
    assert coerce_credit_score(None) is None
    assert coerce_credit_score(True) is None


# ── Data minimisation ───────────────────────────────────────────────────────

def test_summary_keeps_only_decision_fields():
    summary = summarize_report(RAW_DECLINE)
    assert summary["credit_score_band"] == "poor"
    assert summary["eviction_records_found"] == 2
    assert summary["collections_count"] == 4
    for key in FORBIDDEN_KEYS:
        assert key not in summary


def test_summary_of_malformed_payload_is_empty():
    assert summarize_report("not a dict") == {}
    assert summarize_report(None) == {}


def test_normalised_result_never_carries_pii():
    result = normalize_screening_response(RAW_DECLINE, provider="transunion")
    keys = _flatten(result.report_data, set())
    for key in FORBIDDEN_KEYS:
        assert key not in keys
    assert "123-45-6789" not in str(result.report_data)
    assert "1984-03-11" not in str(result.report_data)


# ── Normalisation end to end ────────────────────────────────────────────────

def test_completed_accept_is_normalised():
    result = normalize_screening_response(
        {"id": "rpt_1", "status": "completed", "recommendation": "approve", "score": 760},
        provider="transunion",
    )
    assert result.status == "completed"
    assert result.recommendation == "accept"
    assert result.credit_score == 760
    assert result.external_ref == "rpt_1"
    assert result.adverse_action is None
    assert "adverse_action" not in result.report_data


def test_pending_report_has_no_recommendation_yet():
    result = normalize_screening_response(
        {"report_id": "rpt_2", "status": "processing", "recommendation": "approved"},
        provider="transunion",
    )
    assert result.status == "pending"
    assert result.recommendation == "unknown"
    assert result.external_ref == "rpt_2"


def test_malformed_payload_becomes_an_error_result():
    result = normalize_screening_response(["nope"], provider="transunion")
    assert result.status == "error"
    assert result.recommendation == "unknown"
    assert result.credit_score is None


def test_provider_status_is_preserved_for_support():
    result = normalize_screening_response(
        {"id": "r", "status": "complete", "decision": "approve"}, provider="tu"
    )
    assert result.report_data["provider_status"] == "complete"


# ── Adverse action ──────────────────────────────────────────────────────────

def test_decline_records_adverse_action_reference():
    result = normalize_screening_response(RAW_DECLINE, provider="transunion")
    assert result.recommendation == "decline"
    action = result.adverse_action
    assert action is not None
    assert action["reason_codes"] == ["EVICTION_HISTORY", "SERIOUS_DELINQUENCY"]
    assert action["provider_reference"] == "rpt_9f2"
    assert action["agency"]["agency_name"] == "Example Screening Bureau"
    assert action["agency"]["agency_phone"] == "1-800-555-0100"
    assert action["notice_required"] is True


def test_adverse_action_is_persisted_in_report_data():
    result = normalize_screening_response(RAW_DECLINE, provider="transunion")
    assert result.report_data["adverse_action"] == result.adverse_action


def test_adverse_action_falls_back_to_provider_as_agency():
    action = build_adverse_action({}, provider="transunion", external_ref="abc")
    assert action["agency"]["agency_name"] == "transunion"
    assert action["reason_codes"] == []
    assert action["provider_reference"] == "abc"


def test_adverse_action_accepts_a_single_reason_string():
    action = build_adverse_action(
        {"reasons": "INSUFFICIENT_INCOME"}, provider="tu", external_ref=None
    )
    assert action["reason_codes"] == ["INSUFFICIENT_INCOME"]


def test_pending_decline_does_not_trigger_adverse_action():
    result = normalize_screening_response(
        {"id": "r", "status": "processing", "decision": "denied"}, provider="tu"
    )
    assert result.adverse_action is None
