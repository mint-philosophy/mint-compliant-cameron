#!/usr/bin/env python3
"""
Comprehensive analysis of compliance overspill v4 evaluation results.
Processes all 1,512 files in data/4_evaluated/ across 18 models.
Outputs: paper/full_evaluation_analysis.md
"""
from __future__ import annotations

import json
import os
import glob
from collections import defaultdict, Counter

DATA_DIR = "/Users/cameronpattison/Documents/Academic Documents/2025-6/playground/evading_unjust_policy/v4/data/4_evaluated/"
OUTPUT = "/Users/cameronpattison/Documents/Academic Documents/2025-6/playground/evading_unjust_policy/v4/data/5_analysis/full_evaluation_analysis.md"

# ── Load all data ──────────────────────────────────────────────────────────

records = []  # flat list of per-case records
file_metadata = []
null_evals = 0
total_evals = 0
eval_errors_total = 0
skipped_errors_total = 0
all_models_in_metadata = set()
empty_models = {}  # model -> file count with 0 evaluations

for fpath in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
    with open(fpath) as fh:
        data = json.load(fh)

    meta = data["metadata"]
    model = meta["evaluated_model"]
    source = meta["source_file"]
    eval_errors_total += meta.get("eval_errors", 0)
    skipped_errors_total += meta.get("skipped_errors", 0)
    file_metadata.append(meta)
    all_models_in_metadata.add(model)

    if len(data["evaluations"]) == 0:
        empty_models[model] = empty_models.get(model, 0) + 1

    # Parse defeat family from source_file
    # source_file = "model-name_defeat_type_authority_name"
    rest = source[len(model) + 1:]  # strip "model_"

    # Determine defeat_type and authority
    if rest.startswith("control_"):
        defeat_type = "control"
        authority = rest[len("control_"):]
    elif rest.startswith("application_defeat_"):
        defeat_type = "application_defeat"
        authority = rest[len("application_defeat_"):]
    elif rest.startswith("content_defeat_"):
        defeat_type = "content_defeat"
        authority = rest[len("content_defeat_"):]
    elif rest.startswith("exception_justified_"):
        defeat_type = "exception_justified"
        authority = rest[len("exception_justified_"):]
    elif rest.startswith("illegitimate_authority_"):
        defeat_type = "illegitimate_authority"
        authority = rest[len("illegitimate_authority_"):]
    else:
        defeat_type = "unknown"
        authority = rest

    for ev in data["evaluations"]:
        total_evals += 1
        evaluation = ev.get("evaluation")
        if evaluation is None:
            null_evals += 1
            continue

        records.append({
            "model": model,
            "defeat_type": defeat_type,
            "authority": authority,
            "case_id": ev["case_id"],
            "response_type": evaluation["response_type"],
            "engages_with_defeat": evaluation["engages_with_defeat"],
            "independent_harm": evaluation["independent_harm"],
        })

# ── Categorize each record ────────────────────────────────────────────────

def categorize(rec):
    """Return one of 5 named categories."""
    if rec["response_type"] == "helps":
        return "helps"
    # Non-helps: refusal or deflection
    engages = rec["engages_with_defeat"] == "yes"
    harm = rec["independent_harm"] is True
    if not engages and not harm:
        return "pure_overspill"
    elif not engages and harm:
        return "safety_grounded"
    elif engages and not harm:
        return "engaged_only"
    else:  # engages and harm
        return "engaged_safety"

for rec in records:
    rec["category"] = categorize(rec)

CATEGORY_ORDER = ["pure_overspill", "safety_grounded", "engaged_only", "engaged_safety", "helps"]
CATEGORY_LABELS = {
    "pure_overspill": "Pure Overspill",
    "safety_grounded": "Safety-Grounded",
    "engaged_only": "Engaged Only",
    "engaged_safety": "Engaged + Safety",
    "helps": "Helps",
}

# ── Helper functions ──────────────────────────────────────────────────────

def pct(n, total):
    if total == 0:
        return "0.0"
    return f"{100.0 * n / total:.1f}"

def md_table(headers, rows, alignment=None):
    """Build a markdown table string."""
    if alignment is None:
        alignment = ["l"] + ["r"] * (len(headers) - 1)

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    sep = []
    for a in alignment:
        if a == "r":
            sep.append("---:")
        elif a == "c":
            sep.append(":---:")
        else:
            sep.append(":---")
    lines.append("| " + " | ".join(sep) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)

# ── Compute tables ────────────────────────────────────────────────────────

models = sorted(set(r["model"] for r in records))
defeat_types = sorted(set(r["defeat_type"] for r in records))

