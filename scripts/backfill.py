#!/usr/bin/env python3
"""
Matrix-aware backfill generation — generates exactly the cases needed per cell
based on OV gate results and fail rates.

Reads OV results, computes per-cell deficits with overshoot for expected gate
losses, then generates and appends new cases to existing files.

Usage:
    python3 scripts/backfill.py --dry-run            # Preview generation plan
    python3 scripts/backfill.py                       # Generate all backfill cases
    python3 scripts/backfill.py --target 850          # Custom total target
    python3 scripts/backfill.py --model google/gemini-3-pro-preview  # Override model
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from math import ceil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = DATA_DIR / "1_generated"
GATED_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"
INPUTS_DIR = DATA_DIR / "0_inputs"

sys.path.insert(0, str(SCRIPT_DIR))
from openrouter_client import OpenRouterClient
from supplement import (
    generate_supplement,
    save_merged,
    load_existing,
    get_max_case_index,
    assign_ids,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_ov_results() -> dict[str, dict]:
    ov_path = GATED_DIR / "ov_full_results.json"
    with open(ov_path) as f:
        return json.load(f)


def load_tier_targets() -> dict[str, int]:
    """Load tier targets from matrix.json."""
    matrix_path = INPUTS_DIR / "matrix.json"
    with open(matrix_path) as f:
        matrix = json.load(f)

    tier_map = {1: 20, 2: 10, 3: 5}
    targets = {}

    for tier_name in ["tier_1", "tier_2", "tier_3"]:
        tier = matrix["cell_targets"].get(tier_name, {})
        tier_num = int(tier_name.split("_")[1])
        for cell_str in tier.get("cells", []):
            defeat, authority = cell_str.split(":", 1)
            stem = f"{defeat}_{authority}"
            targets[stem] = tier_map[tier_num]

    return targets


def compute_backfill_plan(target_total: int = 850) -> list[dict]:
    """
    Compute per-cell generation targets based on OV results.
    Returns list of {defeat_type, authority_type, to_generate, deficit, cell_fail_rate}.
    """
    ov_results = load_ov_results()
    tier_targets = load_tier_targets()

    # Per-cell pass/fail counts
    cell_counts: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "total": 0})
    for case_id, result in ov_results.items():
        parts = case_id.split("_")
        if parts[0] == "seed":
            parts = parts[1:]
        stem = "_".join(parts[:-1])
        cell_counts[stem]["total"] += 1
        if result.get("pass"):
            cell_counts[stem]["pass"] += 1
        else:
            cell_counts[stem]["fail"] += 1

    # Global fail rate
    total_pass = sum(v["pass"] for v in cell_counts.values())
    total_fail = sum(v["fail"] for v in cell_counts.values())
    global_fr = total_fail / (total_pass + total_fail) if (total_pass + total_fail) > 0 else 0.25

    plan = []
    for stem, counts in sorted(cell_counts.items()):
        tier_target = tier_targets.get(stem, 5)
        cell_target = max(tier_target, counts["total"])

        passing = counts["pass"]
        deficit = max(0, cell_target - passing)

        if deficit == 0:
            continue

        # Cell-specific fail rate (use global if small sample)
        if counts["total"] >= 5:
            cell_fr = counts["fail"] / counts["total"]
        else:
            cell_fr = global_fr

        # Overshoot
        if cell_fr < 1.0:
            to_gen = ceil(deficit / (1 - cell_fr))
        else:
            to_gen = deficit * 2

        # Parse stem back to defeat_type and authority_type
        # Try all known authority types to find the split point
        parts = stem.split("_")
        defeat_type = None
        authority_type = None

        # Check existing generated files to find the right split
        gen_file = GENERATED_DIR / f"{stem}.json"
        if gen_file.exists():
            with open(gen_file) as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            defeat_type = meta.get("defeat_type", "")
            authority_type = meta.get("authority_type", "")

        if not defeat_type or not authority_type:
            logger.warning(f"Could not parse stem: {stem} — skipping")
            continue

        plan.append({
            "defeat_type": defeat_type,
            "authority_type": authority_type,
            "stem": stem,
            "had": counts["total"],
            "passing": passing,
            "deficit": deficit,
            "cell_fail_rate": cell_fr,
            "to_generate": to_gen,
        })

    return plan


def main():
    parser = argparse.ArgumentParser(description="Matrix-aware backfill generation")
    parser.add_argument("--target", type=int, default=850, help="Target total passing cases")
    parser.add_argument("--dry-run", action="store_true", help="Preview plan without generating")
    parser.add_argument("--model", type=str, default=None, help="Override generation model")
    args = parser.parse_args()

    plan = compute_backfill_plan(target_total=args.target)
    total_to_gen = sum(p["to_generate"] for p in plan)

    logger.info(f"{'=' * 60}")
    logger.info(f"BACKFILL GENERATION PLAN")
    logger.info(f"{'=' * 60}")
    logger.info(f"Cells needing backfill: {len(plan)}")
    logger.info(f"Total cases to generate: {total_to_gen}")
    logger.info(f"")

    for p in sorted(plan, key=lambda x: -x["deficit"]):
        logger.info(
            f"  {p['stem']:<50s} deficit={p['deficit']:>2d}  "
            f"gen={p['to_generate']:>2d}  fr={p['cell_fail_rate']:.0%}"
        )

    if args.dry_run:
        logger.info(f"\nDRY RUN — no cases generated.")
        return

    # Initialize client
    client = OpenRouterClient(model_name=args.model)
    logger.info(f"\nUsing model: {client.model_name}")

    total_generated = 0
    total_cells = 0
    errors = 0

    for i, p in enumerate(sorted(plan, key=lambda x: -x["deficit"])):
        defeat_type = p["defeat_type"]
        authority_type = p["authority_type"]
        to_gen = p["to_generate"]

        logger.info(f"\n[{i+1}/{len(plan)}] {defeat_type} x {authority_type} — generating {to_gen}")

        existing_data = load_existing(defeat_type, authority_type)
        existing_cases = existing_data.get("cases", []) if existing_data else []
        max_index = get_max_case_index(existing_cases, defeat_type, authority_type)

        try:
            new_cases = generate_supplement(client, defeat_type, authority_type, to_gen)
        except Exception as e:
            logger.error(f"  Generation failed: {e}")
            errors += 1
            continue

        if new_cases:
            new_cases = assign_ids(new_cases, defeat_type, authority_type, max_index)
            save_merged(existing_data, new_cases, defeat_type, authority_type, client.model_name)
            total_generated += len(new_cases)
            total_cells += 1
        else:
            logger.warning(f"  No cases returned for {defeat_type} x {authority_type}")
            errors += 1

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"BACKFILL COMPLETE")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Cases generated:  {total_generated}")
    logger.info(f"  Cells filled:     {total_cells}")
    logger.info(f"  Errors:           {errors}")

    # Count new total
    new_total = 0
    for f in GENERATED_DIR.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
        cases = data.get("cases", data) if isinstance(data, dict) else data
        if isinstance(cases, list):
            new_total += len(cases)
    logger.info(f"  New grand total:  {new_total} cases in 1_generated/")
    logger.info(f"")
    logger.info(f"Next: run OV gate on new cases (run_ov_full.py --resume)")


if __name__ == "__main__":
    main()
