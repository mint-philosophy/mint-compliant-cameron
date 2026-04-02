#!/usr/bin/env python3
"""
Dual-use flag gate runner — GPT-5.4 medium reasoning backend.

Runs the dual_use gate on all cases in data/1_generated/ and writes
per-file results to logs/gate_verdicts/du_<stem>.json.

After the gate run, --backfill joins results by case_id back into
data/3_responses/ and data/4_evaluated/ in-place.

Usage:
    python3 scripts/run_du_gate.py --all-files           # run gate
    python3 scripts/run_du_gate.py --all-files --resume  # skip completed files
    python3 scripts/run_du_gate.py --backfill            # join results into responses + evals
    python3 scripts/run_du_gate.py --all-files --backfill  # both in one shot
    python3 scripts/run_du_gate.py --dry-run --all-files   # preview only

Cost estimate (GPT-5.4, medium reasoning):
    ~1,260 cases × ~1,100 tokens in + ~200 tokens out ≈ $8-10
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = DATA_DIR / "1_generated"
RESPONSES_DIR = DATA_DIR / "3_responses"
EVALUATED_DIR = DATA_DIR / "4_evaluated"
VERDICTS_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"
GATE_PROMPT_PATH = PROJECT_ROOT / "prompts" / "gates" / "dual_use.md"

OPENAI_MODEL = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "medium"
RETRIES = 3
INTER_CALL_DELAY_S = 0.3
COST_CEILING = 50.00  # USD — safety ceiling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

_usage: dict[str, int] = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,
    "cached_tokens": 0,
    "calls": 0,
}

PRICING = {
    "input_per_1m": 2.50,
    "cached_input_per_1m": 0.25,
    "output_per_1m": 15.00,
}


def _current_cost() -> float:
    regular = max(0, _usage["prompt_tokens"] - _usage["cached_tokens"])
    return (
        regular * PRICING["input_per_1m"] / 1_000_000
        + _usage["cached_tokens"] * PRICING["cached_input_per_1m"] / 1_000_000
        + _usage["completion_tokens"] * PRICING["output_per_1m"] / 1_000_000
    )


# ---------------------------------------------------------------------------
# OpenAI call
# ---------------------------------------------------------------------------

def call_openai(prompt: str) -> str | None:
    """Call GPT-5.4 with medium reasoning, returning raw text or None on failure."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set.")
        return None

    client = OpenAI(api_key=api_key)

    if _current_cost() >= COST_CEILING:
        logger.error(f"Cost ceiling ${COST_CEILING} reached — aborting.")
        return None

    system = (
        "You are a quality-control gate for a research dataset. "
        "Return only valid JSON — a single JSON object. "
        "No commentary, no markdown fences, no text outside the JSON."
    )

    for attempt in range(RETRIES):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                reasoning_effort=REASONING_EFFORT,
                response_format={"type": "json_object"},
                max_completion_tokens=600,
            )
            usage = response.usage
            if usage:
                _usage["prompt_tokens"] += usage.prompt_tokens or 0
                _usage["completion_tokens"] += usage.completion_tokens or 0
                _usage["calls"] += 1
                if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                    _usage["reasoning_tokens"] += getattr(
                        usage.completion_tokens_details, "reasoning_tokens", 0
                    ) or 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    _usage["cached_tokens"] += getattr(
                        usage.prompt_tokens_details, "cached_tokens", 0
                    ) or 0
                if _usage["calls"] % 100 == 0:
                    logger.info(f"  Cost so far: ${_current_cost():.2f} ({_usage['calls']} calls)")

            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()

            logger.warning(f"  Attempt {attempt + 1}/{RETRIES}: empty response")
            time.sleep(2.0 * (2 ** attempt))

        except Exception as e:
            logger.warning(f"  Attempt {attempt + 1}/{RETRIES}: {e}")
            time.sleep(2.0 * (2 ** attempt))

    logger.error("All attempts failed.")
    return None


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
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


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

