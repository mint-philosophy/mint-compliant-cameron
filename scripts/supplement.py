#!/usr/bin/env python3
"""
Supplemental case generation for v4 compliance overspill project.

Generates additional cases to bring each matrix cell up to new target counts,
appending to existing files without overwriting.

Usage:
    python3 scripts/supplement.py --dry-run --all
    python3 scripts/supplement.py --all --resume
    python3 scripts/supplement.py --defeat-type control --authority-type workplace
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

# ---------------------------------------------------------------------------
# Configurable supplement targets per tier
# ---------------------------------------------------------------------------
TIER_1_TARGET = 20
TIER_2_TARGET = 10
TIER_3_TARGET = 5

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
INPUTS_DIR = DATA_DIR / "0_inputs"
OUTPUT_DIR = DATA_DIR / "1_generated"
FILTERED_DIR = DATA_DIR / "2_filtered"

sys.path.insert(0, str(SCRIPT_DIR))
from openrouter_client import OpenRouterClient

# Import generation infrastructure from generate.py
from generate import (
    build_prompt,
    extract_json_array,
    load_matrix,
    validate_case,
    VALID_DIMENSIONS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# System prompt identical to generate.py
SYSTEM_PROMPT = (
    "You are a dataset generator for AI safety research. "
    "Return only valid JSON -- a JSON array of case objects. "
    "No commentary, no markdown fences, no text before or after the JSON."
)
TEMPERATURE = 0.7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_supplement_cells(matrix: dict) -> list[tuple[str, str, int]]:
    """
    Return list of (defeat_type, authority_type, new_target) for all
    non-implausible cells, using the supplement tier targets.
    """
    implausible = set()
    for entry in matrix["cell_targets"].get("implausible", {}).get("cells", []):
        cell_str = entry if isinstance(entry, str) else entry.get("cell", "")
        implausible.add(cell_str)

    tier_targets = {
        "tier_1": TIER_1_TARGET,
        "tier_2": TIER_2_TARGET,
        "tier_3": TIER_3_TARGET,
    }

    cells = []
    for tier_name, target in tier_targets.items():
        tier = matrix["cell_targets"].get(tier_name, {})
        for cell_str in tier.get("cells", []):
            if cell_str in implausible:
                continue
            defeat, authority = cell_str.split(":", 1)
            cells.append((defeat, authority, target))

    return cells


def output_path(defeat_type: str, authority_type: str) -> Path:
    """Get the output file path for a cell."""
    return OUTPUT_DIR / f"{defeat_type}_{authority_type}.json"


def load_existing(defeat_type: str, authority_type: str) -> dict | None:
    """Load an existing generated file, or return None if it does not exist."""
    fpath = output_path(defeat_type, authority_type)
    if not fpath.exists():
        return None
    with open(fpath) as f:
        return json.load(f)


def get_max_case_index(cases: list[dict], defeat_type: str, authority_type: str) -> int:
    """
    Parse existing case IDs like 'seed_{defeat}_{authority}_{N}' and return
    the maximum N found, or 0 if no cases.
    """
    prefix = f"seed_{defeat_type}_{authority_type}_"
    max_n = 0
    for case in cases:
        case_id = case.get("id", "")
        if case_id.startswith(prefix):
            try:
                n = int(case_id[len(prefix):])
                max_n = max(max_n, n)
            except ValueError:
                pass
    # Fallback: if no matching IDs found, use length of existing cases
    if max_n == 0 and cases:
        max_n = len(cases)
    return max_n


def assign_ids(
    new_cases: list[dict],
    defeat_type: str,
    authority_type: str,
    start_index: int,
) -> list[dict]:
    """Assign sequential IDs to new cases starting from start_index + 1."""
    for i, case in enumerate(new_cases):
        case["id"] = f"seed_{defeat_type}_{authority_type}_{start_index + i + 1}"
    return new_cases


def save_merged(
    existing_data: dict | None,
    new_cases: list[dict],
    defeat_type: str,
    authority_type: str,
    model_name: str,
) -> None:
    """Merge new cases into the existing file and save."""
    fpath = output_path(defeat_type, authority_type)

    if existing_data is None:
        # No existing file -- create from scratch
        existing_cases = []
        metadata = {}
    else:
        existing_cases = existing_data.get("cases", [])
        metadata = existing_data.get("metadata", {})

    merged_cases = existing_cases + new_cases

    # Update metadata
    metadata["actual_count"] = len(merged_cases)
    metadata["timestamp"] = datetime.now(timezone.utc).isoformat()
    metadata["defeat_type"] = defeat_type
    metadata["authority_type"] = authority_type
    metadata["model"] = model_name
    metadata["supplement_added"] = len(new_cases)
    metadata["supplement_timestamp"] = datetime.now(timezone.utc).isoformat()

    payload = {
        "metadata": metadata,
        "cases": merged_cases,
    }

    with open(fpath, "w") as f:
        json.dump(payload, f, indent=2)

    logger.info(f"Saved {len(merged_cases)} total cases to {fpath} (+{len(new_cases)} new)")


def generate_supplement(
    client: OpenRouterClient,
    defeat_type: str,
    authority_type: str,
    delta: int,
) -> list[dict]:
    """Generate delta new cases for a single matrix cell."""
    logger.info(f"Generating {delta} supplement cases for {defeat_type} x {authority_type}")

    prompt = build_prompt(defeat_type, authority_type, delta)

    response = client.generate_with_retry(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        temperature=TEMPERATURE,
        max_tokens=delta * 1500,
        json_mode=True,
    )

    if not response:
        logger.error(f"No response for {defeat_type} x {authority_type}")
        return []

    cases = extract_json_array(response)
    if cases is None:
        logger.error(f"Failed to parse JSON for {defeat_type} x {authority_type}")
        logger.debug(f"Raw response: {response[:500]}")
        return []

    # Validate each case (log issues but keep all)
    for i, case in enumerate(cases):
        issues = validate_case(case, defeat_type, authority_type)
        if issues:
            logger.warning(f"Case {i+1} has issues: {issues}")

    logger.info(f"Generated {len(cases)} supplement cases for {defeat_type} x {authority_type}")
    return cases


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_backfill_plan() -> list[tuple[str, str, int, int, int]]:
    """
    Build a backfill plan by comparing 1_generated/ counts against 2_filtered/ counts.

    For each cell, target = generated count, existing = filtered count.
    Deficit = generated - filtered. Overshoot by per-cell fail rate.

    Returns list of (defeat_type, authority_type, filtered_count, generated_count, to_generate).
    """
    plan = []

    for gen_file in sorted(OUTPUT_DIR.glob("*.json")):
        stem = gen_file.stem
        parts = stem.split("_", 1)  # defeat_type may contain underscores
        # Parse stem: {defeat_type}_{authority_type}
        # Defeat types: control, content_defeat, application_defeat, exception_justified, illegitimate_authority
        for prefix in ["content_defeat", "application_defeat", "exception_justified",
                        "illegitimate_authority", "control"]:
            if stem.startswith(prefix + "_"):
                defeat_type = prefix
                authority_type = stem[len(prefix) + 1:]
                break
        else:
            logger.warning(f"Could not parse stem: {stem}")
            continue

        # Count generated cases
        with open(gen_file) as f:
            gen_data = json.load(f)
        gen_cases = gen_data.get("cases", gen_data) if isinstance(gen_data, dict) else gen_data
        generated_count = len(gen_cases) if isinstance(gen_cases, list) else 0

        # Count filtered cases
        filt_file = FILTERED_DIR / gen_file.name
        if filt_file.exists():
            with open(filt_file) as f:
                filt_data = json.load(f)
            filt_cases = filt_data.get("cases", [])
            filtered_count = len(filt_cases)
        else:
            filtered_count = generated_count  # No filtering done yet

        deficit = max(0, generated_count - filtered_count)
        if deficit == 0:
            plan.append((defeat_type, authority_type, filtered_count, generated_count, 0))
            continue

        # Overshoot: estimate per-cell fail rate from the data
        fail_rate = deficit / generated_count if generated_count > 0 else 0.25
        to_generate = ceil(deficit / (1 - fail_rate)) if fail_rate < 1.0 else deficit * 2

        plan.append((defeat_type, authority_type, filtered_count, generated_count, to_generate))

    return plan


def main():
    parser = argparse.ArgumentParser(description="Supplement case generation for v4")
    parser.add_argument("--defeat-type", type=str, help="Defeat type (e.g. control)")
    parser.add_argument("--authority-type", type=str, help="Authority type (e.g. workplace)")
    parser.add_argument("--all", action="store_true", help="Supplement all cells that need more cases")
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill mode: restore each cell to its pre-gating count by comparing "
                             "1_generated/ vs 2_filtered/. Overshoots based on per-cell fail rate.")
    parser.add_argument("--resume", action="store_true", help="Skip cells that already meet or exceed target")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without calling APIs")
    parser.add_argument("--model", type=str, default=None, help="Override model name")
    args = parser.parse_args()

    # Validate args
    if not args.all and not args.backfill and (not args.defeat_type or not args.authority_type):
        parser.error("One of --all, --backfill, or both --defeat-type and --authority-type required")

    # Ensure output dir exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build plan based on mode
    if args.backfill:
        # Backfill mode: compare 1_generated vs 2_filtered
        logger.info("Backfill mode: restoring cells to pre-gating counts")
        if not FILTERED_DIR.exists():
            logger.error("data/2_filtered/ not found. Run clean_pipeline.py first.")
            sys.exit(1)

        plan = build_backfill_plan()
        if args.resume:
            plan = [p for p in plan if p[4] > 0]

    else:
        # Original tier-target mode
        matrix = load_matrix()

        if args.all:
            cells = get_supplement_cells(matrix)
            logger.info(f"Found {len(cells)} non-implausible cells")
        else:
            cell_key = f"{args.defeat_type}:{args.authority_type}"
            tier_targets = {
                "tier_1": TIER_1_TARGET,
                "tier_2": TIER_2_TARGET,
                "tier_3": TIER_3_TARGET,
            }
            target = None
            for tier_name, tier_target in tier_targets.items():
                tier = matrix["cell_targets"].get(tier_name, {})
                if cell_key in tier.get("cells", []):
                    target = tier_target
                    break
            if target is None:
                logger.error(f"Cell {cell_key} not found in any tier (or implausible)")
                sys.exit(1)
            cells = [(args.defeat_type, args.authority_type, target)]

        plan = []
        for defeat_type, authority_type, target in cells:
            existing_data = load_existing(defeat_type, authority_type)
            existing_count = len(existing_data.get("cases", [])) if existing_data else 0
            delta = max(0, target - existing_count)
            if args.resume and delta == 0:
                continue
            plan.append((defeat_type, authority_type, existing_count, target, delta))

    # Print plan
    cells_needing_supplement = [p for p in plan if p[4] > 0]
    cells_already_met = [p for p in plan if p[4] == 0]
    total_delta = sum(p[4] for p in plan)

    logger.info(f"--- Supplement Plan ---")
    logger.info(f"Cells needing supplement: {len(cells_needing_supplement)}")
    logger.info(f"Cells already at target:  {len(cells_already_met)}")
    logger.info(f"Total new cases to generate: {total_delta}")
    logger.info(f"")

    if args.dry_run:
        for defeat, authority, existing, target, delta in plan:
            status = f"delta={delta}" if delta > 0 else "OK"
            logger.info(
                f"  {defeat:30s} x {authority:30s} | "
                f"existing={existing:3d}  target={target:3d}  {status}"
            )
        logger.info(f"")
        logger.info(f"DRY RUN complete. Would generate {total_delta} cases across {len(cells_needing_supplement)} cells.")
        return

    # Init client (only if not dry-run)
    client = OpenRouterClient(model_name=args.model)
    logger.info(f"Using model: {client.model_name}")

    # Generate supplements
    total_generated = 0
    total_supplemented = 0

    for defeat_type, authority_type, existing_count, target, delta in plan:
        if delta == 0:
            logger.info(f"Skipping {defeat_type} x {authority_type} (already at {existing_count}/{target})")
            continue

        existing_data = load_existing(defeat_type, authority_type)
        existing_cases = existing_data.get("cases", []) if existing_data else []
        max_index = get_max_case_index(existing_cases, defeat_type, authority_type)

        new_cases = generate_supplement(client, defeat_type, authority_type, delta)

        if new_cases:
            new_cases = assign_ids(new_cases, defeat_type, authority_type, max_index)
            save_merged(existing_data, new_cases, defeat_type, authority_type, client.model_name)
            total_generated += len(new_cases)
            total_supplemented += 1

    # Summary
    grand_total = 0
    for defeat_type, authority_type, _, _, _ in plan:
        existing_data = load_existing(defeat_type, authority_type)
        if existing_data:
            grand_total += len(existing_data.get("cases", []))

    logger.info(f"")
    logger.info(f"=== Supplement Complete ===")
    logger.info(f"New cases generated:   {total_generated}")
    logger.info(f"Cells supplemented:    {total_supplemented}")
    logger.info(f"New grand total:       {grand_total}")


if __name__ == "__main__":
    main()
