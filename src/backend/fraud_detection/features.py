"""Claim features shared by training rows and live scoring."""

from __future__ import annotations

FEATURE_NAMES = [
    "em_level",
    "billed_ratio",
    "units_ratio",
    "unbundling",
    "near_duplicate_count",
]

# Office-visit level and a typical billed amount. Unknown CPTs stay neutral.
TYPICAL = {
    "99211": (1, 75.0),
    "99212": (2, 110.0),
    "99213": (3, 185.0),
    "99214": (4, 220.0),
    "99215": (5, 280.0),
}
DEFAULT_LEVEL = 3
DEFAULT_BILLED = 150.0
UNBUNDLE_PAIRS = (("93000", "93005"), ("93000", "93010"))


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_features(claim: dict) -> dict:
    lines = claim.get("lines") or []
    best_ratio = 0.0
    em_level = DEFAULT_LEVEL
    units_ratio = 0.0
    codes: list[str] = []
    for line in lines:
        cpt = str(line.get("cpt_code") or "")
        codes.append(cpt)
        level, typical = TYPICAL.get(cpt, (DEFAULT_LEVEL, DEFAULT_BILLED))
        ratio = _number(line.get("billed_amount")) / typical if typical else 0.0
        if ratio >= best_ratio:
            best_ratio = ratio
            em_level = level
        units_ratio = max(units_ratio, _number(line.get("units")))
    code_set = set(codes)
    unbundling = 1 if any(left in code_set and right in code_set for left, right in UNBUNDLE_PAIRS) else 0
    if "near_duplicate_count" in claim:
        near = int(_number(claim.get("near_duplicate_count")))
    else:
        flags = claim.get("flags") or []
        near = 2 if "POSSIBLE_DUPLICATE" in flags else 0
    return {
        "em_level": float(em_level),
        "billed_ratio": round(best_ratio, 4),
        "units_ratio": round(units_ratio, 4),
        "unbundling": float(unbundling),
        "near_duplicate_count": float(near),
    }


def feature_vector(features: dict) -> list[float]:
    return [float(features[name]) for name in FEATURE_NAMES]