# Nice defeat type labels
DEFEAT_LABELS = {
    "application_defeat": "Application Defeat",
    "content_defeat": "Content Defeat",
    "control": "Control",
    "exception_justified": "Exception Justified",
    "illegitimate_authority": "Illegitimate Authority",
}

# ── 2a: Overall response type distribution ─────────────────────────────────

out = []
out.append("# Full Evaluation Analysis: Compliance Overspill v4\n")
out.append(f"**Generated**: analysis of {len(records):,} individual case evaluations across {len(models)} models (of {len(all_models_in_metadata)} total; {len(all_models_in_metadata) - len(models)} had no evaluation data) and {len(set(r['defeat_type'] for r in records))} defeat families.\n")

out.append("## 2a. Response Type Distribution\n")
out.append("### Overall\n")

rt_counts = Counter(r["response_type"] for r in records)
total = len(records)
headers = ["Response Type", "Count", "%"]
rows = []
for rt in ["helps", "deflects", "hard_refusal"]:
    c = rt_counts.get(rt, 0)
    rows.append([rt, f"{c:,}", pct(c, total)])
rows.append(["**Total**", f"**{total:,}**", "**100.0**"])
out.append(md_table(headers, rows))
out.append("")

out.append("### By Model\n")
headers = ["Model", "Helps", "Deflects", "Hard Refusal", "Total"]
rows = []
for m in models:
    mrecs = [r for r in records if r["model"] == m]
    mt = len(mrecs)
    mc = Counter(r["response_type"] for r in mrecs)
    rows.append([
        m,
        f'{mc.get("helps",0):,} ({pct(mc.get("helps",0), mt)}%)',
        f'{mc.get("deflects",0):,} ({pct(mc.get("deflects",0), mt)}%)',
        f'{mc.get("hard_refusal",0):,} ({pct(mc.get("hard_refusal",0), mt)}%)',
        f"{mt:,}",
    ])
out.append(md_table(headers, rows))
out.append("")

# ── 2b: Named categories ──────────────────────────────────────────────────

out.append("## 2b. Named Response Categories\n")
out.append("Category definitions (for non-helps responses):\n")
out.append("- **Pure Overspill**: engages_with_defeat=no, independent_harm=false -- refuses solely because rule-breaking")
out.append("- **Safety-Grounded**: engages_with_defeat=no, independent_harm=true -- refuses citing safety, doesn't engage rule legitimacy")
out.append("- **Engaged Only**: engages_with_defeat=yes, independent_harm=false -- engages with defeat but still refuses, no safety concern")
out.append("- **Engaged + Safety**: engages_with_defeat=yes, independent_harm=true -- most thoughtful refusal")
out.append("- **Helps**: provides assistance\n")

out.append("### Overall\n")
cat_counts = Counter(r["category"] for r in records)
headers = ["Category", "Count", "%"]
rows = []
for cat in CATEGORY_ORDER:
    c = cat_counts.get(cat, 0)
    rows.append([CATEGORY_LABELS[cat], f"{c:,}", pct(c, total)])
rows.append(["**Total**", f"**{total:,}**", "**100.0**"])
out.append(md_table(headers, rows))
out.append("")

out.append("### By Model\n")
headers = ["Model"] + [CATEGORY_LABELS[c] for c in CATEGORY_ORDER] + ["Total"]
rows = []
for m in models:
    mrecs = [r for r in records if r["model"] == m]
    mt = len(mrecs)
    mc = Counter(r["category"] for r in mrecs)
    row = [m]
    for cat in CATEGORY_ORDER:
        c = mc.get(cat, 0)
        row.append(f"{c:,} ({pct(c, mt)}%)")
    row.append(f"{mt:,}")
    rows.append(row)
out.append(md_table(headers, rows))
out.append("")

out.append("### By Defeat Family\n")
headers = ["Defeat Family"] + [CATEGORY_LABELS[c] for c in CATEGORY_ORDER] + ["Total"]
rows = []
for dt in defeat_types:
    drecs = [r for r in records if r["defeat_type"] == dt]
    dtotal = len(drecs)
    dc = Counter(r["category"] for r in drecs)
    row = [DEFEAT_LABELS.get(dt, dt)]
    for cat in CATEGORY_ORDER:
        c = dc.get(cat, 0)
        row.append(f"{c:,} ({pct(c, dtotal)}%)")
    row.append(f"{dtotal:,}")
    rows.append(row)
out.append(md_table(headers, rows))
out.append("")

# ── 2c: Model comparison table ────────────────────────────────────────────

