#!/usr/bin/env python3
"""
Run a quality gate on ALL generated cases using claude -p CLI.

Saves results incrementally to avoid losing progress on interruption.
Can be resumed — skips cases already in the output file.

Usage:
    python3 scripts/run_ov_full.py                                # OV gate (default)
    python3 scripts/run_ov_full.py --gate reasonable_judge        # RJ gate
    python3 scripts/run_ov_full.py --model opus --workers 4
    python3 scripts/run_ov_full.py --gate reasonable_judge --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
GENERATED_DIR = PROJECT_ROOT / "data" / "1_generated"
GATES_DIR = PROJECT_ROOT / "prompts" / "gates"
DEFEATS_DIR = PROJECT_ROOT / "prompts" / "defeats"
OUTPUT_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_all_cases() -> list[dict]:
    """Load all cases from all generated files."""
    cases = []
    for f in sorted(GENERATED_DIR.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
        file_cases = data.get("cases", data) if isinstance(data, dict) else data
        if isinstance(file_cases, list):
            cases.extend(file_cases)
    return cases


GATE_PREFIX_MAP = {
    "operational_validity": "ov",
    "reasonable_judge": "rj",
    "dual_use": "du",
}

# Gates that need defeat subtype definition injected into the prompt
GATES_NEEDING_DEFEAT_DEF = {"operational_validity"}


def load_gate_prompt(gate_name: str) -> str:
    path = GATES_DIR / f"{gate_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Gate prompt not found: {path}")
    return path.read_text()


def load_defeat_definitions() -> dict[str, str]:
    defs = {}
    for f in DEFEATS_DIR.glob("*.md"):
        defs[f.stem] = f.read_text()
    return defs


def build_prompt(gate_template: str, case: dict, defeat_defs: dict, gate_name: str) -> str:
    prompt = gate_template
    prompt = prompt.replace("{{CASE_JSON}}", json.dumps(case, indent=2))
    if gate_name in GATES_NEEDING_DEFEAT_DEF:
        defeat_type = case.get("defeat_type", "")
        defeat_def = defeat_defs.get(defeat_type, "No definition available.")
        prompt = prompt.replace("{{DEFEAT_SUBTYPE_DEFINITION}}", defeat_def)
    return prompt


def extract_json_object(text: str) -> dict | None:
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


def run_gate_on_case(
    gate_template: str, case: dict, defeat_defs: dict,
    gate_name: str = "operational_validity",
    model: str | None = None, retries: int = 3,
) -> dict | None:
    """Run a gate on a single case via claude -p CLI."""
    prompt = build_prompt(gate_template, case, defeat_defs, gate_name)
    system_prompt = (
        "You are a quality gate for a research dataset. "
        "Return only valid JSON — a single JSON object. "
        "No commentary, no markdown fences, no text before or after the JSON."
    )

    cmd = [
        "claude", "-p",
        "--system-prompt", system_prompt,
        "--tools", "",
        "--output-format", "text",
        "--no-session-persistence",
    ]
    if model:
        cmd.extend(["--model", model])

    last_error = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                logger.warning(f"Attempt {attempt + 1}: code {result.returncode}: {result.stderr[:200]}")
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
                logger.warning(f"Attempt {attempt + 1}: JSON parse failed")
                time.sleep(2 ** attempt)
                continue

            if "case_id" not in parsed:
                parsed["case_id"] = case.get("id", "unknown")
            return parsed

        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt + 1}: timeout (180s)")
            last_error = "timeout"
            time.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: {e}")
            last_error = str(e)
            time.sleep(2 ** attempt)

    logger.error(f"All {retries} attempts failed. Last error: {last_error}")
    return None


# Thread-safe file writing
write_lock = Lock()


def save_result(output_path: Path, case_id: str, result: dict, all_results: dict):
    """Save a single result incrementally."""
    with write_lock:
        all_results[case_id] = result
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Run a quality gate on full dataset via claude CLI")
    parser.add_argument("--gate", type=str, default="operational_validity",
                        help="Gate name (default: operational_validity)")
    parser.add_argument("--model", type=str, default="opus",
                        help="Claude model alias (default: opus)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from existing output file")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path")
    args = parser.parse_args()

    gate_name = args.gate
    prefix = GATE_PREFIX_MAP.get(gate_name, gate_name[:2])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else OUTPUT_DIR / f"{prefix}_full_results.json"

    # Load existing results if resuming
    all_results = {}
    if args.resume and output_path.exists():
        with open(output_path) as f:
            all_results = json.load(f)
        logger.info(f"Resuming: {len(all_results)} cases already completed")

    # Load cases and resources
    cases = load_all_cases()
    gate_template = load_gate_prompt(gate_name)
    defeat_defs = load_defeat_definitions()
    logger.info(f"Gate: {gate_name} | Model: {args.model}")

    # Filter out already-completed cases
    pending = [c for c in cases if c.get("id", "") not in all_results]
    logger.info(f"Total cases: {len(cases)} | Already done: {len(all_results)} | Pending: {len(pending)}")

    if not pending:
        logger.info("All cases already processed!")
        print_summary(all_results)
        return

    errors = 0
    start_time = time.time()

    if args.workers <= 1:
        # Sequential execution
        for i, case in enumerate(pending):
            case_id = case.get("id", f"unknown_{i}")
            logger.info(f"[{len(all_results) + 1}/{len(cases)}] {case_id}")

            result = run_gate_on_case(gate_template, case, defeat_defs,
                                      gate_name=gate_name, model=args.model)
            if result:
                save_result(output_path, case_id, result, all_results)
            else:
                errors += 1
                save_result(output_path, case_id, {"error": True, "case_id": case_id}, all_results)

            # Progress estimate
            elapsed = time.time() - start_time
            done = i + 1
            rate = elapsed / done
            remaining = (len(pending) - done) * rate
            logger.info(f"  ETA: {remaining/3600:.1f}h remaining ({rate:.0f}s/case)")
    else:
        # Parallel execution
        logger.info(f"Running with {args.workers} parallel workers")

        def process_case(case_with_idx):
            idx, case = case_with_idx
            case_id = case.get("id", f"unknown_{idx}")
            result = run_gate_on_case(gate_template, case, defeat_defs,
                                      gate_name=gate_name, model=args.model)
            return case_id, result

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_case, (i, c)): i
                for i, c in enumerate(pending)
            }
            completed = 0
            for future in as_completed(futures):
                case_id, result = future.result()
                completed += 1
                if result:
                    save_result(output_path, case_id, result, all_results)
                    status = "PASS" if result.get("pass") else "FAIL/FLAG"
                else:
                    errors += 1
                    save_result(output_path, case_id, {"error": True, "case_id": case_id}, all_results)
                    status = "ERROR"

                elapsed = time.time() - start_time
                rate = elapsed / completed
                remaining = (len(pending) - completed) * rate / args.workers
                logger.info(f"[{len(all_results)}/{len(cases)}] {case_id}: {status} | ETA: {remaining/3600:.1f}h")

    elapsed_total = time.time() - start_time
    logger.info(f"Completed in {elapsed_total/3600:.1f}h | Errors: {errors}")

    print_summary(all_results)


def print_summary(results: dict):
    """Print pass/fail/error summary."""
    passed = sum(1 for r in results.values() if r.get("pass") is True)
    failed = sum(1 for r in results.values() if r.get("pass") is False)
    errored = sum(1 for r in results.values() if r.get("error"))
    total = len(results)

    # Infer gate name from results
    gate_label = "GATE"
    sample = next(iter(results.values()), {})
    if sample.get("gate"):
        gate_label = sample["gate"].upper()

    print(f"\n{'=' * 60}")
    print(f"{gate_label} — FULL DATASET RESULTS")
    print(f"{'=' * 60}")
    print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Errors: {errored}")
    print(f"Pass rate: {passed/total:.1%}" if total else "No results")

    if failed:
        print(f"\n{'─' * 60}")
        print(f"FAILED CASES ({failed}):")
        for case_id, r in sorted(results.items()):
            if r.get("pass") is False:
                checks = r.get("checks", {})
                failed_checks = [
                    k for k, v in checks.items()
                    if isinstance(v, dict) and not v.get("pass")
                ]
                reason = r.get("overall_reasoning", "")[:100]
                print(f"  {case_id}")
                print(f"    Failed: {', '.join(failed_checks)}")
                print(f"    Reason: {reason}")

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
