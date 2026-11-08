"""Write claim_risk_synthetic, the supervised training file."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from fraud_detection.features import FEATURE_NAMES, build_features

SEED = 11
ROW_COUNT = 2000
FRAUD_RATE = 0.04
LABEL_NOISE = 0.02
PROVIDER_COUNT = 40
TRAIN_PROVIDERS = 30
SCHEMES = ("upcoding", "excessive_units", "unbundling", "near_duplicate")


def dataset_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "fraud" / "claim_risk_synthetic.csv"


def _claim_for(scheme: str | None, rng: np.random.Generator) -> dict:
    if scheme == "upcoding":
        ratio = float(rng.uniform(4.0, 8.0))
        return {"lines": [{"cpt_code": "99215", "units": 1, "billed_amount": round(280.0 * ratio, 2)}]}
    if scheme == "excessive_units":
        units = int(rng.integers(6, 13))
        return {"lines": [{"cpt_code": "99213", "units": units, "billed_amount": 185.0}]}
    if scheme == "unbundling":
        return {
            "lines": [
                {"cpt_code": "93000", "units": 1, "billed_amount": 150.0},
                {"cpt_code": "93005", "units": 1, "billed_amount": 150.0},
            ]
        }
    if scheme == "near_duplicate":
        return {
            "lines": [{"cpt_code": "99213", "units": 1, "billed_amount": 185.0}],
            "near_duplicate_count": int(rng.integers(2, 6)),
        }
    ratio = float(rng.uniform(0.85, 1.2))
    return {"lines": [{"cpt_code": "99213", "units": 1, "billed_amount": round(185.0 * ratio, 2)}]}


def generate_rows(seed: int = SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    fraud_count = int(round(ROW_COUNT * FRAUD_RATE))
    fraud_ids = [int(index) for index in rng.choice(ROW_COUNT, size=fraud_count, replace=False)]
    scheme_of = {index: SCHEMES[position % len(SCHEMES)] for position, index in enumerate(fraud_ids)}
    flip_count = int(round(ROW_COUNT * LABEL_NOISE))
    flipped = {int(index) for index in rng.choice(ROW_COUNT, size=flip_count, replace=False)}
    rows: list[dict] = []
    for index in range(ROW_COUNT):
        scheme = scheme_of.get(index)
        provider_id = index % PROVIDER_COUNT
        features = build_features(_claim_for(scheme, rng))
        label = 1 if scheme else 0
        if index in flipped:
            label = 1 - label
        row = {
            "provider_id": provider_id,
            "split": "train" if provider_id < TRAIN_PROVIDERS else "test",
            "scheme": scheme or "clean",
            "label": label,
        }
        row.update(features)
        rows.append(row)
    return rows


def write_dataset(path: Path | None = None) -> Path:
    target = path or dataset_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = generate_rows()
    fieldnames = ["provider_id", "split", "scheme", "label", *FEATURE_NAMES]
    with target.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return target


def read_dataset(path: Path | None = None) -> list[dict]:
    target = path or dataset_path()
    with target.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    parsed: list[dict] = []
    for row in rows:
        item = {
            "provider_id": int(row["provider_id"]),
            "split": row["split"],
            "scheme": row["scheme"],
            "label": int(row["label"]),
        }
        for name in FEATURE_NAMES:
            item[name] = float(row[name])
        parsed.append(item)
    return parsed
