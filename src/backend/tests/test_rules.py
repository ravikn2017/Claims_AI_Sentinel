"""One case per validation rule, plus REJECT beating MISSING_INFO."""

from datetime import date
from decimal import Decimal

from contracts.models import ClaimDraft
from payer_service.app.rules import Issue, MemberRow, PolicyRow, ProviderRow, Reference, validate

TODAY = date(2026, 10, 28)


def _draft(**overrides) -> ClaimDraft:
    payload = {
        "claim_type": "professional",
        "member": {
            "member_id": "MBR-100231",
            "first_name": "Jane",
            "last_name": "Doe",
            "dob": "1984-03-12",
        },
        "group_number": "GRP-7781",
        "billing_provider": {"npi": "1234567893", "name": "Lakeside Family Clinic"},
        "rendering_npi": "1987654328",
        "place_of_service": "11",
        "service_from": "2026-10-20",
        "service_to": "2026-10-20",
        "diagnosis_codes": ["E11.9", "I10"],
        "lines": [
            {
                "line_no": 1,
                "cpt_code": "99214",
                "modifiers": [],
                "units": 1,
                "billed_amount": "185.00",
                "service_date": "2026-10-20",
                "diagnosis_pointers": [1, 2],
            }
        ],
        "total_billed": "185.00",
    }
    payload.update(overrides)
    return ClaimDraft.model_validate(payload)


def _reference() -> Reference:
    reference = Reference()
    reference.members["MBR-100231"] = MemberRow("MBR-100231", "Jane", "Doe", date(1984, 3, 12))
    reference.members["MBR-400001"] = MemberRow("MBR-400001", "Alex", "Chen", date(1990, 5, 15))
    reference.members["MBR-300001"] = MemberRow("MBR-300001", "Pat", "Kim", date(1965, 11, 2))
    reference.policies = [
        PolicyRow("POL-100231", "MBR-100231", "SILVER-PPO-01", "GRP-7781", date(2020, 1, 1), None, "active"),
        PolicyRow("POL-300001", "MBR-300001", "SILVER-PPO-01", "GRP-3001", date(2020, 1, 1), date(2024, 6, 1), "terminated"),
        PolicyRow("POL-400001A", "MBR-400001", "SILVER-PPO-01", "GRP-ALPHA", date(2020, 1, 1), None, "active"),
        PolicyRow("POL-400001B", "MBR-400001", "BRONZE-HMO-01", "GRP-BETA", date(2020, 1, 1), None, "active"),
    ]
    reference.providers_by_npi["1234567893"] = ProviderRow("PRV-0042", "1234567893", "Lakeside", "in", 4, "Minneapolis", "MN")
    reference.providers_by_npi["1098765435"] = ProviderRow("PRV-0099", "1098765435", "Harbor", "out", 3, "Duluth", "MN")
    reference.cpt_codes = {"99214", "83036"}
    reference.icd10 = {"E11.9": True, "I10": True, "E11": False}
    return reference


def _codes(outcome) -> set[str]:
    return {issue.issue_code for issue in outcome.issues}


def test_clean_claim_validates():
    outcome = validate(_draft(), _reference(), today=TODAY)
    assert outcome.status == "VALIDATED"
    assert outcome.policy is not None and outcome.policy.policy_id == "POL-100231"


def test_missing_field():
    draft = _draft()
    draft.diagnosis_codes = []
    outcome = validate(draft, _reference(), today=TODAY)
    assert outcome.status == "PENDING_INFO"
    assert "MISSING_FIELD" in _codes(outcome)


def test_unconfirmed_field():
    outcome = validate(
        _draft(),
        _reference(),
        unconfirmed=[("billing_provider.npi", "Could not confirm billing_provider.npi from the document.")],
        today=TODAY,
    )
    assert "UNCONFIRMED_FIELD" in _codes(outcome)
    assert outcome.status == "PENDING_INFO"


def test_member_not_matched():
    draft = _draft(member={"member_id": "MBR-100231", "first_name": "Jane", "last_name": "Doe", "dob": "1980-01-01"})
    outcome = validate(draft, _reference(), today=TODAY)
    assert outcome.status == "PENDING_INFO"
    assert "MEMBER_NOT_MATCHED" in _codes(outcome)
    assert "NO_ACTIVE_COVERAGE" not in _codes(outcome)


def test_no_active_coverage():
    draft = _draft(member={"member_id": "MBR-300001", "first_name": "Pat", "last_name": "Kim", "dob": "1965-11-02"})
    outcome = validate(draft, _reference(), today=TODAY)
    assert outcome.status == "REJECTED"
    assert "NO_ACTIVE_COVERAGE" in _codes(outcome)