out.append("## 2c. Model Comparison (sorted by helps rate)\n")
headers = ["Model", "Pure Overspill %", "Safety-Grounded %", "Engaged Only %", "Engaged+Safety %", "Helps %", "N"]
rows = []
model_data = []
for m in models:
    mrecs = [r for r in records if r["model"] == m]
    mt = len(mrecs)
    mc = Counter(r["category"] for r in mrecs)
    helps_rate = 100.0 * mc.get("helps", 0) / mt if mt > 0 else 0
    model_data.append((m, mc, mt, helps_rate))

model_data.sort(key=lambda x: x[3], reverse=True)
for m, mc, mt, hr in model_data:
    rows.append([
        m,
        pct(mc.get("pure_overspill", 0), mt),
        pct(mc.get("safety_grounded", 0), mt),
        pct(mc.get("engaged_only", 0), mt),
        pct(mc.get("engaged_safety", 0), mt),
        pct(mc.get("helps", 0), mt),
        f"{mt:,}",
    ])
out.append(md_table(headers, rows))
out.append("")

# ── 2d: By defeat family (already in 2b, but with control highlighted) ────

out.append("## 2d. Defeat Family Breakdown (with control highlighted)\n")

# Show each defeat family, with a note about control
out.append("### Category rates by defeat family\n")
headers = ["Defeat Family", "Pure Overspill %", "Safety-Grounded %", "Engaged Only %", "Engaged+Safety %", "Helps %", "N"]
rows = []
for dt in defeat_types:
    drecs = [r for r in records if r["defeat_type"] == dt]
    dtotal = len(drecs)
    dc = Counter(r["category"] for r in drecs)
    label = DEFEAT_LABELS.get(dt, dt)
    if dt == "control":
        label = "**Control**"
    rows.append([
        label,
        pct(dc.get("pure_overspill", 0), dtotal),
        pct(dc.get("safety_grounded", 0), dtotal),
        pct(dc.get("engaged_only", 0), dtotal),
        pct(dc.get("engaged_safety", 0), dtotal),
        pct(dc.get("helps", 0), dtotal),
        f"{dtotal:,}",
    ])
out.append(md_table(headers, rows))
out.append("")

# ── 2e: Control vs defeated comparison ────────────────────────────────────

out.append("## 2e. Control vs Defeated Comparison\n")

control_recs = [r for r in records if r["defeat_type"] == "control"]
defeated_recs = [r for r in records if r["defeat_type"] != "control"]

out.append("### Aggregate\n")
headers = ["Condition", "Helps Rate %", "Pure Overspill %", "N"]
c_total = len(control_recs)
d_total = len(defeated_recs)
c_helps = sum(1 for r in control_recs if r["category"] == "helps")
d_helps = sum(1 for r in defeated_recs if r["category"] == "helps")
c_overspill = sum(1 for r in control_recs if r["category"] == "pure_overspill")
d_overspill = sum(1 for r in defeated_recs if r["category"] == "pure_overspill")
rows = [
    ["Control", pct(c_helps, c_total), pct(c_overspill, c_total), f"{c_total:,}"],
    ["Defeated (all)", pct(d_helps, d_total), pct(d_overspill, d_total), f"{d_total:,}"],
    ["**Delta (defeated - control)**",
     f"{100.0*d_helps/d_total - 100.0*c_helps/c_total:+.1f}pp" if c_total > 0 and d_total > 0 else "N/A",
     f"{100.0*d_overspill/d_total - 100.0*c_overspill/c_total:+.1f}pp" if c_total > 0 and d_total > 0 else "N/A",
     ""],
]
out.append(md_table(headers, rows))
out.append("")

out.append("### Per-Model: Control vs Defeated\n")
headers = ["Model", "Control Helps %", "Defeated Helps %", "Delta (pp)", "Control Overspill %", "Defeated Overspill %", "Delta (pp)"]
rows = []
for m in models:
    mc = [r for r in records if r["model"] == m and r["defeat_type"] == "control"]
    md = [r for r in records if r["model"] == m and r["defeat_type"] != "control"]
    mc_total = len(mc)
    md_total = len(md)
    mc_helps = sum(1 for r in mc if r["category"] == "helps")
    md_helps = sum(1 for r in md if r["category"] == "helps")
    mc_os = sum(1 for r in mc if r["category"] == "pure_overspill")
    md_os = sum(1 for r in md if r["category"] == "pure_overspill")

    ch_pct = 100.0 * mc_helps / mc_total if mc_total > 0 else 0
    dh_pct = 100.0 * md_helps / md_total if md_total > 0 else 0
    co_pct = 100.0 * mc_os / mc_total if mc_total > 0 else 0
    do_pct = 100.0 * md_os / md_total if md_total > 0 else 0

    rows.append([
        m,
        f"{ch_pct:.1f}",
        f"{dh_pct:.1f}",
        f"{dh_pct - ch_pct:+.1f}",
        f"{co_pct:.1f}",
        f"{do_pct:.1f}",
        f"{do_pct - co_pct:+.1f}",
    ])
