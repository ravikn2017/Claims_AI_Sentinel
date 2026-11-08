"""Load the small synthetic reference world. Safe to run more than once.

Does not insert claims and does not remove claim rows. Each run appends one
reference.load audit event.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "backend"))

load_dotenv(ROOT / ".env")

from contracts.models import SubmissionRequest  # noqa: E402
from db_url import database_url  # noqa: E402
from portal.app.passwords import hash_password  # noqa: E402

DEMO_PASSWORD = "sentinel"
USERS = [
    ("PRV-0042", "provider@example.test", "Lakeside Family Clinic", "provider", "user", "PRV-0042"),
    ("MBR-100231", "member@example.test", "Jane Doe", "member", "user", "MBR-100231"),
    ("REV-01", "reviewer@example.test", "Alex Reviewer", "reviewer", "user", None),
    ("INV-01", "investigator@example.test", "Sam Investigator", "investigator", "user", None),
    ("OPS-01", "ops@example.test", "Platform lead", "ops", "operator", None),
]

MEMBERS = [
    ("MBR-100231", "Jane", "Doe", "1984-03-12", "F"),
    ("MBR-200001", "Sam", "Rivera", "1979-07-22", "M"),
    ("MBR-300001", "Pat", "Kim", "1965-11-02", "F"),
    ("MBR-400001", "Alex", "Chen", "1990-05-15", "M"),
]

POLICIES = [
    ("POL-100231", "MBR-100231", "SILVER-PPO-01", "GRP-7781", "2020-01-01", None, "active"),
    ("POL-200001", "MBR-200001", "BRONZE-HMO-01", "GRP-2201", "2020-01-01", None, "active"),
    ("POL-300001", "MBR-300001", "SILVER-PPO-01", "GRP-3001", "2020-01-01", "2024-06-01", "terminated"),
    ("POL-400001A", "MBR-400001", "SILVER-PPO-01", "GRP-ALPHA", "2020-01-01", None, "active"),
    ("POL-400001B", "MBR-400001", "BRONZE-HMO-01", "GRP-BETA", "2020-01-01", None, "active"),
]

# NPIs pass the CMS Luhn check over 80840 + the 10-digit number.
PROVIDERS = [
    ("PRV-0042", "1234567893", "Lakeside Family Clinic", "207Q00000X", "in", 4, "Minneapolis", "MN"),
    ("PRV-0099", "1098765435", "Harbor Outpatient", "207Q00000X", "out", 3, "Duluth", "MN"),
    ("PRV-0101", "1678901236", "Cedar Low Quality Clinic", "207Q00000X", "in", 2, "Rochester", "MN"),
]

CPT = [
    ("99213", "Office visit, established, low", True),
    ("99214", "Office visit, established, moderate", True),
    ("99285", "Emergency department visit, high", True),
    ("71046", "Chest X-ray, 2 views", True),
    ("70553", "MRI brain without and with contrast", True),
    ("72148", "MRI lumbar spine without contrast", True),
    ("97110", "Therapeutic exercise", True),
    ("90837", "Psychotherapy, 60 minutes", True),
    ("43644", "Laparoscopic gastric bypass", True),
    ("19357", "Breast reconstruction with tissue expander", True),
    ("15823", "Upper eyelid blepharoplasty", True),
    ("97810", "Acupuncture, initial 15 minutes", True),
    ("93000", "Electrocardiogram, routine ECG", True),
    ("83036", "Hemoglobin glycosylated A1C", True),
]

ICD10 = [
    ("E11.9", "Type 2 diabetes mellitus without complications", True),
    ("I10", "Essential hypertension", True),
    ("E11", "Type 2 diabetes mellitus", False),
]

# Exact rows from the policy compliance design. 93000 is intentionally absent.
BENEFITS = [
    ("SILVER-PPO-01", "99213", "office_visit", True, False, "§4.1"),
    ("SILVER-PPO-01", "99214", "office_visit", True, False, "§4.1"),
    ("SILVER-PPO-01", "99285", "emergency", True, False, "§4.2"),
    ("SILVER-PPO-01", "71046", "imaging", True, False, "§4.3"),
    ("SILVER-PPO-01", "70553", "advanced_imaging", True, True, "§4.3"),
    ("SILVER-PPO-01", "72148", "advanced_imaging", True, True, "§4.3"),
    ("SILVER-PPO-01", "97110", "rehab_therapy", True, False, "§4.4"),
    ("SILVER-PPO-01", "90837", "mental_health", True, False, "§4.5"),
    ("SILVER-PPO-01", "43644", "bariatric_surgery", True, True, "§4.6"),
    ("SILVER-PPO-01", "19357", "reconstructive", True, False, "§4.7"),
    ("SILVER-PPO-01", "15823", "cosmetic", False, False, "§5.2"),
    ("SILVER-PPO-01", "97810", "acupuncture", True, False, "§4.8"),
    ("BRONZE-HMO-01", "99213", "office_visit", True, False, "§4.1"),
    ("BRONZE-HMO-01", "99214", "office_visit", True, False, "§4.1"),
    ("BRONZE-HMO-01", "99285", "emergency", True, False, "§4.2"),
    ("BRONZE-HMO-01", "71046", "imaging", True, False, "§4.3"),
    ("BRONZE-HMO-01", "70553", "advanced_imaging", True, True, "§4.3"),
    ("BRONZE-HMO-01", "72148", "advanced_imaging", True, True, "§4.3"),
    ("BRONZE-HMO-01", "97110", "rehab_therapy", True, False, "§4.4"),
    ("BRONZE-HMO-01", "90837", "mental_health", True, False, "§4.5"),
    ("BRONZE-HMO-01", "43644", "bariatric_surgery", False, False, "§5.3"),
    ("BRONZE-HMO-01", "19357", "reconstructive", True, False, "§4.7"),
    ("BRONZE-HMO-01", "15823", "cosmetic", False, False, "§5.2"),
    ("BRONZE-HMO-01", "97810", "acupuncture", False, False, "§5.4"),
]


def _validate_fixtures() -> list[str]:
    names = []
    for path in sorted((ROOT / "data" / "fixtures").glob("*.json")):
        SubmissionRequest.model_validate(json.loads(path.read_text()))
        names.append(path.name)
    return names


def seed() -> None:
    fixtures = _validate_fixtures()
    engine = create_engine(database_url(), pool_pre_ping=True)
    with engine.begin() as conn:
        for row in MEMBERS:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.member (member_id, first_name, last_name, dob, gender)
                    VALUES (:member_id, :first_name, :last_name, :dob, :gender)
                    ON CONFLICT (member_id) DO NOTHING
                    """
                ),
                {
                    "member_id": row[0],
                    "first_name": row[1],
                    "last_name": row[2],
                    "dob": row[3],
                    "gender": row[4],
                },
            )
        for row in POLICIES:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.policy (
                        policy_id, member_id, plan_code, group_number,
                        effective_date, termination_date, status
                    )
                    VALUES (
                        :policy_id, :member_id, :plan_code, :group_number,
                        :effective_date, :termination_date, :status
                    )
                    ON CONFLICT (policy_id) DO NOTHING
                    """
                ),
                {
                    "policy_id": row[0],
                    "member_id": row[1],
                    "plan_code": row[2],
                    "group_number": row[3],
                    "effective_date": row[4],
                    "termination_date": row[5],
                    "status": row[6],
                },
            )
        for row in PROVIDERS:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.provider (
                        provider_id, npi, name, taxonomy_code, network_status,
                        quality_rating, city, state
                    )
                    VALUES (
                        :provider_id, :npi, :name, :taxonomy_code, :network_status,
                        :quality_rating, :city, :state
                    )
                    ON CONFLICT (provider_id) DO NOTHING
                    """
                ),
                {
                    "provider_id": row[0],
                    "npi": row[1],
                    "name": row[2],
                    "taxonomy_code": row[3],
                    "network_status": row[4],
                    "quality_rating": row[5],
                    "city": row[6],
                    "state": row[7],
                },
            )
        for row in CPT:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.ref_cpt (code, description, active)
                    VALUES (:code, :description, :active)
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                {"code": row[0], "description": row[1], "active": row[2]},
            )
        for row in ICD10:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.ref_icd10 (code, description, billable)
                    VALUES (:code, :description, :billable)
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                {"code": row[0], "description": row[1], "billable": row[2]},
            )
        for row in BENEFITS:
            conn.execute(
                text(
                    """
                    INSERT INTO claims.plan_benefit (
                        plan_code, cpt_code, benefit_category, is_covered,
                        requires_prior_auth, policy_section
                    )
                    VALUES (
                        :plan_code, :cpt_code, :benefit_category, :is_covered,
                        :requires_prior_auth, :policy_section
                    )
                    ON CONFLICT (plan_code, cpt_code) DO NOTHING
                    """
                ),
                {
                    "plan_code": row[0],
                    "cpt_code": row[1],
                    "benefit_category": row[2],
                    "is_covered": row[3],
                    "requires_prior_auth": row[4],
                    "policy_section": row[5],
                },
            )
        password_hash = hash_password(DEMO_PASSWORD)
        for row in USERS:
            conn.execute(
                text(
                    """
                    INSERT INTO portal.app_user (
                        user_id, email, display_name, password_hash, role, actor_type, submitter_id
                    )
                    VALUES (
                        :user_id, :email, :display_name, :password_hash, :role, :actor_type, :submitter_id
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        display_name = EXCLUDED.display_name,
                        password_hash = EXCLUDED.password_hash,
                        role = EXCLUDED.role,
                        actor_type = EXCLUDED.actor_type,
                        submitter_id = EXCLUDED.submitter_id
                    """
                ),
                {
                    "user_id": row[0],
                    "email": row[1],
                    "display_name": row[2],
                    "password_hash": password_hash,
                    "role": row[3],
                    "actor_type": row[4],
                    "submitter_id": row[5],
                },
            )
        conn.execute(
            text(
                """
                INSERT INTO claims.audit_event (
                    actor_type, actor_id, actor_role, action, reason, details
                )
                VALUES (
                    'operator', 'ops:seed', 'ops', 'reference.load',
                    'phase 3 reference seed',
                    CAST(:details AS jsonb)
                )
                """
            ),
            {"details": json.dumps({"script": "db/seed.py", "fixtures": fixtures})},
        )
        counts = {}
        for table in ("member", "policy", "provider", "ref_cpt", "ref_icd10", "plan_benefit"):
            counts[table] = conn.execute(text(f"SELECT count(*) FROM claims.{table}")).scalar_one()
    engine.dispose()
    print("seeded", counts)
    print("fixtures", fixtures)
    print("demo login password:", DEMO_PASSWORD)


if __name__ == "__main__":
    seed()
