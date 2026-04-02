#!/usr/bin/env python3
"""
Stratified sampling of 300 evaluation items for blind human review (Phase 2b).

Stratifies to ensure:
  - response_type floor: ≥80 each (helps / deflects / hard_refusal)
  - defeat_type floor: ≥40 each (5 types)
  - model floor: ≥10 each
  - engages_with_defeat: ≥100 each (yes / no)

Outputs:
  eval_sample_300.json      — list of review_keys (case_id__model_slug)
  eval_sample_300_meta.json — stratification stats + full item list
"""
from __future__ import annotations

import collections
import glob
import json
import os
import random

SEED = 42
N_TOTAL = 300
RT_FLOOR = 80      # min per response_type
ENG_FLOOR = 100    # min per engages_with_defeat value
MODEL_FLOOR = 10   # min per model
DEFEAT_FLOOR = 40  # min per defeat_type

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# scripts live in v4/data/human_validation/ → go up two levels to reach v4/
BASE = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
EVALUATED_DIR = os.path.join(BASE, "data", "4_evaluated")
OUTPUT = os.path.join(SCRIPT_DIR, "eval_sample_300.json")
META_OUTPUT = os.path.join(SCRIPT_DIR, "eval_sample_300_meta.json")

# Sorted longest-first to prevent greedy short matches
DEFEAT_TYPES = sorted([
    "application_defeat",
    "content_defeat",
    "exception_justified",
    "illegitimate_authority",
    "control",
], key=len, reverse=True)


def parse_file_stem(stem: str):
    for dt in DEFEAT_TYPES:
        idx = stem.find(dt)
        if idx == -1:
            continue
        model_slug = stem[:idx].rstrip("_")
        authority_type = stem[idx + len(dt):].lstrip("_")
        if model_slug and authority_type:
            return model_slug, dt, authority_type
    return None


def load_all_items() -> list[dict]:
    """Load all evaluation entries from 4_evaluated/."""
    items = []
    for filepath in sorted(glob.glob(os.path.join(EVALUATED_DIR, "*.json"))):
        stem = os.path.basename(filepath)[:-5]
        parsed = parse_file_stem(stem)
        if parsed is None:
            continue
        model_slug, defeat_type, authority_type = parsed
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        for ev in data.get("evaluations", []):
            case_id = ev.get("case_id", "")
            if not case_id:
                continue
            eval_ = ev.get("evaluation", {})
            rt = eval_.get("response_type", "deflects")
            eng = eval_.get("engages_with_defeat", "no")
            ih = eval_.get("independent_harm", False)
            review_key = f"{case_id}__{model_slug}"
            items.append({
                "review_key": review_key,
                "case_id": case_id,
                "model_slug": model_slug,
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                "response_type": rt,
                "engages_with_defeat": "yes" if str(eng).lower() in ("yes", "true", "1") else "no",
                "independent_harm": "yes" if ih else "no",
            })
    return items


def stratified_sample(items: list[dict]) -> list[dict]:
    """
    Two-pass stratified sample:
      Pass 1 — guarantee RT floor (≥80 each)
      Pass 2 — fill remaining slots from leftover, biasing toward
               under-represented defeat_types and models
    """
    random.seed(SEED)

    # Deduplicate by review_key (keep first occurrence)
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        if item["review_key"] not in seen:
            seen.add(item["review_key"])
            unique.append(item)

    # Group by response_type and shuffle within groups
    by_rt: dict[str, list[dict]] = collections.defaultdict(list)
    for item in unique:
        by_rt[item["response_type"]].append(item)
    for pool in by_rt.values():
        random.shuffle(pool)

    selected: list[dict] = []
    remaining_pool: list[dict] = []

    # Pass 1: take RT_FLOOR from each response_type
    for rt, pool in by_rt.items():
        take = min(RT_FLOOR, len(pool))
        selected.extend(pool[:take])
        remaining_pool.extend(pool[take:])

    # Pass 2: fill to N_TOTAL from remaining, prioritising under-represented strata
    random.shuffle(remaining_pool)

    # Score items by how much they contribute to under-represented strata
    def coverage_score(item: dict, current: list[dict]) -> int:
        """Higher = more valuable (rarer combination in current selection)."""
        dt_counts = collections.Counter(i["defeat_type"] for i in current)
        model_counts = collections.Counter(i["model_slug"] for i in current)
        eng_counts = collections.Counter(i["engages_with_defeat"] for i in current)
        score = 0
        if dt_counts.get(item["defeat_type"], 0) < DEFEAT_FLOOR:
            score += 10
        if model_counts.get(item["model_slug"], 0) < MODEL_FLOOR:
            score += 5
        if eng_counts.get(item["engages_with_defeat"], 0) < ENG_FLOOR:
            score += 3
        return score

    need = N_TOTAL - len(selected)
    if need > 0 and remaining_pool:
        # Greedy: sort remaining by coverage_score descending (stable)
        remaining_pool.sort(key=lambda x: -coverage_score(x, selected))
        selected.extend(remaining_pool[:need])
    elif need < 0:
        # Over-selected (shouldn't happen with defaults, but trim if so)
        random.shuffle(selected)
        selected = selected[:N_TOTAL]

    random.shuffle(selected)
    return selected