def test_policy_ambiguous_and_group_mismatch():
    draft = _draft(
        member={"member_id": "MBR-400001", "first_name": "Alex", "last_name": "Chen", "dob": "1990-05-15"},
        group_number=None,
    )
    ambiguous = validate(draft, _reference(), today=TODAY)
    assert "POLICY_AMBIGUOUS" in _codes(ambiguous)
    mismatch = validate(_draft(group_number="GRP-OTHER"), _reference(), today=TODAY)
    assert mismatch.status == "VALIDATED"
    assert "GROUP_MISMATCH" in mismatch.flags


def test_invalid_npi_and_provider_not_on_file_and_out_of_network():
    invalid = validate(_draft(billing_provider={"npi": "1234567890", "name": "Lakeside"}), _reference(), today=TODAY)
    assert "INVALID_NPI" in _codes(invalid)
    assert "PROVIDER_NOT_ON_FILE" not in _codes(invalid)
    missing = validate(_draft(billing_provider={"npi": "1555123458", "name": "Unknown"}), _reference(), today=TODAY)
    assert missing.status == "REJECTED"
    assert "PROVIDER_NOT_ON_FILE" in _codes(missing)
    outside = validate(_draft(billing_provider={"npi": "1098765435", "name": "Harbor"}), _reference(), today=TODAY)
    assert outside.status == "VALIDATED"


def test_invalid_code_amount_date_pointer_and_timely_filing():
    bad_code = validate(_draft(lines=[{
        "line_no": 2, "cpt_code": "8303", "modifiers": [], "units": 1,
        "billed_amount": "185.00", "service_date": "2026-10-20", "diagnosis_pointers": [1],
    }]), _reference(), today=TODAY)
    assert "INVALID_CODE" in _codes(bad_code)
    category = validate(_draft(diagnosis_codes=["E11"]), _reference(), today=TODAY)
    assert "INVALID_CODE" in _codes(category)
    amount = validate(_draft(total_billed="10.00"), _reference(), today=TODAY)
    assert "AMOUNT_MISMATCH" in _codes(amount)
    units = validate(_draft(lines=[{
        "line_no": 1, "cpt_code": "99214", "modifiers": [], "units": 0,
        "billed_amount": "185.00", "service_date": "2026-10-20", "diagnosis_pointers": [1],
    }]), _reference(), today=TODAY)
    assert "AMOUNT_MISMATCH" in _codes(units)
    future = validate(_draft(service_from="2026-11-01", service_to="2026-11-01", lines=[{
        "line_no": 1, "cpt_code": "99214", "modifiers": [], "units": 1,
        "billed_amount": "185.00", "service_date": "2026-11-01", "diagnosis_pointers": [1],
    }]), _reference(), today=TODAY)
    assert "INVALID_DATE" in _codes(future)
    pointer = validate(_draft(lines=[{
        "line_no": 1, "cpt_code": "99214", "modifiers": [], "units": 1,
        "billed_amount": "185.00", "service_date": "2026-10-20", "diagnosis_pointers": [9],
    }]), _reference(), today=TODAY)
    assert "INVALID_POINTER" in _codes(pointer)
    late = validate(_draft(
        service_from="2020-01-15", service_to="2020-01-15",
        lines=[{
            "line_no": 1, "cpt_code": "99214", "modifiers": [], "units": 1,
            "billed_amount": "185.00", "service_date": "2020-01-15", "diagnosis_pointers": [1],
        }],
    ), _reference(), today=TODAY)
    assert late.status == "REJECTED"
    assert "TIMELY_FILING" in _codes(late)


def test_possible_duplicate_is_only_a_flag():
    reference = _reference()
    from payer_service.app.rules import ClaimSignature

    draft = _draft()
    reference.existing.append(
        ClaimSignature("CLM-OTHER", "MBR-100231", "1234567893", date(2026, 10, 20), date(2026, 10, 20), (("99214", 1, "185.00", date(2026, 10, 20)),))
    )
    outcome = validate(draft, reference, today=TODAY)
    assert outcome.status == "VALIDATED"
    assert "POSSIBLE_DUPLICATE" in outcome.flags


def test_reject_beats_missing_info():
    outcome = validate(
        _draft(
            service_from="2020-01-15",
            service_to="2020-01-15",
            lines=[{
                "line_no": 1, "cpt_code": "8303", "modifiers": [], "units": 1,
                "billed_amount": "185.00", "service_date": "2020-01-15", "diagnosis_pointers": [1],
            }],
        ),
        _reference(),
        today=TODAY,
    )
    assert outcome.status == "REJECTED"
    assert {"TIMELY_FILING", "INVALID_CODE"} <= _codes(outcome)
    assert all(isinstance(issue, Issue) for issue in outcome.issues)
