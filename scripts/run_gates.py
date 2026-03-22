#!/usr/bin/env python3
"""
v4 gate runner — runs quality gates on generated cases using Gemini via OpenRouter.

Usage:
    python3 scripts/run_gates.py --gate operational_validity --input data/1_generated/control_workplace.json
    python3 scripts/run_gates.py --all-gates --input data/1_generated/control_workplace.json
    python3 scripts/run_gates.py --gate operational_validity --all-files
    python3 scripts/run_gates.py --all-gates --all-files
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
GATES_DIR = PROMPTS_DIR / "gates"
DEFEATS_DIR = PROMPTS_DIR / "defeats"
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = DATA_DIR / "1_generated"
GATED_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"

sys.path.insert(0, str(SCRIPT_DIR))
from openrouter_client import OpenRouterClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Gate name → filename prefix (used in output and in serve_review.py)
GATE_MAP = {
    "dual_use": "du",
    "operational_validity": "ov",
    "reasonable_judge": "rj",
}

# Flag gates: non-blocking. They add metadata flags but don't disqualify cases.
# Blocking gates cause case rejection on failure; flag gates just annotate.
FLAG_GATES = {"dual_use"}

# Retired/archived gates (kept for reference, not run):
# - structural_verification (sv): Removed — vestigial; never filtered anything.
# - naturalistic_ask (na): Removed — "Walk me through" false positives and
#   questionable construct validity for generated stimuli.
# - decision_forcing (df): Archived — redundant with operational validity gate.

# Gates that need the defeat subtype definition injected
GATES_NEEDING_DEFEAT_DEF = {"operational_validity"}


def load_gate_prompt(gate_name: str) -> str:
    """Load a gate prompt template."""
    path = GATES_DIR / f"{gate_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Gate prompt not found: {path}")
    return path.read_text()


def load_defeat_definitions() -> dict[str, str]:
    """Load all defeat type definition files, keyed by defeat_type name."""
    defs = {}
    for f in DEFEATS_DIR.glob("*.md"):
        defs[f.stem] = f.read_text()
    return defs


def load_cases_from_file(filepath: Path) -> list[dict]:
    """Load cases from a generated file (handles both flat arrays and {metadata, cases} format)."""
    with open(filepath) as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    return [data]


def find_all_generated_files() -> list[Path]:
    """Find all generated case files."""
    return sorted(GENERATED_DIR.glob("*.json"))


def extract_json_object(text: str) -> dict | None:
    """Extract a JSON object from response text."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find object in text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None


def build_gate_prompt(
    gate_template: str,
    case: dict,
    defeat_definitions: dict[str, str],
    gate_name: str,
) -> str:
    """Build a gate prompt for a single case."""
    prompt = gate_template

    # Inject case JSON
    case_json = json.dumps(case, indent=2)
    prompt = prompt.replace("{{CASE_JSON}}", case_json)

    # Inject defeat subtype definition if needed
    if gate_name in GATES_NEEDING_DEFEAT_DEF:
        defeat_type = case.get("defeat_type", "")
        defeat_def = defeat_definitions.get(defeat_type, "No definition available.")
        prompt = prompt.replace("{{DEFEAT_SUBTYPE_DEFINITION}}", defeat_def)

    return prompt


def run_gate_on_case(
    client: OpenRouterClient,
    gate_name: str,
    gate_template: str,
    case: dict,
    defeat_definitions: dict[str, str],
) -> dict | None:
    """Run a single gate on a single case."""
    prompt = build_gate_prompt(gate_template, case, defeat_definitions, gate_name)

    system_prompt = (
        "You are a quality gate for a research dataset. "
        "Return only valid JSON — a single JSON object. "
        "No commentary, no markdown fences, no text before or after the JSON."
    )

    response = client.generate_with_retry(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.0,  # Deterministic gating
        max_tokens=4000,
        json_mode=False,  # Gemini truncates with json_mode; we strip fences instead
    )

    if not response:
        logger.error(f"No response for gate {gate_name} on case {case.get('id', '?')}")
        return None

    result = extract_json_object(response)
    if result is None:
        logger.error(f"Failed to parse gate result for {case.get('id', '?')}")
        logger.debug(f"Raw response: {response[:500]}")
        return None

    # Ensure case_id is present
    if "case_id" not in result:
        result["case_id"] = case.get("id", "unknown")

    return result


def load_existing_results(gate_name: str, source_file: Path) -> dict[str, dict]:
    """Load existing gate results for a file, keyed by case_id."""
    prefix = GATE_MAP.get(gate_name, gate_name[:2])
    stem = source_file.stem
    out_path = GATED_DIR / f"{prefix}_{stem}.json"
    if not out_path.exists():
        return {}
    try:
        with open(out_path) as f:
            data = json.load(f)
        return {r.get("case_id", ""): r for r in data if isinstance(r, dict)}
    except (json.JSONDecodeError, KeyError):
        return {}


