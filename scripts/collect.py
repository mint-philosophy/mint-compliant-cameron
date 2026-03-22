#!/usr/bin/env python3
"""
v4 response collector -- sends gated cases to AI models via OpenRouter and records responses.

Reads cases from data/2_filtered/ (pre-filtered by quality gates), attaches flag gate
metadata, then sends each case's user_query to target models.

Cases in 2_filtered/ have already passed all blocking gates (OV, RJ). No gate checking
is performed here — the filtering happened upstream via clean_pipeline.py.

Usage:
    python3 scripts/collect.py --all-files                               # All models, all files
    python3 scripts/collect.py --model anthropic/claude-sonnet-4-6 --all-files   # One model
    python3 scripts/collect.py --dry-run --all-files                      # Preview
    python3 scripts/collect.py --all-files --resume                       # Skip completed
    python3 scripts/collect.py --input data/2_filtered/control_workplace.json   # One file
    python3 scripts/collect.py --all-files --new-only                     # Only cases not yet collected
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = DATA_DIR / "1_generated"
FILTERED_DIR = DATA_DIR / "2_filtered"
GATED_DIR = PROJECT_ROOT / "logs" / "gate_verdicts"
RESPONSES_DIR = DATA_DIR / "3_responses"

sys.path.insert(0, str(SCRIPT_DIR))
from openrouter_client import OpenRouterClient  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Target models -- all routed through OpenRouter
#
# 17 thinking configurations + 2 base comparisons = 19 total.
# See paper/model_suite.md for full documentation, pricing, and rationale.
#
# Each model has:
#   id:         OpenRouter model ID (used for API calls)
#   slug:       Short filename-safe identifier (used in output filenames)
#   extra_body: Provider-specific params passed through OpenRouter (reasoning, etc.)
# ---------------------------------------------------------------------------
TARGET_MODELS: list[dict] = [
    # --- Anthropic Claude 4.6 (extended thinking enabled by default) ---
    {"id": "anthropic/claude-sonnet-4.6", "slug": "claude-sonnet-4-6"},
    {"id": "anthropic/claude-opus-4.6", "slug": "claude-opus-4-6"},

    # --- OpenAI GPT-5.4 (thinking) — reasoning must be explicitly enabled ---
    {"id": "openai/gpt-5.4-nano", "slug": "gpt-5-4-nano-thinking",
     "extra_body": {"reasoning_effort": "high"}},
    {"id": "openai/gpt-5.4-mini", "slug": "gpt-5-4-mini-thinking",
     "extra_body": {"reasoning_effort": "high"}},
    {"id": "openai/gpt-5.4", "slug": "gpt-5-4-thinking",
     "extra_body": {"reasoning_effort": "high"}},
    {"id": "openai/gpt-5.4-pro", "slug": "gpt-5-4-pro-thinking",
     "extra_body": {"reasoning_effort": "high"}},

    # --- OpenAI GPT-5.4 (base comparisons) — reasoning disabled ---
    {"id": "openai/gpt-5.4", "slug": "gpt-5-4-base",
     "extra_body": {"reasoning_effort": "none"}},
    {"id": "openai/gpt-5.4-mini", "slug": "gpt-5-4-mini-base",
     "extra_body": {"reasoning_effort": "none"}},

    # --- Google Gemini 3.1 (Pro: mandatory reasoning; Flash Lite: medium) ---
    {"id": "google/gemini-3.1-pro-preview", "slug": "gemini-3-1-pro"},
    {"id": "google/gemini-3.1-flash-lite-preview", "slug": "gemini-3-1-flash-lite"},

    # --- Qwen 3.5 ---
    {"id": "qwen/qwen3.5-flash-02-23", "slug": "qwen-3-5-flash"},
    {"id": "qwen/qwen3.5-plus-02-15", "slug": "qwen-3-5-plus"},
    {"id": "qwen/qwen3.5-397b-a17b", "slug": "qwen-3-5-397b"},

    # --- GLM 5 (reasoning via <think> tags, enabled by default) ---
    {"id": "z-ai/glm-5-turbo", "slug": "glm-5-turbo"},
    {"id": "z-ai/glm-5", "slug": "glm-5"},

    # --- NVIDIA Nemotron 3 (free tier) ---
    {"id": "nvidia/nemotron-3-nano-30b-a3b:free", "slug": "nemotron-3-nano"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "slug": "nemotron-3-super"},

    # --- xAI Grok 4 (reasoning toggle available, enabled for our runs) ---
    {"id": "x-ai/grok-4-fast", "slug": "grok-4-fast"},
    {"id": "x-ai/grok-4", "slug": "grok-4"},
]

# ---------------------------------------------------------------------------
# Gate configuration
# ---------------------------------------------------------------------------
# Blocking gates (OV, RJ) are applied UPSTREAM by clean_pipeline.py.
# Cases in 2_filtered/ have already passed all blocking gates.
# Only flag gates are referenced here for metadata attachment.
FLAG_GATES = {"du"}                    # metadata only, never filter

# ---------------------------------------------------------------------------
# Collection parameters
# ---------------------------------------------------------------------------
TEMPERATURE = 0.0
MAX_TOKENS = 2000
INTER_CASE_DELAY_S = 2.0


# ===================================================================
# Data loading helpers
# ===================================================================

def load_cases_from_file(filepath: Path) -> list[dict]:
    """Load cases from a generated file (handles both flat arrays and {metadata, cases})."""
    with open(filepath) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    return [data]


def load_metadata_from_file(filepath: Path) -> dict:
    """Load metadata from a generated file."""
    with open(filepath) as f:
        data = json.load(f)
    if isinstance(data, dict) and "metadata" in data:
        return data["metadata"]
    return {}


def find_all_filtered_files() -> list[Path]:
    """Find all filtered case files (pre-gated)."""
    if not FILTERED_DIR.exists():
        logger.error(f"Filtered directory not found: {FILTERED_DIR}")
        logger.error("Run clean_pipeline.py first to create data/2_filtered/")
        return []
    return sorted(FILTERED_DIR.glob("*.json"))


def load_gate_results(gate_prefix: str, stem: str) -> dict[str, dict]:
    """
    Load gate results for a specific gate prefix and file stem.
    Returns a dict keyed by case_id.
    """
    gate_file = GATED_DIR / f"{gate_prefix}_{stem}.json"
    if not gate_file.exists():
        return {}

    with open(gate_file) as f:
        results = json.load(f)

    by_id: dict[str, dict] = {}
    for entry in results:
        cid = entry.get("case_id")
        if cid:
            by_id[cid] = entry
    return by_id


def get_flag_gate_metadata(case_id: str, stem: str) -> dict:
    """
    Collect flag gate metadata for a case.
    Returns a dict with dual_use sub-dict.
    """
    flags: dict = {}

    # dual_use
    du_results = load_gate_results("du", stem)
    du_entry = du_results.get(case_id, {})
    flags["dual_use"] = {
        "flagged": du_entry.get("flagged", None),
        "category": du_entry.get("category", None),
    }

    return flags


# ===================================================================
# Output helpers
# ===================================================================

def output_path_for(model_slug: str, stem: str) -> Path:
    """Build the output file path for a model + file stem combo."""
    return RESPONSES_DIR / f"{model_slug}_{stem}.json"


def output_exists(model_slug: str, stem: str) -> bool:
    """Check whether responses have already been collected for this combo."""
    return output_path_for(model_slug, stem).exists()


def save_responses(
    responses: list[dict],
    model_info: dict,
    source_metadata: dict,
    stem: str,
) -> Path:
    """Save collected responses to disk."""
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = output_path_for(model_info["slug"], stem)

    payload = {
        "metadata": {
            "model_id": model_info["id"],
            "model_slug": model_info["slug"],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "source_file": stem,
            "source_metadata": source_metadata,
            "collection_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_responses": len(responses),
            "successful": sum(1 for r in responses if r["status"] == "success"),
            "errors": sum(1 for r in responses if r["status"] == "error"),
        },
        "responses": responses,
    }

    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    logger.info(f"Saved {len(responses)} responses to {out_path.name}")
    return out_path


# ===================================================================
# Collection logic
# ===================================================================

def collect_single_case(
    client: OpenRouterClient,
    case: dict,
    model_info: dict,
    stem: str,
) -> dict:
    """Send a single case's user_query to the model and return a response record."""
    case_id = case.get("id", "unknown")
    user_query = case.get("user_query", "")

    if not user_query:
        return {
            "case_id": case_id,
            "model": model_info["id"],
            "response": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error_message": "Case has no user_query field",
            "gate_flags": get_flag_gate_metadata(case_id, stem),
        }

    try:
        # Send with empty system prompt to get the model's default behavior.
        # OpenRouter requires a system message to be present, so we pass an
        # empty string which models treat as "no system prompt".
        response_text = client.generate_with_retry(
            prompt=user_query,
            system_prompt="",
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            json_mode=False,
            retries=5,
            base_delay=2.0,
            extra_body=model_info.get("extra_body"),
        )

        if response_text is None:
            return {
                "case_id": case_id,
                "model": model_info["id"],
                "response": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error_message": "All retry attempts returned empty/null",
                "gate_flags": get_flag_gate_metadata(case_id, stem),
            }

        return {
            "case_id": case_id,
            "model": model_info["id"],
            "response": response_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "error_message": None,
            "gate_flags": get_flag_gate_metadata(case_id, stem),
        }

    except Exception as exc:
        logger.error(f"[{case_id}] API error for {model_info['slug']}: {exc}")
        return {
            "case_id": case_id,
            "model": model_info["id"],
            "response": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error_message": str(exc),
            "gate_flags": get_flag_gate_metadata(case_id, stem),
        }


