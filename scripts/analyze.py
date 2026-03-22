#!/usr/bin/env python3
"""
Full analysis of Compliance Overspill v5 LLM-judge evaluations.

v5 taxonomy: response_type (helps/hard_refusal/deflects) + acknowledges_defeat (yes/no).

Reads from data/4_evaluated/*.json and data/1_generated/*.json (case context with
dimensional coding), producing summary tables across response types, defeat types,
gate effects, and secondary dimensional breakdowns.

Usage:
    python3 scripts/analyze.py

Output:
    - Prints tables to stdout
    - Writes markdown report to output/analysis.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT = Path(__file__).resolve().parent.parent
EVAL_DIR = PROJECT / "data" / "4_evaluated"
GENERATED_DIR = PROJECT / "data" / "1_generated"
GATED_DIR = PROJECT / "logs" / "gate_verdicts"
OUTPUT_DIR = PROJECT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "analysis.md"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL_ORDER = [
    "claude-opus-4-6",
    "gpt-5-2",
    "gemini-3-1-pro",
    "deepseek-v3-2",
    "llama-4-maverick",
]

DEFEAT_ORDER = [
    "application_defeat",
    "content_defeat",
    "exception_justified",
    "illegitimate_authority",
    "control",
]

# v5 taxonomy
RESPONSE_TYPE_ORDER = ["helps", "hard_refusal", "deflects"]
ACKNOWLEDGES_DEFEAT_ORDER = ["yes", "no"]

# Secondary dimensions
LEGALITY_ORDER = [
    "private_rule",
    "technically_illegal_trivial",
    "illegal_but_unjust",
    "clearly_illegal_enforced",
    "contract",
]
HARM_ORDER = ["none", "diffuse", "concrete_minor", "concrete_significant"]
STAKES_ORDER = ["trivial", "moderate", "severe", "existential"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pct(n: int, total: int) -> str:
    """Format a count as 'XX.X% (n/total)'."""
    if total == 0:
        return "- (0)"
    return f"{n / total * 100:.1f}% ({n}/{total})"


def pct_short(n: int, total: int) -> str:
    """Format a count as 'XX.X%' only."""
    if total == 0:
        return "-"
    return f"{n / total * 100:.1f}%"


def make_table(headers: list[str], rows: list[list[str]], align: list[str] | None = None) -> str:
    """Build a markdown table string."""
    if align is None:
        align = ["l"] * len(headers)
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells: list) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = col_widths[i] if i < len(col_widths) else len(str(cell))
            s = str(cell)
            if i < len(align) and align[i] == "r":
                parts.append(s.rjust(w))
            else:
                parts.append(s.ljust(w))
        return "| " + " | ".join(parts) + " |"

    sep_parts = []
    for i, w in enumerate(col_widths):
        a = align[i] if i < len(align) else "l"
        if a == "r":
            sep_parts.append("-" * (w - 1) + ":")
        elif a == "c":
            sep_parts.append(":" + "-" * (w - 2) + ":")
        else:
            sep_parts.append("-" * w)
    sep = "| " + " | ".join(sep_parts) + " |"

    lines = [fmt_row(headers), sep]
    for row in rows:
        lines.append(fmt_row(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_case_contexts() -> dict[str, dict]:
    """Load all generated cases, keyed by case_id."""
    cases: dict[str, dict] = {}
    for fp in sorted(GENERATED_DIR.glob("*.json")):
        try:
            with open(fp) as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            print(f"  WARNING: Skipping malformed generated file {fp.name}: {e}", file=sys.stderr)
            continue
        meta = data.get("metadata", {})
        for c in data.get("cases", []):
            cid = c.get("id")
            if cid:
                c["_file_defeat_type"] = meta.get("defeat_type", "")
                c["_file_authority_type"] = meta.get("authority_type", "")
                cases[cid] = c
    return cases


def load_gate_flags() -> dict[str, dict]:
    """Load gate flags directly from logs/gate_verdicts/ (authoritative source)."""
    flags: dict[str, dict] = {}

    for fp in sorted(GATED_DIR.glob("df_*.json")):
        try:
            with open(fp) as fh:
                data = json.load(fh)
        except json.JSONDecodeError:
            continue
        for r in data:
            cid = r.get("case_id", "")
            if not cid or r.get("error"):
                continue
            if cid not in flags:
                flags[cid] = {}
            flags[cid]["df_pass"] = r.get("pass")
            flags[cid]["df_escape_route"] = r.get("escape_route")

    for fp in sorted(GATED_DIR.glob("du_*.json")):
        try:
            with open(fp) as fh:
                data = json.load(fh)
        except json.JSONDecodeError:
            continue
        for r in data:
            cid = r.get("case_id", "")
            if not cid or r.get("error"):
                continue
            if cid not in flags:
                flags[cid] = {}
            flags[cid]["du_flagged"] = r.get("flagged")
            flags[cid]["du_category"] = r.get("category")

    return flags


def load_all_evals(cases: dict[str, dict], gate_flags: dict[str, dict]) -> tuple[list[dict], int, list[str]]:
    """Load all evaluation files and merge with case context and gate flags."""
    records: list[dict] = []
    missing_cases: list[str] = []
    file_count = 0

    for fp in sorted(EVAL_DIR.glob("*.json")):
        file_count += 1
        try:
            with open(fp) as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            print(f"  WARNING: Skipping malformed file {fp.name}: {e}", file=sys.stderr)
            continue

        meta = data.get("metadata", {})
        model_slug = meta.get("evaluated_model", "")

        # Parse defeat_type and authority_type from source_file name
        source = meta.get("source_file", "")
        suffix = source
        for m in MODEL_ORDER:
            if suffix.startswith(m + "_"):
                suffix = suffix[len(m) + 1:]
                break

        file_defeat_type = ""
        file_authority_type = ""
        for dt in DEFEAT_ORDER:
            if suffix.startswith(dt + "_"):
                file_defeat_type = dt
                file_authority_type = suffix[len(dt) + 1:]
                break
            elif suffix == dt:
                file_defeat_type = dt
                break

        if not file_defeat_type and source:
            print(f"  WARNING: Could not parse defeat_type from source_file: {source!r}", file=sys.stderr)

        for ev in data.get("evaluations", []):
            case_id = ev.get("case_id", "")
            evaluation = ev.get("evaluation", {})
            gf = gate_flags.get(case_id, {})
            case = cases.get(case_id, {})
            dim = case.get("dimensional_coding", {})
            defeat_type = case.get("defeat_type", "") or file_defeat_type
            authority_type = case.get("authority_type", "") or file_authority_type

            records.append({
                # Identity
                "model": model_slug,
                "case_id": case_id,
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                "authority_group": case.get("authority_group", ""),

                # v5 judge evaluation
                "response_type": evaluation.get("response_type", "deflects"),
                "acknowledges_defeat": evaluation.get("acknowledges_defeat", "no"),

                # Gate flags (from logs/gate_verdicts/)
                "df_pass": gf.get("df_pass"),
                "du_flagged": gf.get("du_flagged"),
                "du_category": gf.get("du_category"),

                # Dimensional coding (from generated cases)
                "legality": dim.get("legality", ""),
                "harm_to_others": dim.get("harm_to_others", ""),
                "stakes_if_caught": dim.get("stakes_if_caught", ""),
                "kind_of_rule": dim.get("kind_of_rule", ""),
                "compliance_ecology": dim.get("compliance_ecology", ""),
                "user_positionality": dim.get("user_positionality", ""),
                "evasion_type": dim.get("evasion_type", ""),

                # Source
                "_source_file": fp.name,
            })

            if case_id and case_id not in cases:
                missing_cases.append(case_id)

    return records, file_count, missing_cases


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def run_analysis():
    print("Loading data...")
    cases = load_case_contexts()
    gflags = load_gate_flags()
    records, file_count, missing_cases = load_all_evals(cases, gflags)

    print(f"  Loaded {len(cases)} cases from {len(list(GENERATED_DIR.glob('*.json')))} generated files")
    print(f"  Loaded {len(gflags)} gate flag entries from logs/gate_verdicts/")
    print(f"  Loaded {len(records)} evaluations from {file_count} eval files")
    if missing_cases:
        unique_missing = set(missing_cases)
        print(f"  WARNING: {len(unique_missing)} case IDs not found in generated data")

    out_lines: list[str] = []

    def emit(s: str = ""):
        print(s)
        out_lines.append(s)

    emit("# Compliance Overspill v5 — Full Analysis")
    emit()
    emit("*v5 taxonomy: response_type (helps / hard_refusal / deflects) + acknowledges_defeat (yes / no).*")
    emit()

    # -----------------------------------------------------------------------
    # Summary statistics
    # -----------------------------------------------------------------------
    emit("## Summary Statistics")
    emit()

    models_found = sorted(set(r["model"] for r in records))
    defeats_found = sorted(set(r["defeat_type"] for r in records))
    authorities_found = sorted(set(r["authority_type"] for r in records))

    emit(f"- **Total evaluations**: {len(records)}")
    emit(f"- **Eval files loaded**: {file_count}")
    emit(f"- **Cases in corpus**: {len(cases)}")
    emit(f"- **Models**: {len(models_found)} — {', '.join(models_found)}")
    emit(f"- **Defeat types**: {len(defeats_found)} — {', '.join(defeats_found)}")
    emit(f"- **Authority types**: {len(authorities_found)}")

    # Response type distribution
    for rt in RESPONSE_TYPE_ORDER:
        cnt = sum(1 for r in records if r["response_type"] == rt)
        emit(f"- **{rt}**: {cnt} ({pct_short(cnt, len(records))})")
    emit()

    # Per-model N counts
    emit("### Evaluations per Model")
    emit()
    headers = ["Model", "N", "% of total"]
    rows = []
    for model in MODEL_ORDER:
        n = sum(1 for r in records if r["model"] == model)
        rows.append([model, str(n), pct_short(n, len(records))])
    emit(make_table(headers, rows))
    emit()

    # Coverage: model x defeat type
    emit("### Coverage: Model x Defeat Type (eval count)")
    emit()
    headers = ["Model"] + [dt.replace("_", " ") for dt in DEFEAT_ORDER] + ["Total"]
    rows = []
    for model in MODEL_ORDER:
        row = [model]
        total = 0
        for dt in DEFEAT_ORDER:
            n = sum(1 for r in records if r["model"] == model and r["defeat_type"] == dt)
            row.append(str(n))
            total += n
        row.append(str(total))
        rows.append(row)
    row = ["**ALL**"]
    grand = 0
    for dt in DEFEAT_ORDER:
        n = sum(1 for r in records if r["defeat_type"] == dt)
        row.append(str(n))
        grand += n
    row.append(str(grand))
    rows.append(row)
    emit(make_table(headers, rows))
    emit()

    # -----------------------------------------------------------------------
    # Table 1: Response Type by Model
    # -----------------------------------------------------------------------
    emit("## Table 1: Response Type by Model")
    emit()
    emit("*Distribution of helps / hard_refusal / deflects per model.*")
    emit()

    headers = ["Model", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for model in MODEL_ORDER:
        subset = [r for r in records if r["model"] == model]
        n = len(subset)
        if n == 0:
            continue
        row = [model, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)

    n = len(records)
    row = ["**ALL**", str(n)]
    for rt in RESPONSE_TYPE_ORDER:
        cnt = sum(1 for r in records if r["response_type"] == rt)
        row.append(pct(cnt, n))
    rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 2: Response Type by Defeat Type
    # -----------------------------------------------------------------------
    emit("## Table 2: Response Type by Defeat Type")
    emit()

    headers = ["Defeat Type", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for dt in DEFEAT_ORDER:
        subset = [r for r in records if r["defeat_type"] == dt]
        n = len(subset)
        if n == 0:
            continue
        row = [dt, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 3: Response Type by Model x Defeat Type (helps rate)
    # -----------------------------------------------------------------------
    emit("## Table 3: Helps Rate by Model x Defeat Type")
    emit()
    emit("*response_type=helps rate in each model x defeat_type cell.*")
    emit()

    headers = ["Model"] + [dt.replace("_", " ") for dt in DEFEAT_ORDER]
    rows = []
    for model in MODEL_ORDER:
        row = [model]
        for dt in DEFEAT_ORDER:
            subset = [r for r in records if r["model"] == model and r["defeat_type"] == dt]
            n = len(subset)
            if n == 0:
                row.append("--")
                continue
            cnt = sum(1 for r in subset if r["response_type"] == "helps")
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows))
    emit()

    # -----------------------------------------------------------------------
    # Table 4: Hard Refusal Rate by Model x Defeat Type
    # -----------------------------------------------------------------------
    emit("## Table 4: Hard Refusal Rate by Model x Defeat Type")
    emit()

    headers = ["Model"] + [dt.replace("_", " ") for dt in DEFEAT_ORDER]
    rows = []
    for model in MODEL_ORDER:
        row = [model]
        for dt in DEFEAT_ORDER:
            subset = [r for r in records if r["model"] == model and r["defeat_type"] == dt]
            n = len(subset)
            if n == 0:
                row.append("--")
                continue
            cnt = sum(1 for r in subset if r["response_type"] == "hard_refusal")
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows))
    emit()

    # -----------------------------------------------------------------------
    # Table 5: Control Cases
    # -----------------------------------------------------------------------
    emit("## Table 5: Control Cases (Legitimate Rule)")
    emit()
    emit("*How models respond when the rule IS legitimate — helping here is a false positive.*")
    emit()

    control = [r for r in records if r["defeat_type"] == "control"]
    headers = ["Model", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for model in MODEL_ORDER:
        subset = [r for r in control if r["model"] == model]
        n = len(subset)
        if n == 0:
            continue
        row = [model, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)

    n = len(control)
    row = ["**ALL**", str(n)]
    for rt in RESPONSE_TYPE_ORDER:
        cnt = sum(1 for r in control if r["response_type"] == rt)
        row.append(pct(cnt, n))
    rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 6: Acknowledges Defeat by Model (non-control)
    # -----------------------------------------------------------------------
    emit("## Table 6: Acknowledges Defeat by Model (non-control)")
    emit()
    emit("*Does the model engage with whether the policy deserves compliance?*")
    emit()

    non_control = [r for r in records if r["defeat_type"] != "control"]
    headers = ["Model", "N"] + ACKNOWLEDGES_DEFEAT_ORDER
    align = ["l", "r"] + ["r"] * len(ACKNOWLEDGES_DEFEAT_ORDER)
    rows = []
    for model in MODEL_ORDER:
        subset = [r for r in non_control if r["model"] == model]
        n = len(subset)
        if n == 0:
            continue
        row = [model, str(n)]
        for val in ACKNOWLEDGES_DEFEAT_ORDER:
            cnt = sum(1 for r in subset if r["acknowledges_defeat"] == val)
            row.append(pct(cnt, n))
        rows.append(row)

    n = len(non_control)
    row = ["**ALL**", str(n)]
    for val in ACKNOWLEDGES_DEFEAT_ORDER:
        cnt = sum(1 for r in non_control if r["acknowledges_defeat"] == val)
        row.append(pct(cnt, n))
    rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 7: Acknowledges Defeat by Defeat Type
    # -----------------------------------------------------------------------
    emit("## Table 7: Acknowledges Defeat by Defeat Type (non-control)")
    emit()

    headers = ["Defeat Type", "N"] + ACKNOWLEDGES_DEFEAT_ORDER
    align = ["l", "r"] + ["r"] * len(ACKNOWLEDGES_DEFEAT_ORDER)
    rows = []
    for dt in [d for d in DEFEAT_ORDER if d != "control"]:
        subset = [r for r in non_control if r["defeat_type"] == dt]
        n = len(subset)
        if n == 0:
            continue
        row = [dt, str(n)]
        for val in ACKNOWLEDGES_DEFEAT_ORDER:
            cnt = sum(1 for r in subset if r["acknowledges_defeat"] == val)
            row.append(pct(cnt, n))
        rows.append(row)

    n = len(non_control)
    row = ["**ALL (non-ctrl)**", str(n)]
    for val in ACKNOWLEDGES_DEFEAT_ORDER:
        cnt = sum(1 for r in non_control if r["acknowledges_defeat"] == val)
        row.append(pct(cnt, n))
    rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 8: Acknowledges Defeat x Response Type (cross-tab)
    # -----------------------------------------------------------------------
    emit("## Table 8: Acknowledges Defeat x Response Type (non-control)")
    emit()
    emit("*How acknowledges_defeat correlates with response type.*")
    emit()

    headers = ["acknowledges_defeat", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for ad in ACKNOWLEDGES_DEFEAT_ORDER:
        subset = [r for r in non_control if r["acknowledges_defeat"] == ad]
        n = len(subset)
        if n == 0:
            continue
        row = [ad, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 9: Dual-Use Flag Effect
    # -----------------------------------------------------------------------
    emit("## Table 9: Effect of Dual-Use Flag on Response Type")
    emit()
    emit("*Response type distribution for dual-use flagged vs. not-flagged cases, per model.*")
    emit()

    headers = ["Model", "DU Flagged (N)", "Flagged helps%", "Flagged hard_ref%", "Not Flagged (N)", "Not Flagged helps%", "Not Flagged hard_ref%"]
    align = ["l", "r", "r", "r", "r", "r", "r"]
    rows = []
    for model in MODEL_ORDER:
        subset = [r for r in records if r["model"] == model]
        flagged = [r for r in subset if r["du_flagged"] is True]
        not_flagged = [r for r in subset if r["du_flagged"] is False]
        nf = len(flagged)
        nnf = len(not_flagged)
        if nf == 0 and nnf == 0:
            continue
        helps_f = sum(1 for r in flagged if r["response_type"] == "helps")
        hr_f = sum(1 for r in flagged if r["response_type"] == "hard_refusal")
        helps_nf = sum(1 for r in not_flagged if r["response_type"] == "helps")
        hr_nf = sum(1 for r in not_flagged if r["response_type"] == "hard_refusal")
        rows.append([
            model, str(nf), pct_short(helps_f, nf), pct_short(hr_f, nf),
            str(nnf), pct_short(helps_nf, nnf), pct_short(hr_nf, nnf),
        ])
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 10: Decision-Forcing Gate Effect
    # -----------------------------------------------------------------------
    emit("## Table 10: Effect of Decision-Forcing Gate on Response Type")
    emit()

    headers = ["Model", "DF Pass (N)", "Pass helps%", "Pass hard_ref%", "DF Fail (N)", "Fail helps%", "Fail hard_ref%"]
    align = ["l", "r", "r", "r", "r", "r", "r"]
    rows = []
    for model in MODEL_ORDER:
        subset = [r for r in records if r["model"] == model]
        df_pass = [r for r in subset if r["df_pass"] is True]
        df_fail = [r for r in subset if r["df_pass"] is False]
        np_ = len(df_pass)
        nf_ = len(df_fail)
        if np_ == 0 and nf_ == 0:
            continue
        helps_p = sum(1 for r in df_pass if r["response_type"] == "helps")
        hr_p = sum(1 for r in df_pass if r["response_type"] == "hard_refusal")
        helps_f = sum(1 for r in df_fail if r["response_type"] == "helps")
        hr_f = sum(1 for r in df_fail if r["response_type"] == "hard_refusal")
        rows.append([
            model, str(np_), pct_short(helps_p, np_), pct_short(hr_p, np_),
            str(nf_), pct_short(helps_f, nf_), pct_short(hr_f, nf_),
        ])
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 11: Response Type by Legality
    # -----------------------------------------------------------------------
    emit("## Table 11: Response Type by Legality of Evasion")
    emit()

    headers = ["Legality", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for leg in LEGALITY_ORDER:
        subset = [r for r in records if r["legality"] == leg]
        n = len(subset)
        if n == 0:
            continue
        row = [leg, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 12: Response Type by Harm-to-Others
    # -----------------------------------------------------------------------
    emit("## Table 12: Response Type by Harm-to-Others")
    emit()

    headers = ["Harm to Others", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for harm in HARM_ORDER:
        subset = [r for r in records if r["harm_to_others"] == harm]
        n = len(subset)
        if n == 0:
            continue
        row = [harm, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Table 13: Response Type by Stakes
    # -----------------------------------------------------------------------
    emit("## Table 13: Response Type by Stakes (Consequences of Getting Caught)")
    emit()

    headers = ["Stakes", "N"] + RESPONSE_TYPE_ORDER
    align = ["l", "r"] + ["r"] * len(RESPONSE_TYPE_ORDER)
    rows = []
    for stake in STAKES_ORDER:
        subset = [r for r in records if r["stakes_if_caught"] == stake]
        n = len(subset)
        if n == 0:
            continue
        row = [stake, str(n)]
        for rt in RESPONSE_TYPE_ORDER:
            cnt = sum(1 for r in subset if r["response_type"] == rt)
            row.append(pct(cnt, n))
        rows.append(row)
    emit(make_table(headers, rows, align))
    emit()

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    with open(OUTPUT_FILE, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")
    print(f"\nReport written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_analysis()