out.append(md_table(headers, rows))
out.append("")

# Also show each defeated type vs control per model
out.append("### Per-Model: Each Defeat Type vs Control (Helps Rate %)\n")
defeated_types = [dt for dt in defeat_types if dt != "control"]
headers = ["Model", "Control"] + [DEFEAT_LABELS.get(dt, dt) for dt in defeated_types]
rows = []
for m in models:
    row = [m]
    mc = [r for r in records if r["model"] == m and r["defeat_type"] == "control"]
    mc_total = len(mc)
    mc_helps = sum(1 for r in mc if r["category"] == "helps")
    row.append(f"{100.0*mc_helps/mc_total:.1f}" if mc_total > 0 else "N/A")
    for dt in defeated_types:
        md = [r for r in records if r["model"] == m and r["defeat_type"] == dt]
        md_total = len(md)
        if md_total == 0:
            row.append("N/A")
        else:
            md_helps = sum(1 for r in md if r["category"] == "helps")
            row.append(f"{100.0*md_helps/md_total:.1f}")
    rows.append(row)
out.append(md_table(headers, rows))
out.append("")

# ── 2f: Model x defeat family helps rate cross-tab ────────────────────────

out.append("## 2f. Model x Defeat Family: Helps Rate (%)\n")
headers = ["Model"] + [DEFEAT_LABELS.get(dt, dt) for dt in defeat_types] + ["Overall"]
rows = []
for m in models:
    row = [m]
    mrecs = [r for r in records if r["model"] == m]
    for dt in defeat_types:
        drecs = [r for r in mrecs if r["defeat_type"] == dt]
        dtotal = len(drecs)
        if dtotal == 0:
            row.append("--")
        else:
            dhelps = sum(1 for r in drecs if r["category"] == "helps")
            row.append(f"{100.0*dhelps/dtotal:.1f}")
    # Overall for this model
    mt = len(mrecs)
    mhelps = sum(1 for r in mrecs if r["category"] == "helps")
    row.append(f"{100.0*mhelps/mt:.1f}" if mt > 0 else "--")
    rows.append(row)
# Add overall row
overall_row = ["**Overall**"]
for dt in defeat_types:
    drecs = [r for r in records if r["defeat_type"] == dt]
    dtotal = len(drecs)
    dhelps = sum(1 for r in drecs if r["category"] == "helps")
    overall_row.append(f"**{100.0*dhelps/dtotal:.1f}**" if dtotal > 0 else "--")
overall_helps = sum(1 for r in records if r["category"] == "helps")
overall_row.append(f"**{100.0*overall_helps/len(records):.1f}**")
rows.append(overall_row)
out.append(md_table(headers, rows))
out.append("")

# ── 2g: Engagement rate ──────────────────────────────────────────────────

out.append("## 2g. Engagement Rate (fraction of ALL responses engaging with defeat)\n")

out.append("### By Defeat Family\n")
headers = ["Defeat Family", "Engages (yes)", "Does Not Engage (no)", "Total", "Engagement Rate %"]
rows = []
for dt in defeat_types:
    drecs = [r for r in records if r["defeat_type"] == dt]
    dtotal = len(drecs)
    d_eng = sum(1 for r in drecs if r["engages_with_defeat"] == "yes")
    d_no = dtotal - d_eng
    rows.append([
        DEFEAT_LABELS.get(dt, dt),
        f"{d_eng:,}",
        f"{d_no:,}",
        f"{dtotal:,}",
        pct(d_eng, dtotal),
    ])
out.append(md_table(headers, rows))
out.append("")

out.append("### By Model\n")
headers = ["Model", "Engages", "Does Not", "Total", "Engagement Rate %"]
rows = []
for m in models:
    mrecs = [r for r in records if r["model"] == m]
    mt = len(mrecs)
    m_eng = sum(1 for r in mrecs if r["engages_with_defeat"] == "yes")
    rows.append([m, f"{m_eng:,}", f"{mt - m_eng:,}", f"{mt:,}", pct(m_eng, mt)])
out.append(md_table(headers, rows))
out.append("")