def load_gate_prompt() -> str:
    if not GATE_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Gate prompt not found: {GATE_PROMPT_PATH}")
    return GATE_PROMPT_PATH.read_text(encoding="utf-8")


def load_cases(filepath: Path) -> list[dict]:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    return [data]


def verdict_path(stem: str) -> Path:
    return VERDICTS_DIR / f"du_{stem}.json"


def load_existing_verdicts(stem: str) -> dict[str, dict]:
    """Load existing verdicts keyed by case_id, or empty dict."""
    p = verdict_path(stem)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            results = json.load(f)
        return {r["case_id"]: r for r in results if "case_id" in r}
    except Exception:
        return {}


def run_gate_on_file(
    gate_template: str,
    input_file: Path,
    resume: bool,
    dry_run: bool,
) -> list[dict]:
    cases = load_cases(input_file)
    existing = load_existing_verdicts(input_file.stem) if resume else {}

    to_run = [c for c in cases if not (resume and c.get("id") in existing)]
    skip_count = len(cases) - len(to_run)

    logger.info(
        f"{input_file.name}: {len(cases)} cases"
        + (f", skipping {skip_count} existing" if skip_count else "")
        + (" [DRY RUN]" if dry_run else "")
    )

    results = list(existing.values()) if resume else []

    for i, case in enumerate(to_run):
        case_id = case.get("id", f"unknown_{i}")
        logger.info(f"  [{i + 1}/{len(to_run)}] {case_id}")

        if dry_run:
            results.append({"case_id": case_id, "dry_run": True})
            continue

        prompt = gate_template.replace("{{CASE_JSON}}", json.dumps(case, indent=2))
        raw = call_openai(prompt)

        if raw is None:
            results.append({
                "gate": "dual_use",
                "case_id": case_id,
                "pass": False,
                "flagged": False,
                "category": None,
                "reasoning": "API call failed.",
                "error": True,
            })
            continue

        parsed = extract_json(raw)
        if parsed is None:
            logger.warning(f"  Could not parse JSON for {case_id}")
            results.append({
                "gate": "dual_use",
                "case_id": case_id,
                "pass": False,
                "flagged": False,
                "category": None,
                "reasoning": f"JSON parse failure. Raw: {raw[:200]}",
                "error": True,
            })
            continue

        parsed.setdefault("case_id", case_id)
        results.append(parsed)

        flagged = parsed.get("flagged", False)
        category = parsed.get("category")
        logger.info(f"    → flagged={flagged}" + (f" [{category}]" if flagged else ""))

        time.sleep(INTER_CALL_DELAY_S)

    return results