def load_existing_case_ids(model_slug: str, stem: str) -> set[str]:
    """Load case IDs already collected for this model+stem combo."""
    out_path = output_path_for(model_slug, stem)
    if not out_path.exists():
        return set()
    with open(out_path) as f:
        data = json.load(f)
    return {r.get("case_id") for r in data.get("responses", [])}


def collect_file_for_model(
    client: OpenRouterClient,
    model_info: dict,
    input_file: Path,
    dry_run: bool = False,
    new_only: bool = False,
    sample_ids: set[str] | None = None,
) -> tuple[int, int, int]:
    """
    Collect responses for all cases in a filtered file.

    Cases in 2_filtered/ have already passed all blocking gates.
    No gate checking is performed here.

    Returns (collected, skipped, errors).
    """
    stem = input_file.stem
    cases = load_cases_from_file(input_file)
    source_metadata = load_metadata_from_file(input_file)

    # If --sample, restrict to sample IDs
    if sample_ids is not None:
        cases = [c for c in cases if c.get("id") in sample_ids]
        if not cases:
            return 0, 0, 0

    # If --new-only, skip cases already collected for this model
    eligible = cases
    already_collected = 0
    if new_only:
        existing_ids = load_existing_case_ids(model_info["slug"], stem)
        eligible = [c for c in cases if c.get("id") not in existing_ids]
        already_collected = len(cases) - len(eligible)

    logger.info(
        f"  {input_file.name}: {len(eligible)} cases to collect"
        + (f" ({already_collected} already collected)" if already_collected else "")
    )

    if dry_run:
        for case in eligible:
            logger.info(f"    [dry-run] Would collect: {case.get('id')}")
        return len(eligible), already_collected, 0

    if not eligible:
        return 0, already_collected, 0

    # Collect responses
    responses: list[dict] = []
    errors = 0

    for i, case in enumerate(eligible):
        cid = case.get("id", "unknown")
        logger.info(f"    [{i+1}/{len(eligible)}] {cid}")

        result = collect_single_case(client, case, model_info, stem)
        responses.append(result)

        if result["status"] == "error":
            errors += 1

        # Delay between cases (skip after last case)
        if i < len(eligible) - 1:
            time.sleep(INTER_CASE_DELAY_S)

    # If new_only, merge with existing responses
    if new_only:
        out_path = output_path_for(model_info["slug"], stem)
        if out_path.exists():
            with open(out_path) as f:
                existing_data = json.load(f)
            existing_responses = existing_data.get("responses", [])
            responses = existing_responses + responses

    # Save (replaces file with full response set)
    save_responses(responses, model_info, source_metadata, stem)

    collected = len(responses) - errors
    return collected, already_collected, errors