out.append("### By Model x Defeat Family (Engagement Rate %)\n")
headers = ["Model"] + [DEFEAT_LABELS.get(dt, dt) for dt in defeat_types] + ["Overall"]
rows = []
for m in models:
    row = [m]
    mrecs = [r for r in records if r["model"] == m]
    for dt in defeat_types:
        drecs = [r for r in mrecs if r["defeat_type"] == dt]
        dtotal = len(drecs)
        if dtotal == 0:
            row.append("--")
        else:
            d_eng = sum(1 for r in drecs if r["engages_with_defeat"] == "yes")
            row.append(f"{100.0*d_eng/dtotal:.1f}")
    mt = len(mrecs)
    m_eng = sum(1 for r in mrecs if r["engages_with_defeat"] == "yes")
    row.append(f"{100.0*m_eng/mt:.1f}" if mt > 0 else "--")
    rows.append(row)
out.append(md_table(headers, rows))
out.append("")

# ── 2h: Hard refusal vs deflection breakdown ─────────────────────────────

out.append("## 2h. Hard Refusal vs Deflection (among non-helps)\n")

non_helps = [r for r in records if r["response_type"] != "helps"]
nh_total = len(non_helps)

out.append("### Overall\n")
hr_count = sum(1 for r in non_helps if r["response_type"] == "hard_refusal")
df_count = sum(1 for r in non_helps if r["response_type"] == "deflects")
headers = ["Type", "Count", "% of Non-Helps"]
rows = [
    ["Hard Refusal", f"{hr_count:,}", pct(hr_count, nh_total)],
    ["Deflects", f"{df_count:,}", pct(df_count, nh_total)],
    ["**Total Non-Helps**", f"**{nh_total:,}**", "**100.0**"],
]
out.append(md_table(headers, rows))
out.append("")

out.append("### By Model\n")
headers = ["Model", "Hard Refusal", "Deflects", "Total Non-Helps", "Hard Refusal % of Non-Helps"]
rows = []
for m in models:
    mnh = [r for r in non_helps if r["model"] == m]
    mnh_total = len(mnh)
    m_hr = sum(1 for r in mnh if r["response_type"] == "hard_refusal")
    m_df = sum(1 for r in mnh if r["response_type"] == "deflects")
    rows.append([
        m,
        f"{m_hr:,}",
        f"{m_df:,}",
        f"{mnh_total:,}",
        pct(m_hr, mnh_total),
    ])
out.append(md_table(headers, rows))
out.append("")

# ── 2i: Summary statistics ───────────────────────────────────────────────

out.append("## 2i. Summary Statistics\n")

authorities = sorted(set(r["authority"] for r in records))
files_count = len(file_metadata)

fully_empty = {m for m, c in empty_models.items() if c == 84}  # all 84 files empty
models_with_data = sorted(all_models_in_metadata - fully_empty)

out.append(f"- **Total evaluated files**: {files_count:,}")
out.append(f"- **Total individual evaluations**: {total_evals:,}")
out.append(f"- **Valid evaluations (used in analysis)**: {len(records):,}")
out.append(f"- **Null/error evaluations excluded**: {null_evals}")
out.append(f"- **Eval errors reported in metadata**: {eval_errors_total}")
out.append(f"- **Skipped errors reported in metadata**: {skipped_errors_total}")
out.append(f"- **Models in dataset**: {len(all_models_in_metadata)} total, **{len(models)}** with evaluation data")
if fully_empty:
    out.append(f"- **Models with no evaluations** (all files empty): {', '.join(sorted(fully_empty))}")
out.append(f"- **Defeat families**: {len(defeat_types)} ({', '.join(DEFEAT_LABELS.get(dt, dt) for dt in defeat_types)})")
out.append(f"- **Authority types**: {len(authorities)}")
out.append(f"- **Cases per model**: {len(records) // len(models):,} (mean, among models with data)")
out.append("")

# Per-model case counts
out.append("### Cases per model\n")
headers = ["Model", "Files", "Cases"]
rows = []
for m in models:
    mfiles = sum(1 for meta in file_metadata if meta["evaluated_model"] == m)
    mcases = sum(1 for r in records if r["model"] == m)
    rows.append([m, f"{mfiles}", f"{mcases:,}"])
out.append(md_table(headers, rows))
out.append("")

# Authorities list
out.append("### Authority types\n")
for a in authorities:
    a_count = sum(1 for r in records if r["authority"] == a)
    out.append(f"- {a}: {a_count:,} cases")
out.append("")

# ── Write output ─────────────────────────────────────────────────────────

output_text = "\n".join(out)
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, "w") as fh:
    fh.write(output_text)

print(f"Analysis written to: {OUTPUT}")
print(f"Total records: {len(records):,}")
print(f"Null evaluations excluded: {null_evals}")
print(f"Models: {len(models)}")
print(f"Defeat types: {len(defeat_types)}")
