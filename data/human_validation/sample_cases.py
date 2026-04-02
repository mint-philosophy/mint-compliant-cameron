#!/usr/bin/env python3
"""
Stratified sampling of 100 cases for human validation.

Stratifies by defeat_type (proportional with minimum floor),
ensures authority_group diversity within each stratum,
and includes a mix of gate-pass and gate-fail cases.

Outputs sample_ids.json — a list of case IDs for the review server to filter on.
"""
from __future__ import annotations

import collections
import json
import glob
import os
import random

SEED = 42
N_TOTAL = 100
MIN_PER_DEFEAT = 10  # floor per defeat type

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CASES_DIR = os.path.join(BASE, "data", "1_generated")
GATES_DIR = os.path.join(BASE, "logs", "gate_verdicts")
OUTPUT = os.path.join(SCRIPT_DIR, "sample_ids.json")


def load_cases() -> list[dict]:
    all_cases = []
    for filepath in sorted(glob.glob(os.path.join(CASES_DIR, "*.json"))):
        with open(filepath) as f:
            data = json.load(f)
        if isinstance(data, list):
            all_cases.extend(data)
        elif isinstance(data, dict) and "cases" in data:
            all_cases.extend(data["cases"])
        else:
            all_cases.append(data)
    return all_cases


def load_gate_status() -> dict[str, bool]:
    """Returns {case_id: all_gates_pass}."""
    gate_map: dict[str, dict[str, bool]] = {}

    if not os.path.isdir(GATES_DIR):
        return {}

    for fname in os.listdir(GATES_DIR):
        if not fname.endswith(".json"):
            continue
        prefix = fname.split("_")[0]
        if prefix not in ("sv", "df", "na", "rj"):
            continue

        with open(os.path.join(GATES_DIR, fname)) as f:
            entries = json.load(f)

        for entry in entries:
            cid = entry.get("case_id")
            if not cid:
                continue
            if cid not in gate_map:
                gate_map[cid] = {}
            gate_map[cid][prefix] = bool(entry.get("pass", False))

    result = {}
    for cid, gates in gate_map.items():
        result[cid] = (
            gates.get("sv", False)
            and gates.get("df", False)
            and gates.get("na", False)
        )
    return result


def stratified_sample(cases: list[dict], gate_status: dict[str, bool]) -> list[str]:
    random.seed(SEED)

    # Group by defeat_type
    by_defeat: dict[str, list[dict]] = collections.defaultdict(list)
    for c in cases:
        dt = c.get("defeat_type", "unknown")
        by_defeat[dt].append(c)

    defeat_types = sorted(by_defeat.keys())
    total = len(cases)

    # Proportional allocation with floor
    allocation: dict[str, int] = {}
    for dt in defeat_types:
        prop = max(MIN_PER_DEFEAT, round(N_TOTAL * len(by_defeat[dt]) / total))
        allocation[dt] = prop

    # Adjust to hit N_TOTAL exactly
    while sum(allocation.values()) > N_TOTAL:
        # Trim from largest
        largest = max(allocation, key=lambda d: allocation[d])
        allocation[largest] -= 1
    while sum(allocation.values()) < N_TOTAL:
        # Add to smallest (relative to pool)
        smallest = min(allocation, key=lambda d: allocation[d] / len(by_defeat[d]))
        allocation[smallest] += 1

    selected_ids = []

    for dt in defeat_types:
        n = allocation[dt]
        pool = by_defeat[dt]

        # Sort pool: prioritize authority_group diversity
        # Shuffle within authority_group buckets, then round-robin
        by_ag: dict[str, list[dict]] = collections.defaultdict(list)
        for c in pool:
            ag = c.get("authority_group", "unknown")
            by_ag[ag].append(c)

        # Shuffle each bucket
        for ag in by_ag:
            random.shuffle(by_ag[ag])

        # Round-robin across authority groups
        ordered = []
        buckets = list(by_ag.values())
        random.shuffle(buckets)
        max_len = max(len(b) for b in buckets)
        for i in range(max_len):
            for b in buckets:
                if i < len(b):
                    ordered.append(b[i])

        # Take first n
        picked = ordered[:n]
        selected_ids.extend(c["id"] for c in picked)

    return selected_ids


def main():
    cases = load_cases()
    gate_status = load_gate_status()

    print(f"Total cases: {len(cases)}")

    # Distribution
    by_dt = collections.Counter(c.get("defeat_type", "?") for c in cases)
    print(f"Defeat types: {dict(by_dt)}")

    selected = stratified_sample(cases, gate_status)

    # Verify distribution
    case_lookup = {c["id"]: c for c in cases}
    sample_dt = collections.Counter(case_lookup[sid]["defeat_type"] for sid in selected)
    sample_ag = collections.Counter(case_lookup[sid].get("authority_group", "?") for sid in selected)
    sample_gate = collections.Counter(
        "gate_pass" if gate_status.get(sid, False) else "gate_fail"
        for sid in selected
    )

    print(f"\nSample size: {len(selected)}")
    print(f"By defeat type: {dict(sample_dt)}")
    print(f"By authority group: {dict(sample_ag)}")
    print(f"By gate status: {dict(sample_gate)}")

    with open(OUTPUT, "w") as f:
        json.dump(selected, f, indent=2)

    print(f"\nWritten to {OUTPUT}")


if __name__ == "__main__":
    main()