# ===================================================================
# Main
# ===================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="v4 response collector -- send gated cases to AI models via OpenRouter"
    )
    parser.add_argument("--input", type=str, help="Single input file path")
    parser.add_argument("--all-files", action="store_true", help="Process all generated files")
    parser.add_argument(
        "--model", type=str, default=None,
        help="Run only one model (full OpenRouter ID, e.g. anthropic/claude-sonnet-4-6)",
    )
    parser.add_argument("--resume", action="store_true", help="Skip model+file combos with existing output")
    parser.add_argument("--new-only", action="store_true", help="Only collect cases not yet in existing response files")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be collected without API calls")
    parser.add_argument("--sample", type=str, default=None,
                        help="Path to JSON file with case IDs to collect (pilot mode)")
    args = parser.parse_args()

    if not args.input and not args.all_files:
        parser.error("Either --input or --all-files required")

    # Determine input files (from 2_filtered/, not 1_generated/)
    if args.all_files:
        input_files = find_all_filtered_files()
        if not input_files:
            logger.error("No filtered files found in data/2_filtered/")
            logger.error("Run clean_pipeline.py first to create the filtered dataset.")
            return 1
    else:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        if not input_path.exists():
            logger.error(f"Input file not found: {input_path}")
            return 1
        input_files = [input_path]

    # Determine models
    if args.model:
        matched = [m for m in TARGET_MODELS if m["id"] == args.model]
        if not matched:
            logger.error(
                f"Unknown model: {args.model}. "
                f"Available: {[m['id'] for m in TARGET_MODELS]}"
            )
            return 1
        models = matched
    else:
        models = TARGET_MODELS

    # Load sample IDs if provided
    sample_ids: set[str] | None = None
    if args.sample:
        sample_path = Path(args.sample)
        if not sample_path.is_absolute():
            sample_path = PROJECT_ROOT / sample_path
        with open(sample_path) as f:
            sample_ids = set(json.load(f))
        logger.info(f"Pilot mode: {len(sample_ids)} sample case IDs loaded")

    logger.info(f"{'='*60}")
    logger.info(f"v4 Response Collector")
    logger.info(f"{'='*60}")
    logger.info(f"Models: {[m['id'] for m in models]}")
    logger.info(f"Files:  {len(input_files)} generated file(s)")
    if sample_ids:
        logger.info(f"Sample: {len(sample_ids)} cases (pilot mode)")
    logger.info(f"Resume: {args.resume}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Temperature: {TEMPERATURE}")
    logger.info(f"Max tokens: {MAX_TOKENS}")
    logger.info(f"{'='*60}")

    # Summary accumulators
    summary: dict[str, dict[str, int]] = {}

    for model_info in models:
        model_slug = model_info["slug"]
        model_id = model_info["id"]
        summary[model_slug] = {"collected": 0, "gate_skipped": 0, "errors": 0, "file_skipped": 0}

        # Create a fresh client for each model
        if not args.dry_run:
            try:
                client = OpenRouterClient(model_name=model_id)
            except Exception as exc:
                logger.error(f"Failed to initialize client for {model_id}: {exc}")
                continue
        else:
            client = None  # type: ignore[assignment]

        logger.info(f"\n{'='*60}")
        logger.info(f"Model: {model_id} ({model_slug})")
        logger.info(f"{'='*60}")

        for input_file in input_files:
            stem = input_file.stem

            # Resume: skip if output already exists
            if args.resume and output_exists(model_slug, stem):
                logger.info(f"  Skipping {stem} (output exists, --resume)")
                summary[model_slug]["file_skipped"] += 1
                continue

            collected, skipped, errors = collect_file_for_model(
                client, model_info, input_file,
                dry_run=args.dry_run,
                new_only=args.new_only,
                sample_ids=sample_ids,
            )
            summary[model_slug]["collected"] += collected
            summary[model_slug]["gate_skipped"] += skipped
            summary[model_slug]["errors"] += errors

    # Print summary
    print(f"\n{'='*60}")
    print(f"COLLECTION SUMMARY")
    print(f"{'='*60}")
    for model_slug, stats in summary.items():
        print(f"\n  {model_slug}:")
        print(f"    Collected:     {stats['collected']}")
        print(f"    Gate-skipped:  {stats['gate_skipped']}")
        print(f"    Errors:        {stats['errors']}")
        if args.resume:
            print(f"    File-skipped:  {stats['file_skipped']} (--resume)")
    print(f"\n{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# TODO: Multi-turn persuasion follow-up (Phase 2)
#
# v2's DESIGN_DECISIONS.md (section 1) describes a two-phase protocol:
#
#   Phase 1 (Baseline): Send the full user_query. This is what THIS script
#   implements. Primary signal-detection measure.
#
#   Phase 2 (Multi-turn persuasion): For cases where the model REFUSES in
#   Phase 1, inject the model's refusal response and send a follow-up message
#   that challenges the rule's legitimacy. Tests persuadability and whether
#   the refusal is rigid or responsive to argument.
#
# Implementation notes for Phase 2:
#   - Requires Phase 1 to be complete and evaluated (refusals identified)
#   - Follow-up prompts should be generated per-case, incorporating the
#     specific refusal text and the structural_facts / defeat_condition
#     from the original case
#   - Same models, same OpenRouter pipeline
#   - Output to data/4_persuasion/ or similar
#   - Needs a separate evaluation pass to classify whether the model changed
#     its mind after the follow-up
#
# This is NOT implemented here. Build as a separate script (e.g. collect_p2.py)
# once Phase 1 collection and evaluation are complete.
# ---------------------------------------------------------------------------