def save_verdicts(results: list[dict], stem: str):
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    p = verdict_path(stem)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info(f"  Saved {len(results)} verdicts → {p.name}")


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def build_case_id_index() -> dict[str, dict]:
    """Build a case_id → verdict dict from all du_*.json verdict files."""
    index: dict[str, dict] = {}
    for p in sorted(VERDICTS_DIR.glob("du_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                results = json.load(f)
            for r in results:
                cid = r.get("case_id")
                if cid:
                    index[cid] = r
        except Exception as e:
            logger.warning(f"Could not load {p.name}: {e}")
    return index


def backfill_file(filepath: Path, index: dict[str, dict], dry_run: bool) -> tuple[int, int]:
    """
    Backfill gate_flags.dual_use into a response or eval file in-place.
    Returns (updated_count, total_count).
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    records_key = "responses" if "responses" in data else "evaluations"
    records = data.get(records_key, [])

    updated = 0
    for rec in records:
        case_id = rec.get("case_id")
        if not case_id:
            continue
        verdict = index.get(case_id)
        if verdict is None:
            continue

        du_entry = {
            "flagged": verdict.get("flagged", False),
            "category": verdict.get("category"),
        }

        if "gate_flags" not in rec:
            rec["gate_flags"] = {}
        rec["gate_flags"]["dual_use"] = du_entry
        updated += 1

    if updated > 0 and not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    return updated, len(records)


def run_backfill(dry_run: bool):
    logger.info("Building case_id index from verdict files...")
    index = build_case_id_index()
    logger.info(f"  {len(index)} case verdicts loaded")

    if not index:
        logger.error("No verdicts found in logs/gate_verdicts/du_*.json — run gate first.")
        return

    total_updated = 0
    total_records = 0

    for directory, label in [(RESPONSES_DIR, "3_responses"), (EVALUATED_DIR, "4_evaluated")]:
        files = sorted(directory.glob("*.json"))
        logger.info(f"\nBackfilling {label}/ ({len(files)} files){'  [DRY RUN]' if dry_run else ''}...")
        for fp in files:
            try:
                updated, total = backfill_file(fp, index, dry_run)
                if updated:
                    logger.info(f"  {fp.name}: {updated}/{total} records updated")
                    total_updated += updated
                    total_records += total
            except Exception as e:
                logger.warning(f"  {fp.name}: {e}")

    logger.info(f"\nBackfill complete: {total_updated} records updated across both directories")
    if dry_run:
        logger.info("  (dry run — no files written)")


# ---------------------------------------------------------------------------
# Cost report
# ---------------------------------------------------------------------------

def print_cost_report():
    cost = _current_cost()
    print(f"\n{'='*50}")
    print("GPT-5.4 Cost Report")
    print(f"{'='*50}")
    print(f"  Calls:             {_usage['calls']:>6}")
    print(f"  Prompt tokens:     {_usage['prompt_tokens']:>8,}")
    print(f"    Cached:          {_usage['cached_tokens']:>8,}")
    print(f"  Completion tokens: {_usage['completion_tokens']:>8,}")
    print(f"    Reasoning:       {_usage['reasoning_tokens']:>8,}")
    print(f"  Estimated cost:    ${cost:>8.4f}")
    print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run dual-use flag gate via GPT-5.4 on generated cases"
    )
    parser.add_argument("--all-files", action="store_true",
                        help="Run on all files in data/1_generated/")
    parser.add_argument("--input", type=str,
                        help="Single input file (path or filename in 1_generated/)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip case files that already have complete verdicts")
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill gate results into 3_responses/ and 4_evaluated/")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without making API calls or writing files")
    args = parser.parse_args()

    if not args.all_files and not args.input and not args.backfill:
        parser.error("Provide --all-files, --input, or --backfill")

    # Load .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    if not args.dry_run and not args.backfill:
        if not os.getenv("OPENAI_API_KEY"):
            logger.error("OPENAI_API_KEY not set. Add it to .env or export it.")
            return 1

    # Determine input files
    input_files: list[Path] = []
    if args.all_files:
        input_files = sorted(GENERATED_DIR.glob("*.json"))
        if not input_files:
            logger.error("No files found in data/1_generated/")
            return 1
    elif args.input:
        p = Path(args.input)
        if not p.is_absolute():
            p = GENERATED_DIR / p
        if not p.exists():
            logger.error(f"Input file not found: {p}")
            return 1
        input_files = [p]

    # Run gate
    if input_files:
        gate_template = load_gate_prompt()

        logger.info(f"{'='*60}")
        logger.info("DU Gate Runner")
        logger.info(f"{'='*60}")
        logger.info(f"Model:      {OPENAI_MODEL} (reasoning: {REASONING_EFFORT})")
        logger.info(f"Files:      {len(input_files)}")
        logger.info(f"Resume:     {args.resume}")
        logger.info(f"Dry run:    {args.dry_run}")
        logger.info(f"{'='*60}")

        total_flagged = 0
        total_cases = 0

        for input_file in input_files:
            results = run_gate_on_file(gate_template, input_file, args.resume, args.dry_run)

            if not args.dry_run:
                save_verdicts(results, input_file.stem)

            flagged = sum(1 for r in results if r.get("flagged"))
            total_flagged += flagged
            total_cases += len(results)

        logger.info(f"\nGate complete: {total_flagged}/{total_cases} cases flagged as dual-use")

        if not args.dry_run:
            print_cost_report()

    # Backfill
    if args.backfill:
        run_backfill(args.dry_run)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
