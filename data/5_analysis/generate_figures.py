#!/usr/bin/env python3
"""
Publication-quality visualization pipeline for Compliance Overspill evaluation results.

Reads from data/4_evaluated/*.json, merges with case metadata from data/2_filtered/*.json,
and generates radar grids, heatmaps, bar charts, and summary tables for the paper.

Output:  data/5_analysis/figures/ (PDF + PNG for each figure)

Usage:
    python3 data/5_analysis/generate_figures.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend -- safe for headless runs

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = PROJECT / "data" / "4_evaluated"
FILTERED_DIR = PROJECT / "data" / "2_filtered"
FIGURES_DIR = PROJECT / "data" / "5_analysis" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFEAT_TYPES = [
    "control",
    "illegitimate_authority",
    "content_defeat",
    "application_defeat",
    "exception_justified",
]

DEFEAT_LABELS = {
    "control": "Control",
    "illegitimate_authority": "Illegit. Auth",
    "content_defeat": "Content",
    "application_defeat": "Application",
    "exception_justified": "Exception",
}

AUTHORITY_TYPES = [
    "national_government", "subnational_government", "supranational_body",
    "family", "tribe",
    "profession", "faith_group", "school", "housing_association", "union",
    "algorithmic_intermediary", "military_command",
    "workplace", "club", "landlord", "creditor_insurer",
    "private_property_owner", "contractual_counterparty", "delegated_authority",
]

AUTHORITY_GROUP_MAP = {
    "national_government": "government",
    "subnational_government": "government",
    "supranational_body": "government",
    "family": "non_voluntary",
    "tribe": "non_voluntary",
    "profession": "semi_voluntary",
    "faith_group": "semi_voluntary",
    "school": "semi_voluntary",
    "housing_association": "semi_voluntary",
    "union": "semi_voluntary",
    "algorithmic_intermediary": "semi_voluntary",
    "military_command": "semi_voluntary",
    "workplace": "voluntary",
    "club": "voluntary",
    "landlord": "voluntary",
    "creditor_insurer": "voluntary",
    "private_property_owner": "voluntary",
    "contractual_counterparty": "voluntary",
    "delegated_authority": "voluntary",
}

AUTHORITY_GROUPS = ["government", "non_voluntary", "semi_voluntary", "voluntary"]

AUTHORITY_GROUP_LABELS = {
    "government": "Government",
    "non_voluntary": "Non-voluntary",
    "semi_voluntary": "Semi-voluntary",
    "voluntary": "Voluntary",
}

# Which authority types belong to which group (ordered for heatmap columns)
AUTHORITY_TYPES_BY_GROUP = {
    "government": ["national_government", "subnational_government", "supranational_body"],
    "non_voluntary": ["family", "tribe"],
    "semi_voluntary": [
        "profession", "faith_group", "school", "housing_association",
        "union", "algorithmic_intermediary", "military_command",
    ],
    "voluntary": [
        "workplace", "club", "landlord", "creditor_insurer",
        "private_property_owner", "contractual_counterparty", "delegated_authority",
    ],
}

# Flat ordered list for heatmap columns
AUTHORITY_TYPES_ORDERED = []
for _g in AUTHORITY_GROUPS:
    AUTHORITY_TYPES_ORDERED.extend(AUTHORITY_TYPES_BY_GROUP[_g])

MODEL_SLUGS = [
    "claude-sonnet-4-6", "claude-opus-4-6",
    "gpt-5-4-nano-thinking", "gpt-5-4-mini-thinking", "gpt-5-4-thinking",
    "gpt-5-4-base", "gpt-5-4-mini-base",
    "gemini-3-1-pro", "gemini-3-1-flash-lite",
    "qwen-3-5-flash", "qwen-3-5-plus", "qwen-3-5-397b",
    "glm-5-turbo", "glm-5",
    "nemotron-3-nano", "nemotron-3-super",
    "grok-4-fast", "grok-4",
]

# Model family assignments (for grouped colors and family-level aggregation)
MODEL_FAMILY = {
    "claude-sonnet-4-6": "Anthropic",
    "claude-opus-4-6": "Anthropic",
    "gpt-5-4-nano-thinking": "OpenAI",
    "gpt-5-4-mini-thinking": "OpenAI",
    "gpt-5-4-thinking": "OpenAI",
    "gpt-5-4-base": "OpenAI",
    "gpt-5-4-mini-base": "OpenAI",
    "gemini-3-1-pro": "Google",
    "gemini-3-1-flash-lite": "Google",
    "qwen-3-5-flash": "Qwen",
    "qwen-3-5-plus": "Qwen",
    "qwen-3-5-397b": "Qwen",
    "glm-5-turbo": "GLM",
    "glm-5": "GLM",
    "nemotron-3-nano": "Nvidia",
    "nemotron-3-super": "Nvidia",
    "grok-4-fast": "xAI",
    "grok-4": "xAI",
}

FAMILY_ORDER = ["Anthropic", "OpenAI", "Google", "Qwen", "GLM", "Nvidia", "xAI"]

# ---------------------------------------------------------------------------
# Color palette -- grouped by model family
# ---------------------------------------------------------------------------

# Family base colors (qualitative, colorblind-aware)
_FAMILY_COLORS = {
    "Anthropic": ["#1f77b4", "#6baed6"],                                       # blues
    "OpenAI":    ["#2ca02c", "#66c2a5", "#98d594", "#38761d", "#a6d854"],       # greens
    "Google":    ["#d62728", "#fc8d59"],                                        # reds
    "Qwen":     ["#9467bd", "#bcbddc", "#756bb1"],                              # purples
    "GLM":      ["#ff7f0e", "#fdae61"],                                         # oranges
    "Nvidia":   ["#7f7f7f", "#bdbdbd"],                                         # grays
    "xAI":      ["#17becf", "#9edae5"],                                         # teals
}

def _build_model_colors() -> dict[str, str]:
    """Assign each model slug a color from its family palette."""
    colors: dict[str, str] = {}
    family_idx: dict[str, int] = {f: 0 for f in FAMILY_ORDER}
    for slug in MODEL_SLUGS:
        fam = MODEL_FAMILY.get(slug, "xAI")
        palette = _FAMILY_COLORS[fam]
        idx = family_idx[fam] % len(palette)
        colors[slug] = palette[idx]
        family_idx[fam] = idx + 1
    return colors

MODEL_COLORS = _build_model_colors()

# Family-level colors (one color per family for family-averaged plots)
FAMILY_COLORS = {
    "Anthropic": "#1f77b4",
    "OpenAI":    "#2ca02c",
    "Google":    "#d62728",
    "Qwen":     "#9467bd",
    "GLM":      "#ff7f0e",
    "Nvidia":   "#7f7f7f",
    "xAI":      "#17becf",
}

# Excluded / implausible defeat-type x authority-type combinations.
# These cells are grayed out in the full matrix heatmap.
# Format: set of (defeat_type, authority_type) tuples.
EXCLUDED_CELLS: set[tuple[str, str]] = set()
# Populate this if certain combinations are logically impossible or were
# intentionally excluded from the case generation. Leave empty if all
# combinations are valid.


# ---------------------------------------------------------------------------
# Style setup
# ---------------------------------------------------------------------------

def setup_style():
    """Apply publication-quality matplotlib style."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 9,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.15,
        "pdf.fonttype": 42,    # TrueType in PDFs (LaTeX-friendly)
        "ps.fonttype": 42,
    })


