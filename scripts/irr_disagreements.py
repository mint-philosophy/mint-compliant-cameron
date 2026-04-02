#!/usr/bin/env python3
"""
Disagreement analysis for the Compliance Overspill v4 project.

Identifies all cases where raters disagree across both validation phases,
groups disagreements by pattern, and outputs a structured markdown report.

Usage:
    python3 scripts/irr_disagreements.py [--output FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "human_validation"

EVAL_REVIEWS = DATA_DIR / "eval_reviews.json"
EVAL_SAMPLE_META = DATA_DIR / "eval_sample_300_meta.json"
PHASE1_REVIEWS = DATA_DIR / "reviews.json"

# ---------------------------------------------------------------------------
# Data loading (same as irr_stats.py)
# ---------------------------------------------------------------------------

def load_phase1() -> Dict[str, Dict]:
    """Load Phase 1 reviews with full metadata."""
    with open(PHASE1_REVIEWS) as f:
        return json.load(f)


def load_phase2_human() -> Dict[str, Dict]:
    """Load Phase 2 human reviews (raw format)."""
    with open(EVAL_REVIEWS) as f:
        return json.load(f)


def load_phase2_llm() -> Dict[str, Dict[str, str]]:
    """Load LLM judge labels. Returns {review_key: {dimension: value, ...}}."""
    with open(EVAL_SAMPLE_META) as f:
        raw = json.load(f)
    result = {}
    for item in raw["sample_items"]:
        key = item["review_key"]
        ih = item["independent_harm"]
        if isinstance(ih, bool):
            ih = "yes" if ih else "no"
        result[key] = {
            "response_type": item["response_type"],
            "engages_with_defeat": item["engages_with_defeat"],
            "independent_harm": str(ih),
            "defeat_type": item.get("defeat_type", ""),
            "authority_type": item.get("authority_type", ""),
            "model_slug": item.get("model_slug", ""),
            "case_id": item.get("case_id", ""),
        }
    return result


def parse_review_key(key: str) -> Tuple[str, str, str]:
    """
    Parse a review key like 'seed_content_defeat_landlord_35__grok-4-fast'
    into (case_id, defeat_type, authority_type).
    Falls back to extracting from the key structure.
    """
    parts = key.split("__")
    case_id = parts[0] if len(parts) >= 1 else key
    model_slug = parts[1] if len(parts) >= 2 else "unknown"

    # Extract defeat_type and authority_type from case_id
    # Format: seed_{defeat_type}_{authority_type}_{number}
    # But defeat_type and authority_type can contain underscores
    # Known defeat types (from data):
    defeat_types = [
        "application_defeat",
        "content_defeat",
        "illegitimate_authority",
        "control",
        "exception_justified",
    ]

    defeat_type = ""
    authority_type = ""
    case_without_seed = case_id[len("seed_"):] if case_id.startswith("seed_") else case_id

    for dt in defeat_types:
        if case_without_seed.startswith(dt + "_"):
            defeat_type = dt
            remainder = case_without_seed[len(dt) + 1:]
            # remainder is like "landlord_35" -> authority_type = landlord
            # or "algorithmic_intermediary_12" -> authority_type = algorithmic_intermediary
            # Strip the trailing number
            parts_r = remainder.rsplit("_", 1)
            if len(parts_r) == 2 and parts_r[1].isdigit():
                authority_type = parts_r[0]
            else:
                authority_type = remainder
            break

    return case_id, defeat_type, authority_type


# ---------------------------------------------------------------------------
# Phase 1 disagreement analysis
# ---------------------------------------------------------------------------

def phase1_disagreements(phase1: Dict) -> List[Dict]:
    """Find all Phase 1 disagreements between Cameron and Lorenzo."""
    disagreements = []
    for case_id, entry in sorted(phase1.items()):
        if "cameron" not in entry or "lorenzo" not in entry:
            continue
        cam_verdict = entry["cameron"]
        lor_verdict = entry["lorenzo"]
        if cam_verdict != lor_verdict:
            _, defeat_type, authority_type = parse_review_key(case_id)
            disagreements.append({
                "case_id": case_id,
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                "cameron_verdict": cam_verdict,
                "lorenzo_verdict": lor_verdict,
                "cameron_note": entry.get("cameron_note", ""),
                "lorenzo_note": entry.get("lorenzo_note", ""),
                "cameron_confound": entry.get("cameron_confound", False),
                "lorenzo_confound": entry.get("lorenzo_confound", False),
            })
    return disagreements


# ---------------------------------------------------------------------------
# Phase 2 disagreement analysis
# ---------------------------------------------------------------------------

DIMENSIONS = ["response_type", "engages_with_defeat", "independent_harm"]


def phase2_disagreements(
    human: Dict, llm: Dict
) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Find all Phase 2 disagreements, organized by dimension and rater pair.

    Returns:
        {dimension: {pair_label: [disagreement_dicts]}}
    """
    result = {}

    for dim in DIMENSIONS:
        dim_disagreements = defaultdict(list)

        # Collect all review keys
        all_keys = set(human.keys()) | set(llm.keys())

        for review_key in sorted(all_keys):
            labels = {}

            # Get human labels
            if review_key in human:
                entry = human[review_key]
                for reviewer in ["cameron", "lorenzo"]:
                    if reviewer in entry:
                        r = entry[reviewer]
                        field = f"human_{dim}"
                        if field in r:
                            labels[reviewer] = r[field]

            # Get LLM label
            if review_key in llm:
                labels["llm"] = llm[review_key][dim]

            # Extract metadata
            case_id, defeat_type, authority_type = parse_review_key(review_key)

            # Use LLM metadata if available
            if review_key in llm:
                defeat_type = llm[review_key].get("defeat_type", defeat_type)
                authority_type = llm[review_key].get("authority_type", authority_type)

            # Get human notes
            cam_notes = ""
            lor_notes = ""
            if review_key in human:
                if "cameron" in human[review_key]:
                    cam_notes = human[review_key]["cameron"].get("human_notes", "")
                if "lorenzo" in human[review_key]:
                    lor_notes = human[review_key]["lorenzo"].get("human_notes", "")

            # Check each rater pair for disagreement
            pairs = [
                ("cameron", "lorenzo"),
                ("cameron", "llm"),
                ("lorenzo", "llm"),
            ]

            for rater_a, rater_b in pairs:
                if rater_a in labels and rater_b in labels:
                    if labels[rater_a] != labels[rater_b]:
                        pair_label = f"{rater_a}_vs_{rater_b}"
                        pattern = f"{labels[rater_a]} vs {labels[rater_b]}"
                        dim_disagreements[pair_label].append({
                            "review_key": review_key,
                            "case_id": case_id,
                            "defeat_type": defeat_type,
                            "authority_type": authority_type,
                            "rater_a_label": labels[rater_a],
                            "rater_b_label": labels[rater_b],
                            "pattern": pattern,
                            "cameron_notes": cam_notes,
                            "lorenzo_notes": lor_notes,
                        })

        result[dim] = dict(dim_disagreements)

    return result


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_report(
    p1_disagree: List[Dict],
    p2_disagree: Dict[str, Dict[str, List[Dict]]],
    phase1_total: int,
    phase2_totals: Dict[str, Dict[str, int]],
) -> str:
    """Generate a structured markdown disagreement report."""
    lines = []

    lines.append("# Disagreement Analysis Report")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("**Data files**:")
    lines.append(f"- Phase 1: `{PHASE1_REVIEWS}`")
    lines.append(f"- Phase 2 human: `{EVAL_REVIEWS}`")
    lines.append(f"- Phase 2 LLM: `{EVAL_SAMPLE_META}`")
    lines.append("")

    # -----------------------------------------------------------------------
    # Phase 1
    # -----------------------------------------------------------------------
    lines.append("## Phase 1: Case Quality Validation")
    lines.append("")
    n_disagree = len(p1_disagree)
    lines.append(
        f"**{n_disagree} disagreements** out of {phase1_total} overlapping cases "
        f"({n_disagree / phase1_total * 100:.1f}% disagreement rate)" if phase1_total > 0
        else f"**{n_disagree} disagreements** (no overlapping cases)"
    )
    lines.append("")

    if p1_disagree:
        # Group by pattern
        pattern_groups = defaultdict(list)
        for d in p1_disagree:
            pattern = f"Cameron={d['cameron_verdict']}, Lorenzo={d['lorenzo_verdict']}"
            pattern_groups[pattern].append(d)

        for pattern, cases in sorted(pattern_groups.items()):
            lines.append(f"### Pattern: {pattern} ({len(cases)} cases)")
            lines.append("")
            for d in cases:
                lines.append(f"**{d['case_id']}**")
                lines.append(f"- Defeat type: {d['defeat_type']}")
                lines.append(f"- Authority type: {d['authority_type']}")
                if d["cameron_note"]:
                    lines.append(f"- Cameron note: {d['cameron_note']}")
                if d["lorenzo_note"]:
                    lines.append(f"- Lorenzo note: {d['lorenzo_note']}")
                if d["cameron_confound"]:
                    lines.append(f"- Cameron flagged confound: yes")
                if d["lorenzo_confound"]:
                    lines.append(f"- Lorenzo flagged confound: yes")
                lines.append("")

    # -----------------------------------------------------------------------
    # Phase 2
    # -----------------------------------------------------------------------
    lines.append("## Phase 2: Response Coding")
    lines.append("")

    dim_labels = {
        "response_type": "Response Type",
        "engages_with_defeat": "Engages with Defeat",
        "independent_harm": "Independent Harm",
    }

    pair_labels = {
        "cameron_vs_lorenzo": "Cameron vs Lorenzo",
        "cameron_vs_llm": "Cameron vs LLM Judge",
        "lorenzo_vs_llm": "Lorenzo vs LLM Judge",
    }

    for dim in DIMENSIONS:
        lines.append(f"### {dim_labels[dim]}")
        lines.append("")

        dim_data = p2_disagree.get(dim, {})
        if not dim_data:
            lines.append("No disagreements found.")
            lines.append("")
            continue

        for pair_key in ["cameron_vs_lorenzo", "cameron_vs_llm", "lorenzo_vs_llm"]:
            if pair_key not in dim_data:
                continue

            cases = dim_data[pair_key]
            total = phase2_totals.get(dim, {}).get(pair_key, 0)
            rate_str = f" ({len(cases) / total * 100:.1f}%)" if total > 0 else ""

            lines.append(f"#### {pair_labels[pair_key]}: {len(cases)} disagreements{rate_str}")
            lines.append("")

            # Group by pattern
            pattern_groups = defaultdict(list)
            for d in cases:
                pattern_groups[d["pattern"]].append(d)

            for pattern, group in sorted(pattern_groups.items(), key=lambda x: -len(x[1])):
                lines.append(f"**Pattern: {pattern}** ({len(group)} cases)")
                lines.append("")

                # Summary table
                lines.append("| Case | Defeat | Authority | Cameron Notes | Lorenzo Notes |")
                lines.append("|------|--------|-----------|---------------|---------------|")

                for d in group:
                    cam_notes = d["cameron_notes"].replace("|", "\\|").replace("\n", " ") if d["cameron_notes"] else ""
                    lor_notes = d["lorenzo_notes"].replace("|", "\\|").replace("\n", " ") if d["lorenzo_notes"] else ""
                    # Truncate long notes for table readability
                    if len(cam_notes) > 80:
                        cam_notes = cam_notes[:77] + "..."
                    if len(lor_notes) > 80:
                        lor_notes = lor_notes[:77] + "..."
                    lines.append(
                        f"| `{d['review_key'][-50:]}` | {d['defeat_type']} | "
                        f"{d['authority_type']} | {cam_notes} | {lor_notes} |"
                    )

                lines.append("")

        lines.append("")

    # -----------------------------------------------------------------------
    # Summary statistics
    # -----------------------------------------------------------------------
    lines.append("## Summary")
    lines.append("")
    lines.append("### Disagreement counts by dimension and pair")
    lines.append("")
    lines.append("| Dimension | Cam-Lor | Cam-LLM | Lor-LLM |")
    lines.append("|-----------|---------|---------|---------|")

    for dim in DIMENSIONS:
        dim_data = p2_disagree.get(dim, {})
        cam_lor = len(dim_data.get("cameron_vs_lorenzo", []))
        cam_llm = len(dim_data.get("cameron_vs_llm", []))
        lor_llm = len(dim_data.get("lorenzo_vs_llm", []))
        lines.append(f"| {dim_labels[dim]} | {cam_lor} | {cam_llm} | {lor_llm} |")

    lines.append("")

    # Pattern frequency analysis
    lines.append("### Most common disagreement patterns (Phase 2)")
    lines.append("")

    all_patterns = Counter()
    for dim in DIMENSIONS:
        dim_data = p2_disagree.get(dim, {})
        for pair_key, cases in dim_data.items():
            for d in cases:
                pattern_label = f"{dim_labels[dim]} / {pair_labels.get(pair_key, pair_key)}: {d['pattern']}"
                all_patterns[pattern_label] += 1

    for pattern, count in all_patterns.most_common(15):
        lines.append(f"- **{pattern}**: {count} cases")

    lines.append("")

    # Defeat-type breakdown for disagreements
    lines.append("### Disagreements by defeat type (all dimensions combined)")
    lines.append("")
    defeat_counts = Counter()
    total_by_defeat = Counter()
    for dim in DIMENSIONS:
        dim_data = p2_disagree.get(dim, {})
        for pair_key, cases in dim_data.items():
            for d in cases:
                defeat_counts[d["defeat_type"]] += 1

    for dt, count in defeat_counts.most_common():
        lines.append(f"- {dt}: {count}")

    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze interrater disagreements for Compliance Overspill v4"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (default: print to stdout)"
    )
    args = parser.parse_args()

    # Verify data files exist
    for path in [PHASE1_REVIEWS, EVAL_REVIEWS, EVAL_SAMPLE_META]:
        if not path.exists():
            print(f"ERROR: Data file not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Load data
    phase1_raw = load_phase1()
    phase2_human = load_phase2_human()
    phase2_llm = load_phase2_llm()

    # Phase 1 analysis
    p1_disagree = phase1_disagreements(phase1_raw)
    phase1_overlap = sum(
        1 for v in phase1_raw.values()
        if "cameron" in v and "lorenzo" in v
    )

    # Phase 2 analysis
    p2_disagree = phase2_disagreements(phase2_human, phase2_llm)

    # Compute totals for rate calculations
    phase2_totals = {}
    for dim in DIMENSIONS:
        dim_totals = {}
        # Count overlap per pair
        all_keys = set(phase2_human.keys()) | set(phase2_llm.keys())
        for pair_key, (rater_a, rater_b) in [
            ("cameron_vs_lorenzo", ("cameron", "lorenzo")),
            ("cameron_vs_llm", ("cameron", "llm")),
            ("lorenzo_vs_llm", ("lorenzo", "llm")),
        ]:
            count = 0
            for review_key in all_keys:
                has_a = False
                has_b = False
                if rater_a in ("cameron", "lorenzo"):
                    if review_key in phase2_human and rater_a in phase2_human[review_key]:
                        has_a = True
                elif rater_a == "llm":
                    if review_key in phase2_llm:
                        has_a = True
                if rater_b in ("cameron", "lorenzo"):
                    if review_key in phase2_human and rater_b in phase2_human[review_key]:
                        has_b = True
                elif rater_b == "llm":
                    if review_key in phase2_llm:
                        has_b = True
                if has_a and has_b:
                    count += 1
            dim_totals[pair_key] = count
        phase2_totals[dim] = dim_totals

    # Generate report
    report = generate_report(p1_disagree, p2_disagree, phase1_overlap, phase2_totals)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"Report written to {output_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
