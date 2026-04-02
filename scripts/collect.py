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
# 16 thinking configurations + 2 base comparisons = 18 total.
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
    # Pro gets extra headroom (16k) for mandatory high-effort reasoning.
    {"id": "openai/gpt-5.4-nano", "slug": "gpt-5-4-nano-thinking",
     "extra_body": {"reasoning_effort": "high"}},
    {"id": "openai/gpt-5.4-mini", "slug": "gpt-5-4-mini-thinking",
     "extra_body": {"reasoning_effort": "high"}},
    {"id": "openai/gpt-5.4", "slug": "gpt-5-4-thinking",
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
MAX_TOKENS = 8000  # Headroom for reasoning models (only pay for tokens actually generated)
INTER_CASE_DELAY_S = 2.0
COST_CEILING = 1000.00  # USD — abort if cumulative cost exceeds this

# ---------------------------------------------------------------------------
# Pricing (per 1M tokens, via OpenRouter, March 2026)
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":      {"input": 3.00, "output": 15.00},
    "claude-opus-4-6":        {"input": 5.00, "output": 25.00},
    "gpt-5-4-nano-thinking":  {"input": 0.20, "output": 1.25},
    "gpt-5-4-mini-thinking":  {"input": 0.75, "output": 4.50},
    "gpt-5-4-mini-base":      {"input": 0.75, "output": 4.50},
    "gpt-5-4-thinking":       {"input": 2.50, "output": 15.00},
    "gpt-5-4-base":           {"input": 2.50, "output": 15.00},
    "gemini-3-1-pro":         {"input": 2.00, "output": 12.00},
    "gemini-3-1-flash-lite":  {"input": 0.25, "output": 1.50},
    "qwen-3-5-flash":         {"input": 0.065, "output": 0.26},
    "qwen-3-5-plus":          {"input": 0.26, "output": 1.56},
    "qwen-3-5-397b":          {"input": 0.39, "output": 2.34},
    "glm-5-turbo":            {"input": 0.96, "output": 3.20},
    "glm-5":                  {"input": 0.72, "output": 2.30},
    "nemotron-3-nano":        {"input": 0.00, "output": 0.00},
    "nemotron-3-super":       {"input": 0.00, "output": 0.00},
    "grok-4-fast":            {"input": 0.20, "output": 0.50},
    "grok-4":                 {"input": 3.00, "output": 15.00},
}