# ---------------------------------------------------------------------------
# Case-ID parser
# ---------------------------------------------------------------------------

def parse_case_id(case_id: str) -> tuple[str, str]:
    """
    Extract defeat_type and authority_type from a case_id.

    Format: seed_{defeat_type}_{authority_type}_{N}

    Defeat types and authority types can both contain underscores, so we match
    against known defeat types first, then known authority types.
    """
    # Strip the 'seed_' prefix and trailing '_N'
    rest = case_id
    if rest.startswith("seed_"):
        rest = rest[5:]
    # Remove trailing _<digits>
    rest = re.sub(r"_(\d+)$", "", rest)

    # Try each defeat type prefix (longest first to avoid partial matches)
    for dt in sorted(DEFEAT_TYPES, key=len, reverse=True):
        if rest.startswith(dt + "_"):
            authority_candidate = rest[len(dt) + 1:]
            if authority_candidate in AUTHORITY_GROUP_MAP:
                return dt, authority_candidate
            # Also handle authority types we might not know about
            return dt, authority_candidate
        elif rest == dt:
            return dt, ""

    return "", rest


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_eval_data() -> pd.DataFrame:
    """
    Load all evaluation results into a single DataFrame.

    Columns:
        case_id, model_slug, defeat_type, authority_type, authority_group,
        response_type, engages_with_defeat, independent_harm, dual_use_flagged
    """
    if not EVAL_DIR.exists():
        print(f"Evaluation directory not found: {EVAL_DIR}")
        return pd.DataFrame()

    eval_files = sorted(EVAL_DIR.glob("*.json"))
    if not eval_files:
        return pd.DataFrame()

    rows: list[dict] = []

    for fp in eval_files:
        try:
            with open(fp, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  WARNING: skipping {fp.name}: {exc}", file=sys.stderr)
            continue

        meta = data.get("metadata", {})
        model_slug = meta.get("evaluated_model", "")

        for ev in data.get("evaluations", []):
            case_id = ev.get("case_id", "")
            evaluation = ev.get("evaluation", {})
            gate_flags = ev.get("gate_flags", {})

            # Parse defeat/authority from case_id
            defeat_type, authority_type = parse_case_id(case_id)
            authority_group = AUTHORITY_GROUP_MAP.get(authority_type, "")

            # Dual-use flag
            du = gate_flags.get("dual_use", {})
            du_flagged = du.get("flagged") if isinstance(du, dict) else None

            rows.append({
                "case_id": case_id,
                "model_slug": model_slug,
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                "authority_group": authority_group,
                "response_type": evaluation.get("response_type", "deflects"),
                "engages_with_defeat": evaluation.get("engages_with_defeat",
                                        evaluation.get("acknowledges_defeat", "no")),
                "independent_harm": bool(evaluation.get("independent_harm", False)),
                "dual_use_flagged": du_flagged,
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Ensure categorical ordering where useful
    df["defeat_type"] = pd.Categorical(df["defeat_type"], categories=DEFEAT_TYPES, ordered=True)
    df["authority_group"] = pd.Categorical(
        df["authority_group"], categories=AUTHORITY_GROUPS, ordered=True
    )

    return df


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def _refusal_rate(sub: pd.DataFrame) -> float:
    """Compute (hard_refusal + deflects) / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return ((sub["response_type"] == "hard_refusal") |
            (sub["response_type"] == "deflects")).sum() / n


def _hard_refusal_rate(sub: pd.DataFrame) -> float:
    """Compute hard_refusal / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return (sub["response_type"] == "hard_refusal").sum() / n


def _deflects_rate(sub: pd.DataFrame) -> float:
    """Compute deflects / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return (sub["response_type"] == "deflects").sum() / n


def _helps_rate(sub: pd.DataFrame) -> float:
    """Compute helps / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return (sub["response_type"] == "helps").sum() / n


def _engagement_rate(sub: pd.DataFrame) -> float:
    """Compute engages_with_defeat=yes / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return (sub["engages_with_defeat"] == "yes").sum() / n


def _independent_harm_rate(sub: pd.DataFrame) -> float:
    """Compute independent_harm=True / total for a subset."""
    n = len(sub)
    if n == 0:
        return np.nan
    return sub["independent_harm"].sum() / n


# ---------------------------------------------------------------------------
# Helper: save figure as both PDF + PNG
# ---------------------------------------------------------------------------

def save_fig(fig: plt.Figure, output_path: str):
    """Save figure as PDF and PNG."""
    base = FIGURES_DIR / output_path
    fig.savefig(str(base) + ".pdf", format="pdf")
    fig.savefig(str(base) + ".png", format="png")
    plt.close(fig)
    print(f"  Saved: {base}.pdf / .png")


# ---------------------------------------------------------------------------
# Plot 1: Polar grid by defeat type (18 small multiples)
# ---------------------------------------------------------------------------

def plot_polar_grid_by_defeat(df: pd.DataFrame, output_path: str):
    """
    3x6 grid of small polar/radar charts, one per model.
    5 axes: the 5 defeat types. Value: refusal rate.
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for polar grid (defeat). Skipping.")
        return

    # 3 rows x 6 cols = 18 slots (exact fit)
    n_models = len(models_present)
    n_rows, n_cols = 3, 6
    n_slots = n_rows * n_cols

    categories = list(DEFEAT_TYPES)
    cat_labels = [DEFEAT_LABELS.get(c, c) for c in categories]
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(24, 12),
        subplot_kw=dict(polar=True),
    )
    fig.subplots_adjust(hspace=0.35, wspace=0.3)
    fig.suptitle("Refusal Rate by Defeat Type (per model)", fontsize=28, fontweight="bold", y=1.01)

    seen_families_outer = set()
    for idx in range(n_slots):
        row, col = divmod(idx, n_cols)
        ax = axes[row][col]

        if idx >= n_models:
            ax.set_visible(False)
            continue

        model = models_present[idx]
        family = MODEL_FAMILY.get(model, "xAI")
        color = FAMILY_COLORS.get(family, "#333333")
        mdf = df[df["model_slug"] == model]

        vals = []
        for dt in categories:
            sub = mdf[mdf["defeat_type"] == dt]
            vals.append(_refusal_rate(sub) if len(sub) > 0 else 0.0)
        # Replace any NaN with 0 for plotting
        vals = [v if not np.isnan(v) else 0.0 for v in vals]
        vals_closed = vals + vals[:1]

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(cat_labels, fontsize=16)
        ax.tick_params(axis="x", which="major", pad=12)
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels(["25%", "50%", "75%", ""], fontsize=9, color="gray")

        ax.plot(angles, vals_closed, color=color, linewidth=1.5, alpha=0.9)
        ax.fill(angles, vals_closed, color=color, alpha=0.15)
        ax.set_title(model, fontsize=18, fontweight="bold", pad=20)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 1b: Polar grid by authority group (18 small multiples)
# ---------------------------------------------------------------------------

def plot_polar_grid_by_authority(df: pd.DataFrame, output_path: str):
    """
    3x6 grid of small polar/radar charts, one per model.
    4 axes: the 4 authority groups. Value: refusal rate.
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for polar grid (authority). Skipping.")
        return

    n_models = len(models_present)
    n_rows, n_cols = 3, 6
    n_slots = n_rows * n_cols

    categories = list(AUTHORITY_GROUPS)
    cat_labels = [AUTHORITY_GROUP_LABELS.get(c, c) for c in categories]
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(18, 10),
        subplot_kw=dict(polar=True),
    )
    fig.suptitle("Refusal Rate by Authority Group (per model)", fontsize=16, fontweight="bold", y=1.02)

    for idx in range(n_slots):
        row, col = divmod(idx, n_cols)
        ax = axes[row][col]

        if idx >= n_models:
            ax.set_visible(False)
            continue

        model = models_present[idx]
        family = MODEL_FAMILY.get(model, "xAI")
        color = FAMILY_COLORS.get(family, "#333333")
        mdf = df[df["model_slug"] == model]

        vals = []
        for ag in categories:
            sub = mdf[mdf["authority_group"] == ag]
            vals.append(_refusal_rate(sub) if len(sub) > 0 else 0.0)
        vals = [v if not np.isnan(v) else 0.0 for v in vals]
        vals_closed = vals + vals[:1]

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(cat_labels, fontsize=14)
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels(["25%", "50%", "75%", ""], fontsize=11, color="gray")

        ax.plot(angles, vals_closed, color=color, linewidth=1.5, alpha=0.9)
        ax.fill(angles, vals_closed, color=color, alpha=0.15)
        ax.set_title(model, fontsize=16, fontweight="bold", pad=18)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 2: Cumulative matrix heatmap (defeat type x authority type)
# ---------------------------------------------------------------------------

def plot_matrix_heatmap_cumulative(df: pd.DataFrame, output_path: str, min_n: int = 5):
    """
    Full matrix heatmap: rows = 5 defeat types, columns = 19 authority types
    (grouped by voluntariness with bracket labels). Cell = average refusal rate
    across all models. Diverging color: blue (low) -- white (50%) -- red (high).
    """
    defeats = list(DEFEAT_TYPES)
    authorities = list(AUTHORITY_TYPES_ORDERED)

    if df.empty:
        print("  WARNING: Empty data for cumulative heatmap. Skipping.")
        return

    n_defeats = len(defeats)
    n_auths = len(authorities)
    matrix = np.full((n_defeats, n_auths), np.nan)
    count_matrix = np.zeros((n_defeats, n_auths), dtype=int)

    for i, dt in enumerate(defeats):
        for j, at in enumerate(authorities):
            sub = df[(df["defeat_type"] == dt) & (df["authority_type"] == at)]
            count_matrix[i, j] = len(sub)
            if len(sub) > 0:
                matrix[i, j] = _refusal_rate(sub)

    # Square cells: set figsize so cell aspect ratio is ~1:1
    cell_size = 0.9  # inches per cell
    fig_w = n_auths * cell_size + 4  # extra for y-labels and colorbar
    fig_h = n_defeats * cell_size + 3  # extra for x-labels and title
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    cmap = plt.cm.RdBu_r
    norm = mcolors.TwoSlopeNorm(vmin=0.0, vcenter=0.5, vmax=1.0)

    # Mask excluded cells
    masked_matrix = np.ma.array(matrix)
    for i, dt in enumerate(defeats):
        for j, at in enumerate(authorities):
            if (dt, at) in EXCLUDED_CELLS:
                masked_matrix[i, j] = np.ma.masked

    # Use pcolormesh with edgecolors='face' to eliminate cell-boundary seams
    X, Y = np.meshgrid(np.arange(n_auths + 1) - 0.5, np.arange(n_defeats + 1) - 0.5)
    im = ax.pcolormesh(X, Y, masked_matrix, cmap=cmap, norm=norm,
                       edgecolors="face", linewidth=0.5, rasterized=True)
    ax.set_xlim(-0.5, n_auths - 0.5)
    ax.set_ylim(n_defeats - 0.5, -0.5)
    ax.set_aspect("equal")

    # Gray out excluded cells
    for i, dt in enumerate(defeats):
        for j, at in enumerate(authorities):
            if (dt, at) in EXCLUDED_CELLS:
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                           fill=True, facecolor="#d9d9d9", edgecolor="white", lw=0.5))

    # Annotate cells
    for i in range(n_defeats):
        for j in range(n_auths):
            if (defeats[i], authorities[j]) in EXCLUDED_CELLS:
                continue
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "--", ha="center", va="center", fontsize=11, color="gray")
            else:
                text_color = "white" if (val > 0.80 or val < 0.20) else "black"
                ax.text(j, i, f"{val:.0%}", ha="center", va="center",
                        fontsize=20, fontweight="bold", color=text_color)

    # Axis labels
    defeat_labels = [DEFEAT_LABELS.get(d, d) for d in defeats]
    auth_labels = [a.replace("_", "\n") for a in authorities]
    ax.set_yticks(range(n_defeats))
    ax.set_yticklabels(defeat_labels, fontsize=13)
    ax.set_xticks(range(n_auths))
    ax.set_xticklabels(auth_labels, fontsize=16, rotation=45, ha="right")
    ax.tick_params(axis="both", which="both", length=0)
    ax.grid(False)

    # Title FIRST (above everything) via fig.suptitle
    fig.suptitle("Average Refusal Rate: Defeat Type x Authority Type (all models)",
                 fontsize=26, fontweight="bold", y=1.0)

    # Group bracket labels below the title
    col_idx = 0
    for grp in AUTHORITY_GROUPS:
        members = AUTHORITY_TYPES_BY_GROUP[grp]
        n_members = len(members)
        center = col_idx + (n_members - 1) / 2
        label = AUTHORITY_GROUP_LABELS.get(grp, grp)
        ax.text(center, -1.2, label, ha="center", va="bottom", fontsize=12,
                fontweight="bold", transform=ax.transData)
        if n_members > 1:
            ax.plot([col_idx - 0.3, col_idx + n_members - 0.7], [-0.7, -0.7],
                    color="black", linewidth=1.0, clip_on=False, transform=ax.transData)
        col_idx += n_members

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Refusal Rate", fontsize=13)
    cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=11)

    fig.tight_layout()
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 3: Per-model matrix heatmaps (18 small multiples)
# ---------------------------------------------------------------------------

def plot_matrix_heatmaps_per_model(df: pd.DataFrame, output_path: str):
    """
    3x6 grid of heatmaps (defeat type x authority GROUP), one per model.
    Simplified to 5 rows x 4 columns per subplot for readability.
    Same color scale across all. No per-cell annotation (color only).
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for per-model heatmaps. Skipping.")
        return

    defeats = list(DEFEAT_TYPES)
    groups = list(AUTHORITY_GROUPS)
    n_defeats = len(defeats)
    n_groups = len(groups)

    n_rows, n_cols = 3, 6
    n_slots = n_rows * n_cols
    n_models = len(models_present)

    cmap = plt.cm.RdBu_r
    norm = mcolors.TwoSlopeNorm(vmin=0.0, vcenter=0.5, vmax=1.0)

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(18, 10))
    fig.suptitle("Refusal Rate: Defeat Type x Authority Group (per model)",
                 fontsize=16, fontweight="bold", y=1.01)

    group_labels = [AUTHORITY_GROUP_LABELS.get(g, g) for g in groups]

    for idx in range(n_slots):
        row, col = divmod(idx, n_cols)
        ax = axes[row][col]

        if idx >= n_models:
            ax.set_visible(False)
            continue

        model = models_present[idx]
        mdf = df[df["model_slug"] == model]

        matrix = np.full((n_defeats, n_groups), np.nan)
        for i, dt in enumerate(defeats):
            for j, grp in enumerate(groups):
                sub = mdf[(mdf["defeat_type"] == dt) & (mdf["authority_group"] == grp)]
                if len(sub) > 0:
                    matrix[i, j] = _refusal_rate(sub)

        ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto",
                  interpolation="nearest")
        ax.tick_params(length=0)  # no tick marks
        ax.grid(False)  # no grid lines
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(model, fontsize=7, fontweight="bold", pad=4)

        # Tick labels
        if col == 0:
            ax.set_yticks(range(n_defeats))
            ax.set_yticklabels([DEFEAT_LABELS.get(d, d) for d in defeats], fontsize=6)
        else:
            ax.set_yticks([])

        if row == n_rows - 1:
            ax.set_xticks(range(n_groups))
            ax.set_xticklabels(group_labels, fontsize=6, rotation=45, ha="right")
        else:
            ax.set_xticks([])

    fig.subplots_adjust(right=0.91, hspace=0.35, wspace=0.15, top=0.93, bottom=0.10)
    cbar_ax = fig.add_axes([0.93, 0.15, 0.012, 0.7])
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.set_label("Refusal Rate", fontsize=9)
    cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=7)
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 4: Refusal rate bar chart (sorted, stacked)
# ---------------------------------------------------------------------------

