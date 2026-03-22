#!/usr/bin/env python3
"""
Clean the pipeline by removing cases that failed blocking gates (OV, RJ) from all downstream data.

Creates data/2_filtered/ with only passing cases (non-destructive: 1_generated/ stays intact).
Removes failed-case responses from data/3_responses/.
Produces a per-cell deficit report for backfill generation.

Usage:
    python3 scripts/clean_pipeline.py                    # Full clean + report
    python3 scripts/clean_pipeline.py --dry-run          # Preview without writing
    python3 scripts/clean_pipeline.py --report-only      # Just the deficit report
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
FILTERED_DIR = DATA_DIR / "2_filtered"
GATED_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"
RESPONSES_DIR = DATA_DIR / "3_responses"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ===================================================================
# Phase 1: Load blocking gate results and build fail set
# ===================================================================

def load_gate_results(filename: str, gate_label: str) -> dict[str, dict]:
    """Load gate results from a full_results.json file. Returns dict keyed by case_id."""
    path = GATED_DIR / filename
    if not path.exists():
        logger.warning(f"{gate_label} results not found: {path}")
        return {}

    with open(path) as f:
        return json.load(f)


def build_fail_set_from_gate(results: dict[str, dict]) -> set[str]:
    """Build set of case IDs that failed a single gate."""
    failed = set()
    for case_id, result in results.items():
        if result.get("error"):
            failed.add(case_id)  # Errors are treated as fails (conservative)
        elif not result.get("pass", False):
            failed.add(case_id)
    return failed


def load_all_blocking_gates() -> tuple[dict[str, dict], dict[str, dict], set[str], set[str]]:
    """
    Load OV and RJ gate results. Returns (ov_results, rj_results, ov_fails, rj_fails).
    OV is required; RJ is optional (warns if missing).
    """
    ov_results = load_gate_results("ov_full_results.json", "OV")
    if not ov_results:
        logger.error("OV results are required. Run run_ov_full.py first.")
        sys.exit(1)

    rj_results = load_gate_results("rj_full_results.json", "RJ")
    if not rj_results:
        logger.warning("RJ results not found — filtering by OV only.")

    ov_fails = build_fail_set_from_gate(ov_results)
    rj_fails = build_fail_set_from_gate(rj_results) if rj_results else set()

    return ov_results, rj_results, ov_fails, rj_fails


# ===================================================================
# Phase 2: Create filtered dataset
# ===================================================================

def create_filtered_dataset(
    failed_ids: set[str],
    ov_fails: set[str],
    rj_fails: set[str],
    dry_run: bool = False,
) -> dict[str, dict]:
    """
    Create data/2_filtered/ with only passing cases.

    Returns per-cell stats: {stem: {before, after, removed, ov_removed, rj_removed}}.
    """
    if not dry_run:
        FILTERED_DIR.mkdir(parents=True, exist_ok=True)

    cell_stats: dict[str, dict] = {}

    for gen_file in sorted(GENERATED_DIR.glob("*.json")):
        stem = gen_file.stem

        with open(gen_file) as f:
            data = json.load(f)

        if isinstance(data, dict) and "cases" in data:
            cases = data["cases"]
            metadata = data.get("metadata", {})
        elif isinstance(data, list):
            cases = data
            metadata = {}
        else:
            cases = [data]
            metadata = {}

        before_count = len(cases)
        passing = [c for c in cases if c.get("id") not in failed_ids]
        removed = before_count - len(passing)

        # Count per-gate removals
        case_ids = {c.get("id") for c in cases}
        ov_removed = len(case_ids & ov_fails)
        rj_removed = len(case_ids & rj_fails)
        # Some cases may fail both gates — total removed <= ov + rj
        both_removed = len(case_ids & ov_fails & rj_fails)

        cell_stats[stem] = {
            "before": before_count,
            "after": len(passing),
            "removed": removed,
            "ov_removed": ov_removed,
            "rj_removed": rj_removed,
            "both_removed": both_removed,
        }

        if not dry_run:
            filtered_data = {
                "metadata": {
                    **metadata,
                    "actual_count": len(passing),
                    "filtered_from": before_count,
                    "ov_removed": ov_removed,
                    "rj_removed": rj_removed,
                    "total_removed": removed,
                },
                "cases": passing,
            }
            out_path = FILTERED_DIR / gen_file.name
            with open(out_path, "w") as f:
                json.dump(filtered_data, f, indent=2)

        if removed > 0:
            detail = f"OV:{ov_removed} RJ:{rj_removed}"
            if both_removed:
                detail += f" both:{both_removed}"
            logger.info(f"  {stem}: {before_count} -> {len(passing)} ({removed} removed — {detail})")

    return cell_stats


# ===================================================================
# Phase 3: Clean responses
# ===================================================================

def clean_responses(
    failed_ids: set[str], dry_run: bool = False,
) -> dict[str, dict]:
    """
    Remove responses for failed cases from data/3_responses/.

    Returns per-file stats: {filename: {before, after, removed}}.
    """
    if not RESPONSES_DIR.exists():
        logger.warning("No responses directory found — skipping response cleanup")
        return {}

    response_stats: dict[str, dict] = {}

    for resp_file in sorted(RESPONSES_DIR.glob("*.json")):
        with open(resp_file) as f:
            data = json.load(f)

        responses = data.get("responses", [])
        metadata = data.get("metadata", {})

        before_count = len(responses)
        passing = [r for r in responses if r.get("case_id") not in failed_ids]
        removed = before_count - len(passing)

        response_stats[resp_file.name] = {
            "before": before_count,
            "after": len(passing),
            "removed": removed,
        }

        if removed > 0 and not dry_run:
            # Update metadata counts
            successful = sum(1 for r in passing if r.get("status") == "success")
            errors = sum(1 for r in passing if r.get("status") == "error")

            data["responses"] = passing
            data["metadata"]["total_responses"] = len(passing)
            data["metadata"]["successful"] = successful
            data["metadata"]["errors"] = errors

            with open(resp_file, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"  {resp_file.name}: {before_count} -> {len(passing)} ({removed} removed)")

    return response_stats


# ===================================================================
# Phase 4: Verification
# ===================================================================

def verify_clean(failed_ids: set[str]) -> bool:
    """
    Verify that NO failed case ID appears in any filtered or response file.
    Returns True if clean, False if contamination found.
    """
    clean = True

    # Check 2_filtered/
    if FILTERED_DIR.exists():
        for filt_file in FILTERED_DIR.glob("*.json"):
            with open(filt_file) as f:
                data = json.load(f)
            cases = data.get("cases", data) if isinstance(data, dict) else data
            if isinstance(cases, list):
                for case in cases:
                    cid = case.get("id", "")
                    if cid in failed_ids:
                        logger.error(f"CONTAMINATION: {cid} found in 2_filtered/{filt_file.name}")
                        clean = False

    # Check 3_responses/
    if RESPONSES_DIR.exists():
        for resp_file in RESPONSES_DIR.glob("*.json"):
            with open(resp_file) as f:
                data = json.load(f)
            for resp in data.get("responses", []):
                cid = resp.get("case_id", "")
                if cid in failed_ids:
                    logger.error(f"CONTAMINATION: {cid} found in 3_responses/{resp_file.name}")
                    clean = False

    return clean


# ===================================================================
# Phase 5: Deficit report
# ===================================================================

def load_matrix_tiers() -> dict[str, int]:
    """Load tier assignments from matrix.json. Returns {stem: tier_target}."""
    matrix_path = DATA_DIR / "0_inputs" / "matrix.json"
    if not matrix_path.exists():
        logger.warning("matrix.json not found — using default targets")
        return {}

    with open(matrix_path) as f:
        matrix = json.load(f)

    # Supplement targets by tier
    tier_targets = {1: 20, 2: 10, 3: 5}

    tiers = {}
    for cell in matrix.get("cells", []):
        defeat = cell.get("defeat_type", "")
        authority = cell.get("authority_type", "")
        tier = cell.get("tier", 3)
        stem = f"{defeat}_{authority}"
        tiers[stem] = tier_targets.get(tier, 5)

    return tiers


def generate_deficit_report(
    cell_stats: dict[str, dict],
    ov_results: dict[str, dict],
    target_total: int = 850,
) -> str:
    """
    Generate a per-cell deficit report with generation targets.

    Overshoots to target_total (default 850) to account for gate losses on new cases.
    """
    tier_targets = load_matrix_tiers()

    # Calculate per-cell fail rates from OV results
    cell_fail_counts: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for case_id, result in ov_results.items():
        # Extract stem from case_id: seed_{defeat}_{authority}_{N}
        parts = case_id.split("_")
        if parts[0] == "seed":
            parts = parts[1:]
        # Find the N at the end
        n_str = parts[-1]
        stem = "_".join(parts[:-1])

        if result.get("pass"):
            cell_fail_counts[stem]["pass"] += 1
        else:
            cell_fail_counts[stem]["fail"] += 1

    # Global fail rate as fallback
    total_pass = sum(v["pass"] for v in cell_fail_counts.values())
    total_fail = sum(v["fail"] for v in cell_fail_counts.values())
    global_fail_rate = total_fail / (total_pass + total_fail) if (total_pass + total_fail) > 0 else 0.25

    total_current_passing = sum(s["after"] for s in cell_stats.values())
    total_deficit = target_total - total_current_passing

    lines = []
    lines.append(f"{'=' * 90}")
    lines.append(f"PER-CELL DEFICIT REPORT")
    lines.append(f"{'=' * 90}")
    lines.append(f"")
    lines.append(f"Current passing cases: {total_current_passing}")
    lines.append(f"Target (with overshoot): {target_total}")
    lines.append(f"Global deficit: {total_deficit}")
    lines.append(f"Global OV fail rate: {global_fail_rate:.1%}")
    lines.append(f"")
    lines.append(f"{'Cell':<55s} | {'Had':>4s} | {'Pass':>4s} | {'Lost':>4s} | {'Tgt':>4s} | {'Need':>4s} | {'Gen':>4s}")
    lines.append(f"{'-' * 55}-+------+------+------+------+------+------")

    cells_needing_gen = []
    total_to_generate = 0

    for stem in sorted(cell_stats.keys()):
        stats = cell_stats[stem]
        had = stats["before"]
        passing = stats["after"]
        lost = stats["removed"]

        # Cell target: at least the tier target
        tier_target = tier_targets.get(stem, 5)
        cell_target = max(tier_target, had)  # Don't go below what we had

        deficit = max(0, cell_target - passing)

        # Cell-specific fail rate (use global if <5 cases)
        cell_fc = cell_fail_counts.get(stem, {"pass": 0, "fail": 0})
        cell_total = cell_fc["pass"] + cell_fc["fail"]
        if cell_total >= 5:
            cell_fr = cell_fc["fail"] / cell_total
        else:
            cell_fr = global_fail_rate

        # Overshoot: generate enough that after gating we still hit target
        if deficit > 0 and cell_fr < 1.0:
            to_gen = ceil(deficit / (1 - cell_fr))
        elif deficit > 0:
            to_gen = deficit * 2  # If 100% fail rate, double it and hope
        else:
            to_gen = 0

        total_to_generate += to_gen

        flag = " ***" if deficit > 0 else ""
        lines.append(
            f"  {stem:<53s} | {had:>4d} | {passing:>4d} | {lost:>4d} | {cell_target:>4d} | {deficit:>4d} | {to_gen:>4d}{flag}"
        )

        if to_gen > 0:
            cells_needing_gen.append((stem, to_gen, deficit, cell_fr))

    lines.append(f"")
    lines.append(f"{'=' * 90}")
    lines.append(f"SUMMARY")
    lines.append(f"{'=' * 90}")
    lines.append(f"  Cells needing generation: {len(cells_needing_gen)}")
    lines.append(f"  Total cases to generate:  {total_to_generate}")
    lines.append(f"  Expected to pass gate:    ~{total_to_generate - int(total_to_generate * global_fail_rate)}")
    lines.append(f"  Projected final total:    ~{total_current_passing + total_to_generate - int(total_to_generate * global_fail_rate)}")
    lines.append(f"")

    if cells_needing_gen:
        lines.append(f"  Cells requiring backfill (sorted by deficit):")
        for stem, to_gen, deficit, fr in sorted(cells_needing_gen, key=lambda x: -x[2]):
            lines.append(f"    {stem}: generate {to_gen} (deficit {deficit}, cell fail rate {fr:.0%})")

    lines.append(f"{'=' * 90}")

    return "\n".join(lines)


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Clean pipeline of gate-failed cases (OV + RJ)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--report-only", action="store_true", help="Just print deficit report")
    parser.add_argument("--target", type=int, default=850, help="Target total passing cases (default 850, overshoots 800)")
    args = parser.parse_args()

    # Load blocking gate results (OV required, RJ optional)
    logger.info("Loading blocking gate results...")
    ov_results, rj_results, ov_fails, rj_fails = load_all_blocking_gates()

    # Combined fail set: union of OV and RJ failures
    failed_ids = ov_fails | rj_fails
    both_failed = ov_fails & rj_fails

    logger.info(f"OV: {len(ov_results)} cases, {len(ov_fails)} failed")
    if rj_results:
        logger.info(f"RJ: {len(rj_results)} cases, {len(rj_fails)} failed")
        logger.info(f"Both: {len(both_failed)} failed both gates")
    logger.info(f"Combined: {len(failed_ids)} unique failures")

    if args.report_only:
        cell_stats = {}
        for gen_file in sorted(GENERATED_DIR.glob("*.json")):
            stem = gen_file.stem
            with open(gen_file) as f:
                data = json.load(f)
            cases = data.get("cases", data) if isinstance(data, dict) else data
            if isinstance(cases, list):
                before = len(cases)
                after = sum(1 for c in cases if c.get("id") not in failed_ids)
                cell_stats[stem] = {"before": before, "after": after, "removed": before - after}

        report = generate_deficit_report(cell_stats, ov_results, target_total=args.target)
        print(report)
        return

    # Phase 2: Create filtered dataset
    logger.info(f"\n{'=' * 60}")
    logger.info("Phase 2: Creating filtered dataset (data/2_filtered/)")
    logger.info(f"{'=' * 60}")
    cell_stats = create_filtered_dataset(failed_ids, ov_fails, rj_fails, dry_run=args.dry_run)

    total_before = sum(s["before"] for s in cell_stats.values())
    total_after = sum(s["after"] for s in cell_stats.values())
    total_removed = sum(s["removed"] for s in cell_stats.values())
    total_ov = sum(s.get("ov_removed", 0) for s in cell_stats.values())
    total_rj = sum(s.get("rj_removed", 0) for s in cell_stats.values())
    logger.info(f"Filtered: {total_before} -> {total_after} ({total_removed} removed — OV:{total_ov} RJ:{total_rj})")

    # Phase 3: Clean responses
    logger.info(f"\n{'=' * 60}")
    logger.info("Phase 3: Cleaning responses (data/3_responses/)")
    logger.info(f"{'=' * 60}")
    response_stats = clean_responses(failed_ids, dry_run=args.dry_run)

    resp_removed = sum(s["removed"] for s in response_stats.values())
    logger.info(f"Responses cleaned: {resp_removed} response entries removed")

    # Phase 4: Verification
    if not args.dry_run:
        logger.info(f"\n{'=' * 60}")
        logger.info("Phase 4: Verification")
        logger.info(f"{'=' * 60}")

        # Verify counts: total_after should equal total_before minus unique failures
        expected_after = total_before - len(failed_ids)
        assert total_after == expected_after, (
            f"MISMATCH: filtered cases ({total_after}) != expected ({expected_after})"
        )
        logger.info(f"  [OK] Filtered case count ({total_after}) matches expected ({expected_after})")

        # Verify no contamination
        is_clean = verify_clean(failed_ids)
        if is_clean:
            logger.info("  [OK] No failed case IDs found in filtered or response files")
        else:
            logger.error("  [FAIL] Contamination detected! See errors above.")
            sys.exit(1)

        # Verify 1_generated/ is untouched
        gen_count = 0
        for gen_file in GENERATED_DIR.glob("*.json"):
            with open(gen_file) as f:
                data = json.load(f)
            cases = data.get("cases", data) if isinstance(data, dict) else data
            if isinstance(cases, list):
                gen_count += len(cases)
        assert gen_count == total_before, (
            f"MISMATCH: 1_generated/ has {gen_count} cases but expected {total_before}"
        )
        logger.info(f"  [OK] 1_generated/ unchanged ({gen_count} cases)")

        # Verify response metadata counts
        for resp_file in RESPONSES_DIR.glob("*.json"):
            with open(resp_file) as f:
                data = json.load(f)
            actual = len(data.get("responses", []))
            reported = data.get("metadata", {}).get("total_responses", -1)
            if actual != reported:
                logger.error(f"  [FAIL] {resp_file.name}: actual={actual}, metadata says={reported}")
                sys.exit(1)
        logger.info(f"  [OK] All response file metadata counts are accurate")

    # Phase 5: Deficit report
    logger.info(f"\n")
    report = generate_deficit_report(cell_stats, ov_results, target_total=args.target)
    print(report)

    # Save report
    if not args.dry_run:
        report_path = PROJECT_ROOT / "validation" / "deficit_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            f.write(report)
        logger.info(f"Deficit report saved to {report_path}")

    logger.info("\nDone. Next steps:")
    logger.info("  1. Review deficit report")
    logger.info("  2. Run supplement.py to backfill cells")
    logger.info("  3. Gate new cases with run_ov_full.py --resume")
    logger.info("  4. Re-run clean_pipeline.py to update 2_filtered/")
    logger.info("  5. Collect responses: collect.py --all-files --new-only")


if __name__ == "__main__":
    main()