def main():
    items = load_all_items()
    print(f"Total evaluation entries: {len(items)}")

    sample = stratified_sample(items)
    print(f"Sample size: {len(sample)}")

    # Compute stats
    rt_counts = collections.Counter(i["response_type"] for i in sample)
    eng_counts = collections.Counter(i["engages_with_defeat"] for i in sample)
    dt_counts = collections.Counter(i["defeat_type"] for i in sample)
    model_counts = collections.Counter(i["model_slug"] for i in sample)
    ih_counts = collections.Counter(str(i["independent_harm"]) for i in sample)

    print(f"\nResponse type: {dict(rt_counts)}")
    print(f"Engages w/ defeat: {dict(eng_counts)}")
    print(f"Defeat type: {dict(dt_counts)}")
    print(f"Independent harm: {dict(ih_counts)}")
    print(f"Models ({len(model_counts)} unique): {dict(sorted(model_counts.items()))}")

    # Check floors (only for strata large enough to have floor items)
    all_items_lookup = {i["review_key"]: i for i in items}
    pool_rt = collections.Counter(i["response_type"] for i in items)
    pool_model = collections.Counter(i["model_slug"] for i in items)
    pool_dt = collections.Counter(i["defeat_type"] for i in items)

    rt_ok = all(
        rt_counts.get(rt, 0) >= min(RT_FLOOR, pool_rt.get(rt, 0))
        for rt in ["helps", "hard_refusal", "deflects"]
    )
    dt_ok = all(
        dt_counts.get(dt, 0) >= min(DEFEAT_FLOOR, pool_dt.get(dt, 0))
        for dt in ["application_defeat", "content_defeat", "exception_justified",
                   "illegitimate_authority", "control"]
    )
    model_ok = all(
        model_counts.get(m, 0) >= min(MODEL_FLOOR, pool_model.get(m, 0))
        for m in pool_model
    )
    floors_ok = rt_ok and dt_ok and model_ok
    print(f"\nFloors satisfied: {floors_ok} (rt={rt_ok}, dt={dt_ok}, model={model_ok})")

    review_keys = [i["review_key"] for i in sample]
    with open(OUTPUT, "w") as f:
        json.dump(review_keys, f, indent=2)

    meta = {
        "total": len(sample),
        "floors_ok": floors_ok,
        "rt_floor": RT_FLOOR,
        "eng_floor": ENG_FLOOR,
        "model_floor": MODEL_FLOOR,
        "defeat_floor": DEFEAT_FLOOR,
        "response_type_counts": dict(rt_counts),
        "engages_with_defeat_counts": dict(eng_counts),
        "defeat_type_counts": dict(dt_counts),
        "independent_harm_counts": dict(ih_counts),
        "model_counts": dict(sorted(model_counts.items())),
        "sample_items": sample,
    }
    with open(META_OUTPUT, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWritten to: {OUTPUT}")
    print(f"Meta written to: {META_OUTPUT}")


if __name__ == "__main__":
    main()