def plot_refusal_rates_sorted(df: pd.DataFrame, output_path: str):
    """
    Horizontal stacked bars: hard_refusal (dark) + deflects (medium).
    One bar per model, sorted by total refusal rate (highest at top).
    Colored by model family.
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for refusal bar chart. Skipping.")
        return

    data = []
    for model in models_present:
        mdf = df[df["model_slug"] == model]
        n = len(mdf)
        if n == 0:
            continue
        hr = (mdf["response_type"] == "hard_refusal").sum() / n
        defl = (mdf["response_type"] == "deflects").sum() / n
        data.append({
            "model": model,
            "hard_refusal": hr,
            "deflects": defl,
            "total_refusal": hr + defl,
            "family": MODEL_FAMILY.get(model, "xAI"),
        })

    if not data:
        return

    # Sort by total refusal descending (highest at top of horizontal chart)
    data.sort(key=lambda x: x["total_refusal"])
    models = [d["model"] for d in data]
    hard = [d["hard_refusal"] for d in data]
    defl = [d["deflects"] for d in data]
    families = [d["family"] for d in data]

    y = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(10, 8))

    # Stacked horizontal bars
    for i, (m, h, d, fam) in enumerate(zip(models, hard, defl, families)):
        base_color = FAMILY_COLORS.get(fam, "#333333")
        # Dark shade for hard_refusal, lighter for deflects
        dark = base_color
        light = mcolors.to_hex([min(1, c + 0.3) for c in mcolors.to_rgb(base_color)])

        ax.barh(i, h, color=dark, edgecolor="white", linewidth=0.3, height=0.7)
        ax.barh(i, d, left=h, color=light, edgecolor="white", linewidth=0.3, height=0.7)

    ax.set_yticks(y)
    ax.set_yticklabels(models, fontsize=9)
    ax.set_xlim(0, 1.0)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlabel("Refusal Rate")
    ax.set_title("Total Refusal Rate by Model (hard refusal + deflects)", fontsize=13, fontweight="bold")

    # Legend — family colors + refusal type indicators
    from matplotlib.patches import Patch
    legend_elements = []
    # Family colors
    families_present = list(dict.fromkeys(families))  # unique, preserve order
    for fam in FAMILY_ORDER:
        if fam in families_present:
            legend_elements.append(Patch(facecolor=FAMILY_COLORS[fam], label=fam))
    legend_elements.append(Patch(facecolor="none", label=""))  # spacer
    legend_elements.append(Patch(facecolor="#333333", label="Hard refusal (dark shade)"))
    legend_elements.append(Patch(facecolor="#999999", label="Deflects (light shade)"))
    ax.legend(handles=legend_elements, loc="lower right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 5: Engagement rate bar chart (control vs defeat)
# ---------------------------------------------------------------------------

def plot_engagement_rates(df: pd.DataFrame, output_path: str):
    """
    Grouped horizontal bar chart: engagement rate for control vs defeat cases.
    One pair of bars per model.
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for engagement chart. Skipping.")
        return

    defeat_eng: list[float] = []
    control_eng: list[float] = []

    for model in models_present:
        mdf = df[df["model_slug"] == model]
        # Defeat cases (non-control)
        ddf = mdf[mdf["defeat_type"] != "control"]
        n_d = len(ddf)
        defeat_eng.append(
            (ddf["engages_with_defeat"] == "yes").sum() / n_d if n_d > 0 else 0.0
        )
        # Control cases
        cdf = mdf[mdf["defeat_type"] == "control"]
        n_c = len(cdf)
        control_eng.append(
            (cdf["engages_with_defeat"] == "yes").sum() / n_c if n_c > 0 else 0.0
        )

    y = np.arange(len(models_present))
    height = 0.35

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(y - height / 2, defeat_eng, height, label="Defeat cases",
            color="#d62728", alpha=0.8)
    ax.barh(y + height / 2, control_eng, height, label="Control cases",
            color="#1f77b4", alpha=0.8)

    ax.set_xlabel("Engagement Rate (engages_with_defeat = yes)")
    ax.set_title("Engagement with Defeat Conditions", fontsize=13, fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels(models_present, fontsize=9)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlim(0, 1.05)
    ax.legend(loc="lower right", fontsize=9)

    fig.tight_layout()
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Plot 6: Independent harm bar chart (sorted)
# ---------------------------------------------------------------------------

def plot_independent_harm_rates(df: pd.DataFrame, output_path: str):
    """
    Horizontal bars: independent_harm=True rate per model, sorted by rate.
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  WARNING: No models for independent harm chart. Skipping.")
        return

    data = []
    for model in models_present:
        mdf = df[df["model_slug"] == model]
        n = len(mdf)
        if n == 0:
            continue
        rate = mdf["independent_harm"].sum() / n
        data.append({
            "model": model,
            "rate": rate,
            "family": MODEL_FAMILY.get(model, "xAI"),
        })

    if not data:
        return

    # Sort ascending (highest at top for horizontal bars)
    data.sort(key=lambda x: x["rate"])
    models = [d["model"] for d in data]
    rates = [d["rate"] for d in data]
    colors = [FAMILY_COLORS.get(d["family"], "#333333") for d in data]

    y = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(10, 8))

    ax.barh(y, rates, color=colors, edgecolor="white", linewidth=0.3, height=0.7)

    ax.set_yticks(y)
    ax.set_yticklabels(models, fontsize=9)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlabel("Independent Harm Rate")
    ax.set_title("Independent Harm Rate by Model", fontsize=13, fontweight="bold")
    max_rate = max(rates) if rates else 0.1
    ax.set_xlim(0, max(max_rate * 1.2, 0.05))

    fig.tight_layout()
    save_fig(fig, output_path)


# ---------------------------------------------------------------------------
# Summary table (LaTeX)
# ---------------------------------------------------------------------------

def print_summary_table(df: pd.DataFrame, output_path: str = "summary_table"):
    """
    Generate and save a LaTeX-formatted summary table.

    Columns: Model, N, Helps%, Deflects%, Hard Refusal%, Engagement%, Independent Harm%
    """
    models_present = [m for m in MODEL_SLUGS if m in df["model_slug"].values]
    if not models_present:
        print("  No models to summarize.")
        return

    header = (
        "\\begin{table}[t]\n"
        "\\centering\n"
        "\\caption{Per-model summary of response distribution and engagement.}\n"
        "\\label{tab:model_summary}\n"
        "\\small\n"
        "\\begin{tabular}{lrrrrrr}\n"
        "\\toprule\n"
        "Model & N & Helps & Deflects & Hard Ref. & Engage & Ind. Harm \\\\\n"
        "\\midrule"
    )

    rows_tex = []
    for model in models_present:
        mdf = df[df["model_slug"] == model]
        n = len(mdf)
        if n == 0:
            continue

        helps = (mdf["response_type"] == "helps").sum()
        deflects = (mdf["response_type"] == "deflects").sum()
        hard_ref = (mdf["response_type"] == "hard_refusal").sum()
        engage = (mdf["engages_with_defeat"] == "yes").sum()
        ih = mdf["independent_harm"].sum()

        row = (
            f"{model} & {n} & "
            f"{helps/n:.1%} & {deflects/n:.1%} & {hard_ref/n:.1%} & "
            f"{engage/n:.1%} & {ih/n:.1%} \\\\"
        )
        rows_tex.append(row)

    footer = (
        "\\bottomrule\n"
        "\\end{tabular}\n"
        "\\end{table}"
    )

    # Print to terminal
    print("\n" + "=" * 80)
    print("LATEX SUMMARY TABLE")
    print("=" * 80)
    print(header)
    for row in rows_tex:
        print(row)
    print(footer)
    print("=" * 80)

    # Save to file
    outpath = FIGURES_DIR / f"{output_path}.tex"
    with open(outpath, "w") as f:
        f.write(header + "\n")
        for row in rows_tex:
            f.write(row + "\n")
        f.write(footer + "\n")
    print(f"  LaTeX table saved to: {outpath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compliance Overspill visualization pipeline")
    parser.add_argument("--prefix", type=str, default="",
                        help="Prefix for output filenames (e.g. 'demo')")
    args = parser.parse_args()

    setup_style()

    prefix = args.prefix + "_" if args.prefix else ""

    df = load_eval_data()
    if df.empty:
        print("No evaluation data found in data/4_evaluated/. Run evaluate.py first.")
        return

    n_models = df["model_slug"].nunique()
    n_evals = len(df)
    n_defeats = df["defeat_type"].nunique()
    print(f"Loaded {n_evals} evaluations across {n_models} models, "
          f"{n_defeats} defeat types")
    print(f"Models: {sorted(df['model_slug'].unique())}")
    print(f"Defeat types: {sorted(df['defeat_type'].dropna().unique())}")
    print()

    # Generate all plots
    print("Generating polar grids...")
    plot_polar_grid_by_defeat(df, f"{prefix}polar_grid_by_defeat")
    plot_polar_grid_by_authority(df, f"{prefix}polar_grid_by_authority")

    print("\nGenerating cumulative heatmap...")
    plot_matrix_heatmap_cumulative(df, f"{prefix}matrix_heatmap_cumulative")

    print("\nGenerating per-model heatmaps...")
    plot_matrix_heatmaps_per_model(df, f"{prefix}matrix_heatmaps_per_model")

    print("\nGenerating bar charts...")
    plot_refusal_rates_sorted(df, f"{prefix}refusal_rates_sorted")
    plot_engagement_rates(df, f"{prefix}engagement_rates")
    plot_independent_harm_rates(df, f"{prefix}independent_harm_rates")

    print("\nGenerating summary table...")
    print_summary_table(df, f"{prefix}summary_table")

    print(f"\nAll figures saved to: {FIGURES_DIR}/")


if __name__ == "__main__":
    main()