def run_gate_on_file(
    client: OpenRouterClient,
    gate_name: str,
    input_file: Path,
    defeat_definitions: dict[str, str],
    errors_only: bool = False,
) -> list[dict]:
    """Run a gate on all cases in a file.

    If errors_only=True, only re-run cases that previously had errors,
    keeping existing successful results.
    """
    cases = load_cases_from_file(input_file)
    gate_template = load_gate_prompt(gate_name)

    existing = load_existing_results(gate_name, input_file) if errors_only else {}
    skip_count = 0

    logger.info(f"Running {gate_name} on {len(cases)} cases from {input_file.name}"
                + (f" (errors-only mode, {len(existing)} existing)" if errors_only else ""))

    results = []
    for i, case in enumerate(cases):
        case_id = case.get("id", f"unknown_{i}")

        # In errors-only mode, skip cases that already have non-error results
        if errors_only and case_id in existing and not existing[case_id].get("error"):
            results.append(existing[case_id])
            skip_count += 1
            continue

        logger.info(f"  [{i+1}/{len(cases)}] {case_id}")

        result = run_gate_on_case(client, gate_name, gate_template, case, defeat_definitions)
        if result:
            results.append(result)
        else:
            # Record failure
            results.append({
                "gate": gate_name,
                "case_id": case_id,
                "pass": False,
                "reasoning": "Gate execution failed — no valid response from API.",
                "error": True,
            })

    if skip_count:
        logger.info(f"  Skipped {skip_count} cases with existing results")

    return results


def save_gate_results(results: list[dict], gate_name: str, source_file: Path):
    """Save gate results to the gated directory."""
    GATED_DIR.mkdir(parents=True, exist_ok=True)

    prefix = GATE_MAP.get(gate_name, gate_name[:2])
    # Derive output name from source file: ov_control_workplace.json
    stem = source_file.stem  # e.g. "control_workplace"
    out_path = GATED_DIR / f"{prefix}_{stem}.json"

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved {len(results)} gate results to {out_path}")


def print_summary(results: list[dict], gate_name: str):
    """Print pass/fail summary, distinguishing flag gates from blocking gates."""
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    failed = total - passed
    errors = sum(1 for r in results if r.get("error"))
    is_flag = gate_name in FLAG_GATES

    gate_type = "FLAG" if is_flag else "BLOCKING"
    print(f"\n{'='*50}")
    print(f"Gate: {gate_name} [{gate_type}]")
    print(f"Total: {total} | Pass: {passed} | Fail: {failed} | Errors: {errors}")
    print(f"Pass rate: {passed/total*100:.0f}%" if total else "No cases")
    if is_flag and failed:
        print(f"  ({failed} cases flagged — not disqualified)")
    print(f"{'='*50}")

    # Show failing/flagged cases
    label = "FLAGGED" if is_flag else "FAIL"
    for r in results:
        if not r.get("pass"):
            print(f"  {label}: {r.get('case_id', '?')}")
            reasoning = r.get("reasoning") or r.get("overall_reasoning", "")
            if reasoning:
                print(f"        {reasoning[:120]}")
            # For dual_use, also show category
            if gate_name == "dual_use" and r.get("category"):
                print(f"        category: {r['category']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="v4 gate runner")
    parser.add_argument("--gate", type=str, help="Gate name (e.g. operational_validity)")
    parser.add_argument("--all-gates", action="store_true", help="Run all gates")
    parser.add_argument("--blocking-only", action="store_true", help="Run only blocking gates (OV, RJ)")
    parser.add_argument("--flag-only", action="store_true", help="Run only flag gates (DF, DU)")
    parser.add_argument("--input", type=str, help="Input file path")
    parser.add_argument("--all-files", action="store_true", help="Run on all generated files")
    parser.add_argument("--model", type=str, default=None, help="Override model name")
    parser.add_argument("--errors-only", action="store_true",
                        help="Only re-run cases that previously had errors")
    args = parser.parse_args()

    # Validate args
    if not args.gate and not args.all_gates and not args.blocking_only and not args.flag_only:
        parser.error("One of --gate, --all-gates, --blocking-only, or --flag-only required")
    if not args.input and not args.all_files:
        parser.error("Either --input or --all-files required")

    # Determine gates to run
    if args.all_gates:
        gates = list(GATE_MAP.keys())
    elif args.blocking_only:
        gates = [g for g in GATE_MAP if g not in FLAG_GATES]
    elif args.flag_only:
        gates = [g for g in GATE_MAP if g in FLAG_GATES]
    else:
        gates = [args.gate]

    # Determine input files
    if args.all_files:
        input_files = find_all_generated_files()
        if not input_files:
            logger.error("No generated files found in data/1_generated/")
            sys.exit(1)
    else:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        input_files = [input_path]

    # Init
    client = OpenRouterClient(model_name=args.model)
    defeat_definitions = load_defeat_definitions()
    logger.info(f"Using model: {client.model_name}")
    logger.info(f"Gates: {gates}")
    logger.info(f"Files: {[f.name for f in input_files]}")

    # Run
    for gate_name in gates:
        for input_file in input_files:
            if not input_file.exists():
                logger.error(f"Input file not found: {input_file}")
                continue

            results = run_gate_on_file(client, gate_name, input_file, defeat_definitions,
                                       errors_only=args.errors_only)
            save_gate_results(results, gate_name, input_file)
            print_summary(results, gate_name)


if __name__ == "__main__":
    main()
