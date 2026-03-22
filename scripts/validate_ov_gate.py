#!/usr/bin/env python3
"""
Validate the operational_validity gate against human review verdicts.

Loads the 100 reviewed cases, runs the OV gate on each, and compares
gate results to Cameron's verdicts (PI tiebreaker).

The reviews.json file is READ ONLY — this script never modifies it.

Uses the Claude Code CLI (`claude -p`) for gate execution — no API key needed.

Usage:
    python3 scripts/validate_ov_gate.py
    python3 scripts/validate_ov_gate.py --model sonnet
    python3 scripts/validate_ov_gate.py --dry-run   # show ground truth without running gate
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
VALIDATION_DIR = PROJECT_ROOT / "validation"
GENERATED_DIR = PROJECT_ROOT / "data" / "1_generated"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
GATES_DIR = PROMPTS_DIR / "gates"
DEFEATS_DIR = PROMPTS_DIR / "defeats"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_reviews() -> dict:
    """Load human review verdicts (READ ONLY)."""
    reviews_path = VALIDATION_DIR / "reviews.json"
    with open(reviews_path) as f:
        return json.load(f)


def get_ground_truth(reviews: dict) -> dict[str, bool]:
    """Derive ground truth from Cameron's verdicts (PI tiebreaker).

    Returns dict mapping case_id -> should_pass (True = pass, False = fail).
    """
    truth = {}
    for case_id, review in reviews.items():
        cameron_verdict = review.get("cameron", "").lower()
        # Cameron's verdict is authoritative
        truth[case_id] = cameron_verdict == "pass"
    return truth


def find_case_in_generated(case_id: str) -> dict | None:
    """Find a case by ID across all generated files."""
    # Parse case_id to determine likely filename
    # Format: seed_{defeat_type}_{authority_type}_{N}
    # Filename: {defeat_type}_{authority_type}.json
    parts = case_id.split("_")
    if parts[0] == "seed":
        parts = parts[1:]  # strip "seed_"

    # Try to reconstruct the filename by finding the right split point
    # The defeat_type and authority_type are separated, but both can have underscores
    # Strategy: try all generated files and search for the case_id
    for json_file in GENERATED_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            cases = data.get("cases", data) if isinstance(data, dict) else data
            if isinstance(cases, list):
                for case in cases:
                    if case.get("id") == case_id:
                        return case
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def load_defeat_definitions() -> dict[str, str]:
    """Load all defeat type definition files."""
    defs = {}
    for f in DEFEATS_DIR.glob("*.md"):
        defs[f.stem] = f.read_text()
    return defs


def load_gate_prompt() -> str:
    """Load the operational_validity gate prompt."""
    path = GATES_DIR / "operational_validity.md"
    return path.read_text()


def build_prompt(gate_template: str, case: dict, defeat_defs: dict) -> str:
    """Build the gate prompt for a single case."""
    prompt = gate_template
    prompt = prompt.replace("{{CASE_JSON}}", json.dumps(case, indent=2))
    defeat_type = case.get("defeat_type", "")
    defeat_def = defeat_defs.get(defeat_type, "No definition available.")
    prompt = prompt.replace("{{DEFEAT_SUBTYPE_DEFINITION}}", defeat_def)
    return prompt


def extract_json_object(text: str) -> dict | None:
    """Extract a JSON object from response text."""
    import re
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None


def run_gate_on_case_cli(
    gate_template: str, case: dict, defeat_defs: dict,
    model: str | None = None, retries: int = 3,
) -> dict | None:
    """Run the OV gate on a single case using claude -p CLI."""
    prompt = build_prompt(gate_template, case, defeat_defs)
    system_prompt = (
        "You are a quality gate for a research dataset. "
        "Return only valid JSON — a single JSON object. "
        "No commentary, no markdown fences, no text before or after the JSON."
    )

    cmd = [
        "claude", "-p",
        "--system-prompt", system_prompt,
        "--tools", "",  # no tools — pure generation
        "--output-format", "text",
        "--no-session-persistence",
    ]
    if model:
        cmd.extend(["--model", model])

    last_error = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning(f"Attempt {attempt + 1}: claude returned code {result.returncode}: {result.stderr[:200]}")
                last_error = result.stderr
                time.sleep(2 ** attempt)
                continue

            response = result.stdout
            if not response.strip():
                logger.warning(f"Attempt {attempt + 1}: empty response")
                time.sleep(2 ** attempt)
                continue

            parsed = extract_json_object(response)
            if parsed is None:
                logger.warning(f"Attempt {attempt + 1}: failed to parse JSON from response")
                logger.debug(f"Raw: {response[:300]}")
                time.sleep(2 ** attempt)
                continue

            if "case_id" not in parsed:
                parsed["case_id"] = case.get("id", "unknown")
            return parsed

        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt + 1}: timed out after 120s")
            last_error = "timeout"
            time.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: {e}")
            last_error = str(e)
            time.sleep(2 ** attempt)

    logger.error(f"All {retries} attempts failed. Last error: {last_error}")
    return None


def print_metrics(
    ground_truth: dict[str, bool],
    gate_results: dict[str, bool],
    gate_details: dict[str, dict],
    reviews: dict,
):
    """Print validation metrics comparing gate results to ground truth."""
    # Align on common case IDs
    common = set(ground_truth.keys()) & set(gate_results.keys())

    tp = fp = tn = fn = 0
    false_positives = []
    false_negatives = []
    true_positives = []

    for cid in sorted(common):
        should_fail = not ground_truth[cid]  # ground truth: True=pass, so NOT pass = should_fail
        gate_failed = not gate_results[cid]   # gate: True=pass, so NOT pass = gate_failed

        if should_fail and gate_failed:
            tp += 1
            true_positives.append(cid)
        elif should_fail and not gate_failed:
            fn += 1
            false_negatives.append(cid)
        elif not should_fail and gate_failed:
            fp += 1
            false_positives.append(cid)
        else:
            tn += 1

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (tp + tn) / total if total > 0 else 0

    print("\n" + "=" * 60)
    print("OPERATIONAL VALIDITY GATE — VALIDATION RESULTS")
    print("=" * 60)
    skipped = len(ground_truth) - len(common)
    print(f"\nCases evaluated: {total}" + (f" ({skipped} skipped due to errors)" if skipped else ""))
    print(f"Ground truth fails: {tp + fn} | Ground truth passes: {tn + fp}")
    print(f"\nConfusion Matrix (detecting FAILS):")
    print(f"  True Positives  (correctly failed):  {tp}")
    print(f"  True Negatives  (correctly passed):  {tn}")
    print(f"  False Positives (wrongly failed):    {fp}")
    print(f"  False Negatives (missed fails):      {fn}")
    print(f"\nMetrics:")
    print(f"  Precision: {precision:.1%}  (of cases gate failed, how many should have failed)")
    print(f"  Recall:    {recall:.1%}  (of cases that should fail, how many did gate catch)")
    print(f"  F1:        {f1:.1%}")
    print(f"  Accuracy:  {accuracy:.1%}")

    if false_negatives:
        print(f"\n{'─' * 60}")
        print(f"MISSED FAILS ({len(false_negatives)} cases the gate should have failed but passed):")
        for cid in false_negatives:
            cam_note = reviews.get(cid, {}).get("cameron_note", "")
            detail = gate_details.get(cid, {})
            checks = detail.get("checks", {})
            print(f"\n  {cid}")
            print(f"    Cameron's note: {cam_note[:120]}")
            for check_name, check_data in checks.items():
                if isinstance(check_data, dict):
                    status = "PASS" if check_data.get("pass") else "FAIL"
                    print(f"    {check_name}: {status} — {check_data.get('reasoning', '')[:100]}")

    if false_positives:
        print(f"\n{'─' * 60}")
        print(f"FALSE FAILURES ({len(false_positives)} cases the gate wrongly failed):")
        for cid in false_positives:
            cam_note = reviews.get(cid, {}).get("cameron_note", "")
            detail = gate_details.get(cid, {})
            checks = detail.get("checks", {})
            print(f"\n  {cid}")
            print(f"    Cameron's note: {cam_note[:120]}")
            for check_name, check_data in checks.items():
                if isinstance(check_data, dict) and not check_data.get("pass"):
                    print(f"    FAILED: {check_name} — {check_data.get('reasoning', '')[:100]}")

    if true_positives:
        print(f"\n{'─' * 60}")
        print(f"CORRECTLY CAUGHT ({len(true_positives)} cases):")
        for cid in true_positives:
            detail = gate_details.get(cid, {})
            checks = detail.get("checks", {})
            failed_checks = [k for k, v in checks.items() if isinstance(v, dict) and not v.get("pass")]
            print(f"  {cid} — failed: {', '.join(failed_checks)}")

    print(f"\n{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="Validate OV gate against human reviews")
    parser.add_argument("--model", type=str, default=None,
                        help="Claude model alias (e.g. 'sonnet', 'opus', 'haiku')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show ground truth without running the gate")
    parser.add_argument("--output", type=str, default=None,
                        help="Save gate results to this JSON file")
    args = parser.parse_args()

    # Load reviews and derive ground truth
    reviews = load_reviews()
    ground_truth = get_ground_truth(reviews)

    should_fail = [cid for cid, passes in ground_truth.items() if not passes]
    should_pass = [cid for cid, passes in ground_truth.items() if passes]
    logger.info(f"Ground truth: {len(should_fail)} fails, {len(should_pass)} passes out of {len(ground_truth)} cases")

    if args.dry_run:
        print("\n--- GROUND TRUTH (Cameron's verdicts) ---")
        print(f"\nShould FAIL ({len(should_fail)}):")
        for cid in sorted(should_fail):
            note = reviews[cid].get("cameron_note", "")
            print(f"  {cid}: {note[:100]}")
        print(f"\nShould PASS ({len(should_pass)}):")
        for cid in sorted(should_pass):
            note = reviews[cid].get("cameron_note", "")
            if note:
                print(f"  {cid}: {note[:80]}")
            else:
                print(f"  {cid}")
        return

    # Find all reviewed cases in generated data
    logger.info("Locating reviewed cases in generated data...")
    cases = {}
    missing = []
    for case_id in ground_truth:
        case = find_case_in_generated(case_id)
        if case:
            cases[case_id] = case
        else:
            missing.append(case_id)
            logger.warning(f"Case not found in generated data: {case_id}")

    if missing:
        logger.warning(f"{len(missing)} cases not found — they will be skipped")

    logger.info(f"Found {len(cases)} of {len(ground_truth)} cases")

    # Load resources
    defeat_defs = load_defeat_definitions()
    gate_template = load_gate_prompt()

    model_label = args.model or "default"
    logger.info(f"Using claude -p (model: {model_label})")
    logger.info(f"Running OV gate on {len(cases)} cases...")

    # Run gate on each case
    gate_results = {}
    gate_details = {}
    errors = 0

    for i, (case_id, case) in enumerate(sorted(cases.items())):
        logger.info(f"  [{i+1}/{len(cases)}] {case_id}")
        result = run_gate_on_case_cli(gate_template, case, defeat_defs, model=args.model)

        if result:
            gate_results[case_id] = result.get("pass", True)
            gate_details[case_id] = result
        else:
            logger.error(f"  Gate execution failed for {case_id}")
            errors += 1
            # Exclude errored cases from metrics — don't count them as pass or fail
            gate_details[case_id] = {"error": True, "case_id": case_id}

    if errors:
        logger.warning(f"{errors} cases had gate execution errors")

    # Save raw results if requested
    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w") as f:
            json.dump(gate_details, f, indent=2)
        logger.info(f"Saved raw gate results to {out_path}")
    else:
        # Default output location
        out_path = VALIDATION_DIR / "ov_gate_results.json"
        with open(out_path, "w") as f:
            json.dump(gate_details, f, indent=2)
        logger.info(f"Saved raw gate results to {out_path}")

    # Print metrics
    print_metrics(ground_truth, gate_results, gate_details, reviews)


if __name__ == "__main__":
    main()