# ---------------------------------------------------------------------------
# Cost tracker (shared across all models in a run)
# ---------------------------------------------------------------------------
class CostTracker:
    """Track cumulative API cost and abort if ceiling is exceeded."""

    def __init__(self, ceiling: float = COST_CEILING):
        self.ceiling = ceiling
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_reasoning_tokens = 0
        self.calls = 0
        self._per_model: dict[str, float] = {}

    def record(self, slug: str, usage: dict | None):
        """Record a single API call's cost. Returns True if under ceiling."""
        if not usage:
            return True

        prices = MODEL_PRICING.get(slug, {"input": 5.0, "output": 25.0})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        reasoning_tokens = usage.get("reasoning_tokens", 0)

        cost = (input_tokens / 1_000_000) * prices["input"] + \
               (output_tokens / 1_000_000) * prices["output"]

        self.total_cost += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_reasoning_tokens += reasoning_tokens
        self.calls += 1
        self._per_model[slug] = self._per_model.get(slug, 0.0) + cost

        return self.total_cost < self.ceiling

    def log_status(self, every_n: int = 50):
        """Log cost status every N calls."""
        if self.calls > 0 and self.calls % every_n == 0:
            logger.info(
                f"  COST: ${self.total_cost:.2f} / ${self.ceiling:.0f} ceiling "
                f"({self.calls} calls, {self.total_input_tokens:,} in, "
                f"{self.total_output_tokens:,} out, {self.total_reasoning_tokens:,} reasoning)"
            )

    def is_over_ceiling(self) -> bool:
        return self.total_cost >= self.ceiling

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"COST SUMMARY",
            f"{'='*60}",
            f"  Total cost:       ${self.total_cost:.2f}",
            f"  API calls:        {self.calls:,}",
            f"  Input tokens:     {self.total_input_tokens:,}",
            f"  Output tokens:    {self.total_output_tokens:,}",
            f"  Reasoning tokens: {self.total_reasoning_tokens:,}",
            f"  Ceiling:          ${self.ceiling:.0f}",
            f"",
            f"  Per-model breakdown:",
        ]
        for slug, cost in sorted(self._per_model.items(), key=lambda x: -x[1]):
            lines.append(f"    {slug:<28s} ${cost:.2f}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


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
        result = client.generate_with_retry(
            prompt=user_query,
            system_prompt="",
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            json_mode=False,
            retries=5,
            base_delay=2.0,
            extra_body=model_info.get("extra_body"),
        )

        if result is None:
            return {
                "case_id": case_id,
                "model": model_info["id"],
                "user_query": user_query,
                "response": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error_message": "All retry attempts returned empty/null",
                "gate_flags": get_flag_gate_metadata(case_id, stem),
                "usage": None,
            }

        return {
            "case_id": case_id,
            "model": model_info["id"],
            "user_query": user_query,
            "response": result.content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "error_message": None,
            "gate_flags": get_flag_gate_metadata(case_id, stem),
            "usage": result.usage_dict(),
        }

    except Exception as exc:
        logger.error(f"[{case_id}] API error for {model_info['slug']}: {exc}")
        return {
            "case_id": case_id,
            "model": model_info["id"],
            "user_query": user_query,
            "response": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error_message": str(exc),
            "gate_flags": get_flag_gate_metadata(case_id, stem),
            "usage": None,
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
    cost_tracker: CostTracker | None = None,
) -> tuple[int, int, int]:
    """
    Collect responses for all cases in a filtered file.
    Saves incrementally after each case to avoid data loss on interruption.

    Cases in 2_filtered/ have already passed all blocking gates.
    No gate checking is performed here.

    Returns (collected, skipped, errors).
    """
    stem = input_file.stem
    cases = load_cases_from_file(input_file)
    source_metadata = load_metadata_from_file(input_file)
    model_slug = model_info["slug"]

    # If --sample, restrict to sample IDs
    if sample_ids is not None:
        cases = [c for c in cases if c.get("id") in sample_ids]
        if not cases:
            return 0, 0, 0

    # Load existing responses (for --new-only merge and incremental append)
    out_path = output_path_for(model_slug, stem)
    existing_responses: list[dict] = []
    if out_path.exists():
        with open(out_path) as f:
            existing_data = json.load(f)
        existing_responses = existing_data.get("responses", [])

    existing_ids = {r.get("case_id") for r in existing_responses}

    # If --new-only, skip cases already collected
    eligible = cases
    already_collected = 0
    if new_only:
        eligible = [c for c in cases if c.get("id") not in existing_ids]
        already_collected = len(cases) - len(eligible)
    elif existing_ids:
        # Even without --new-only, skip cases already in the file (incremental safety)
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

    # Collect responses with incremental saves
    responses = list(existing_responses)  # start from what we have
    errors = 0

    for i, case in enumerate(eligible):
        # Check cost ceiling before each call
        if cost_tracker and cost_tracker.is_over_ceiling():
            logger.error(
                f"COST CEILING REACHED: ${cost_tracker.total_cost:.2f} >= "
                f"${cost_tracker.ceiling:.0f}. Aborting."
            )
            break

        cid = case.get("id", "unknown")
        logger.info(f"    [{i+1}/{len(eligible)}] {cid}")

        result = collect_single_case(client, case, model_info, stem)
        responses.append(result)

        if result["status"] == "error":
            errors += 1

        # Record cost
        if cost_tracker:
            cost_tracker.record(model_slug, result.get("usage"))
            cost_tracker.log_status(every_n=50)

        # Incremental save after each case
        save_responses(responses, model_info, source_metadata, stem)

        # Delay between cases (skip after last case)
        if i < len(eligible) - 1:
            time.sleep(INTER_CASE_DELAY_S)

    collected = sum(1 for r in responses if r.get("status") == "success")
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
    parser.add_argument("--provider", type=str, default=None,
                        choices=["anthropic", "openai", "google", "qwen", "glm", "nvidia", "xai"],
                        help="Run only models from this provider (for staggered parallel launches)")
    parser.add_argument("--cost-ceiling", type=float, default=COST_CEILING,
                        help=f"Abort if cumulative cost exceeds this (default: ${COST_CEILING:.0f})")
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
    PROVIDER_PREFIXES = {
        "anthropic": "anthropic/",
        "openai": "openai/",
        "google": "google/",
        "qwen": "qwen/",
        "glm": "z-ai/",
        "nvidia": "nvidia/",
        "xai": "x-ai/",
    }

    if args.model:
        matched = [m for m in TARGET_MODELS if m["id"] == args.model]
        if not matched:
            logger.error(
                f"Unknown model: {args.model}. "
                f"Available: {[m['id'] for m in TARGET_MODELS]}"
            )
            return 1
        models = matched
    elif args.provider:
        prefix = PROVIDER_PREFIXES.get(args.provider, args.provider + "/")
        models = [m for m in TARGET_MODELS if m["id"].startswith(prefix)]
        if not models:
            logger.error(f"No models found for provider: {args.provider}")
            return 1
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

    # Initialize cost tracker
    cost_tracker = CostTracker(ceiling=args.cost_ceiling)

    logger.info(f"{'='*60}")
    logger.info(f"v4 Response Collector")
    logger.info(f"{'='*60}")
    logger.info(f"Models: {[m['id'] for m in models]}")
    logger.info(f"Files:  {len(input_files)} generated file(s)")
    if sample_ids:
        logger.info(f"Sample: {len(sample_ids)} cases (pilot mode)")
    if args.provider:
        logger.info(f"Provider: {args.provider}")
    logger.info(f"Resume: {args.resume}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Temperature: {TEMPERATURE}")
    logger.info(f"Max tokens: {MAX_TOKENS}")
    logger.info(f"Cost ceiling: ${args.cost_ceiling:.0f}")
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
                cost_tracker=cost_tracker,
            )
            summary[model_slug]["collected"] += collected
            summary[model_slug]["gate_skipped"] += skipped
            summary[model_slug]["errors"] += errors

            # Check cost ceiling after each file
            if cost_tracker.is_over_ceiling():
                logger.error(f"COST CEILING REACHED. Stopping all collection.")
                break

        # Break outer loop too if ceiling hit
        if cost_tracker.is_over_ceiling():
            break

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

    # Print cost summary
    if not args.dry_run:
        print(f"\n{cost_tracker.summary()}")

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
