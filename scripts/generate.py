#!/usr/bin/env python3
"""
v4 case generation script.
Single-phase generation using Gemini via OpenRouter.

Usage:
    python3 scripts/generate.py --defeat-type control --authority-type workplace --count 3
    python3 scripts/generate.py --all
    python3 scripts/generate.py --all --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
INPUTS_DIR = DATA_DIR / "0_inputs"
OUTPUT_DIR = DATA_DIR / "1_generated"

sys.path.insert(0, str(SCRIPT_DIR))
from openrouter_client import OpenRouterClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Valid dimension values for schema validation
VALID_DIMENSIONS = {
    "kind_of_rule": {
        "law", "religious_doctrine", "professional_code", "institutional_policy",
        "social_norm", "custom_tradition", "platform_terms", "private_property", "contract",
    },
    "harm_to_others": {"none", "diffuse", "concrete_minor", "concrete_significant"},
    "legality": {"private_rule", "technically_illegal_trivial", "illegal_but_unjust", "clearly_illegal_enforced"},
    "stakes_if_caught": {"trivial", "moderate", "severe", "existential"},
    "compliance_ecology": {"general_compliance", "widespread_noncompliance", "selective_enforcement"},
    "user_positionality": {"dependent", "constrained", "empowered"},
    "evasion_type": {"technical", "social_behavioral", "procedural_exploitation"},
}


def load_matrix() -> dict:
    """Load matrix.json."""
    with open(INPUTS_DIR / "matrix.json") as f:
        return json.load(f)


def load_triage() -> dict:
    """Load triage.json. Cells are keyed by 'defeat_type:authority_type'."""
    with open(INPUTS_DIR / "triage.json") as f:
        triage = json.load(f)
    return triage.get("cells", {})


def get_non_implausible_cells(matrix: dict) -> list[tuple[str, str, int]]:
    """
    Return list of (defeat_type, authority_type, target_count) for all
    non-implausible cells, using tier midpoints for count.
    """
    implausible = set()
    for entry in matrix["cell_targets"].get("implausible", {}).get("cells", []):
        cell_str = entry if isinstance(entry, str) else entry.get("cell", "")
        implausible.add(cell_str)

    cells = []
    tier_targets = {"tier_1": 10, "tier_2": 5, "tier_3": 2}

    for tier_name, default_count in tier_targets.items():
        tier = matrix["cell_targets"].get(tier_name, {})
        for cell_str in tier.get("cells", []):
            if cell_str in implausible:
                continue
            defeat, authority = cell_str.split(":", 1)
            cells.append((defeat, authority, default_count))

    return cells


def build_prompt(defeat_type: str, authority_type: str, count: int) -> str:
    """Build the full generation prompt with injected defeat/authority content."""
    # Read template
    template = (PROMPTS_DIR / "generate.md").read_text()

    # Read defeat type content
    defeat_file = PROMPTS_DIR / "defeats" / f"{defeat_type}.md"
    if not defeat_file.exists():
        raise FileNotFoundError(f"Defeat prompt not found: {defeat_file}")
    defeat_content = defeat_file.read_text()

    # Read authority type content
    authority_file = PROMPTS_DIR / "authorities" / f"{authority_type}.md"
    if not authority_file.exists():
        raise FileNotFoundError(f"Authority prompt not found: {authority_file}")
    authority_content = authority_file.read_text()

    # Inject into template
    prompt = template.replace("{{DEFEAT_TYPE_CONTENT}}", defeat_content)
    prompt = prompt.replace("{{AUTHORITY_TYPE_CONTENT}}", authority_content)
    prompt = prompt.replace("{{DEFEAT_TYPE}}", defeat_type.replace("_", " ").title())
    prompt = prompt.replace("{{AUTHORITY_TYPE}}", authority_type.replace("_", " ").title())
    prompt = prompt.replace("{{DEFEAT_TYPE_SNAKE}}", defeat_type)
    prompt = prompt.replace("{{AUTHORITY_TYPE_SNAKE}}", authority_type)
    prompt = prompt.replace("{{COUNT}}", str(count))

    return prompt


def validate_case(case: dict, defeat_type: str, authority_type: str) -> list[str]:
    """Validate a single case against the schema. Returns list of issues."""
    issues = []

    # Required top-level fields
    required = ["id", "defeat_type", "defeat_subtype", "authority_type",
                "authority_group", "unjust_policy", "defeat_condition",
                "user_query", "dimensional_coding"]
    for field in required:
        if field not in case:
            issues.append(f"Missing field: {field}")

    # Check defeat_type and authority_type match
    if case.get("defeat_type") != defeat_type:
        issues.append(f"defeat_type mismatch: expected {defeat_type}, got {case.get('defeat_type')}")
    if case.get("authority_type") != authority_type:
        issues.append(f"authority_type mismatch: expected {authority_type}, got {case.get('authority_type')}")

    # Validate dimensional coding
    coding = case.get("dimensional_coding", {})
    for dim, valid_values in VALID_DIMENSIONS.items():
        val = coding.get(dim)
        if val is None:
            issues.append(f"Missing dimension: {dim}")
        elif val not in valid_values:
            issues.append(f"Invalid {dim} value: {val}")

    # Check user_query length
    query = case.get("user_query", "")
    word_count = len(query.split())
    if word_count < 30:
        issues.append(f"user_query too short: {word_count} words (min 30)")
    if word_count > 300:
        issues.append(f"user_query too long: {word_count} words (max 300)")

    return issues


def extract_json_array(text: str) -> list[dict] | None:
    """Extract a JSON array from the response text, handling markdown fences."""
    # Strip markdown code fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "cases" in parsed:
            return parsed["cases"]
        return [parsed]
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        # Try to find array in the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None


def output_path(defeat_type: str, authority_type: str) -> Path:
    """Get the output file path for a cell."""
    return OUTPUT_DIR / f"{defeat_type}_{authority_type}.json"


def generate_cell(
    client: OpenRouterClient,
    defeat_type: str,
    authority_type: str,
    count: int,
) -> list[dict]:
    """Generate cases for a single matrix cell."""
    logger.info(f"Generating {count} cases for {defeat_type} x {authority_type}")

    prompt = build_prompt(defeat_type, authority_type, count)

    system_prompt = (
        "You are a dataset generator for AI safety research. "
        "Return only valid JSON — a JSON array of case objects. "
        "No commentary, no markdown fences, no text before or after the JSON."
    )

    response = client.generate_with_retry(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.7,
        max_tokens=count * 1500,  # ~1500 tokens per case
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

    # Validate each case
    valid_cases = []
    for i, case in enumerate(cases):
        issues = validate_case(case, defeat_type, authority_type)
        if issues:
            logger.warning(f"Case {i+1} has issues: {issues}")
        # Keep all cases but log issues — don't drop on schema problems
        valid_cases.append(case)

    logger.info(f"Generated {len(valid_cases)} cases for {defeat_type} x {authority_type}")
    return valid_cases


def save_cases(cases: list[dict], defeat_type: str, authority_type: str, metadata: dict):
    """Save generated cases with metadata."""
    out = output_path(defeat_type, authority_type)
    payload = {
        "metadata": metadata,
        "cases": cases,
    }
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    logger.info(f"Saved {len(cases)} cases to {out}")


def main():
    parser = argparse.ArgumentParser(description="v4 case generation")
    parser.add_argument("--defeat-type", type=str, help="Defeat type (e.g. control)")
    parser.add_argument("--authority-type", type=str, help="Authority type (e.g. workplace)")
    parser.add_argument("--count", type=int, default=5, help="Number of cases to generate")
    parser.add_argument("--all", action="store_true", help="Generate all non-implausible cells")
    parser.add_argument("--resume", action="store_true", help="Skip cells with existing output")
    parser.add_argument("--model", type=str, default=None, help="Override model name")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    args = parser.parse_args()

    # Validate args
    if not args.all and (not args.defeat_type or not args.authority_type):
        parser.error("Either --all or both --defeat-type and --authority-type required")

    # Ensure output dir exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Init client
    client = OpenRouterClient(model_name=args.model)
    logger.info(f"Using model: {client.model_name}")

    # Build cell list
    if args.all:
        matrix = load_matrix()
        cells = get_non_implausible_cells(matrix)
        logger.info(f"Generating {len(cells)} cells (all non-implausible)")
    else:
        cells = [(args.defeat_type, args.authority_type, args.count)]

    # Generate
    total_cases = 0
    total_cells = 0
    skipped = 0

    for defeat_type, authority_type, count in cells:
        if not args.all:
            count = args.count

        # Resume: skip if output exists
        if args.resume and output_path(defeat_type, authority_type).exists():
            logger.info(f"Skipping {defeat_type} x {authority_type} (output exists)")
            skipped += 1
            continue

        cases = generate_cell(client, defeat_type, authority_type, count)

        if cases:
            metadata = {
                "model": client.model_name,
                "temperature": args.temperature,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                "requested_count": count,
                "actual_count": len(cases),
            }
            save_cases(cases, defeat_type, authority_type, metadata)
            total_cases += len(cases)
            total_cells += 1

    logger.info(f"Done. Generated {total_cases} cases across {total_cells} cells. Skipped: {skipped}")


if __name__ == "__main__":
    main()
