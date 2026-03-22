#!/usr/bin/env python3
"""
Evaluation review server for v4 compliance overspill research.
Multi-reviewer support with inter-rater reliability (category-level + group-level kappa).

Serves eval_review.html and provides API endpoints for reviewing
LLM judge evaluations of model responses.

Run from the v4/ project root and open localhost:8001.

Data sources:
  - data/4_evaluated/{model_slug}_{defeat_type}_{authority_type}.json
  - data/1_generated/{defeat_type}_{authority_type}.json
  - data/3_responses/{model_slug}_{defeat_type}_{authority_type}.json
  - data/eval_reviews.json  (human overrides, multi-reviewer)
"""
from __future__ import annotations

import glob
import json
import os
import http.server
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PORT = 8001
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
EVALUATED_DIR = os.path.join(BASE, "data", "4_evaluated")
CASES_DIR = os.path.join(BASE, "data", "1_generated")
RESPONSES_DIR = os.path.join(BASE, "data", "3_responses")
REVIEWS_FILE = os.path.join(SCRIPT_DIR, "eval_reviews.json")
REVIEWERS = ["cameron", "lorenzo"]

# Known defeat type tokens — sorted longest-first to prevent greedy short matches
DEFEAT_TYPES = sorted([
    "application_defeat",
    "content_defeat",
    "exception_justified",
    "illegitimate_authority",
    "control",
], key=len, reverse=True)

# v5 taxonomy — 2 dimensions: response_type and acknowledges_defeat
ALL_RESPONSE_TYPES = ["helps", "hard_refusal", "deflects"]
ALL_ACKNOWLEDGES_DEFEAT = ["yes", "no"]

# Backward-compat aliases used by stats/kappa code
ALL_CATEGORIES = ALL_RESPONSE_TYPES
ALL_GROUPS = ALL_ACKNOWLEDGES_DEFEAT


def parse_file_stem(stem: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse a file stem like 'claude-opus-4-6_application_defeat_club'
    into (model_slug, defeat_type, authority_type).

    DEFEAT_TYPES is sorted longest-first so 'illegitimate_authority'
    is tried before 'control', preventing greedy short matches.

    Returns None if parsing fails.
    """
    for dt in DEFEAT_TYPES:
        idx = stem.find(dt)
        if idx == -1:
            continue

        model_slug = stem[:idx].rstrip("_")
        authority_type = stem[idx + len(dt):].lstrip("_")

        if model_slug and authority_type:
            return model_slug, dt, authority_type

    return None


def load_cases_for_cell(defeat_type: str, authority_type: str) -> Dict[str, dict]:
    """
    Load original cases from data/1_generated/{defeat_type}_{authority_type}.json.
    Returns a dict keyed by case_id.
    """
    filepath = os.path.join(CASES_DIR, f"{defeat_type}_{authority_type}.json")
    if not os.path.exists(filepath):
        return {}

    with open(filepath) as f:
        data = json.load(f)

    cases = []
    if isinstance(data, list):
        cases = data
    elif isinstance(data, dict) and "cases" in data:
        cases = data["cases"]
    else:
        cases = [data]

    return {c["id"]: c for c in cases if c.get("id")}


def load_responses_for_cell(
    model_slug: str, defeat_type: str, authority_type: str
) -> Dict[str, dict]:
    """
    Load raw responses from data/3_responses/{model_slug}_{defeat_type}_{authority_type}.json.
    Returns a dict keyed by case_id.
    """
    filepath = os.path.join(
        RESPONSES_DIR, f"{model_slug}_{defeat_type}_{authority_type}.json"
    )
    if not os.path.exists(filepath):
        return {}

    with open(filepath) as f:
        data = json.load(f)

    responses = data.get("responses", []) if isinstance(data, dict) else data
    return {r["case_id"]: r for r in responses if r.get("case_id")}


def load_reviews() -> Dict[str, Dict[str, dict]]:
    """Load human review overrides. Returns {review_key: {reviewer: review_data}}.

    Auto-migrates old format {review_key: {human_category, ...}} to
    {review_key: {cameron: {human_category, ...}}}.
    """
    if not os.path.exists(REVIEWS_FILE):
        return {}
    try:
        with open(REVIEWS_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

    # Auto-migrate old format: detect by presence of "human_category" at top level of value
    migrated = False
    for key in list(data.keys()):
        value = data[key]
        if isinstance(value, dict) and "human_category" in value:
            # Old format — wrap under cameron
            data[key] = {"cameron": value}
            migrated = True

    if migrated:
        save_reviews(data)

    return data


def save_reviews(reviews: Dict[str, Dict[str, dict]]) -> None:
    """Save human review overrides to eval_reviews.json."""
    with open(REVIEWS_FILE, "w") as f:
        json.dump(reviews, f, indent=2)


def load_all_evaluations() -> List[dict]:
    """
    Load all evaluated files, merge with original case data and full responses.
    Returns a list of merged evaluation objects ready for the frontend.
    """
    all_evals: List[dict] = []

    if not os.path.isdir(EVALUATED_DIR):
        return all_evals

    # Cache for case and response data to avoid re-loading per evaluation
    case_cache: Dict[str, Dict[str, dict]] = {}
    response_cache: Dict[str, Dict[str, dict]] = {}
    reviews = load_reviews()  # load once, not per-file

    for filepath in sorted(glob.glob(os.path.join(EVALUATED_DIR, "*.json"))):
        fname = os.path.basename(filepath)
        stem = fname[:-5]  # remove .json

        parsed = parse_file_stem(stem)
        if parsed is None:
            continue

        model_slug, defeat_type, authority_type = parsed

        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        evaluations = data.get("evaluations", [])
        metadata = data.get("metadata", {})

        # Load cases for this cell (cached)
        cell_key = f"{defeat_type}_{authority_type}"
        if cell_key not in case_cache:
            case_cache[cell_key] = load_cases_for_cell(defeat_type, authority_type)
        cases = case_cache[cell_key]

        # Load responses for this cell (cached)
        resp_key = f"{model_slug}_{defeat_type}_{authority_type}"
        if resp_key not in response_cache:
            response_cache[resp_key] = load_responses_for_cell(
                model_slug, defeat_type, authority_type
            )
        responses = response_cache[resp_key]

        for ev in evaluations:
            case_id = ev.get("case_id", "")
            model_id = ev.get("model", metadata.get("evaluated_model", ""))
            evaluation = ev.get("evaluation", {})
            gate_flags = ev.get("gate_flags", {})
            response_preview = ev.get("response_preview", "")

            # Look up original case
            original_case = cases.get(case_id, {})

            # Look up full response
            response_entry = responses.get(case_id, {})
            full_response = response_entry.get("response", response_preview)

            # Compute review key
            review_key = f"{case_id}__{model_slug}"
            reviewer_reviews = reviews.get(review_key, {})

            # v5 taxonomy fields
            category = evaluation.get("response_type", "deflects")
            ack_defeat = evaluation.get("acknowledges_defeat", "no")

            merged = {
                "case_id": case_id,
                "model": model_id,
                "model_slug": model_slug,
                "defeat_type": defeat_type,
                "authority_type": authority_type,
                # Original case context
                "unjust_policy": original_case.get(
                    "unjust_policy",
                    original_case.get("scenario_spec", {}).get("unjust_policy", ""),
                ),
                "defeat_condition": original_case.get(
                    "defeat_condition",
                    original_case.get("scenario_spec", {}).get(
                        "defeat_condition", ""
                    ),
                ),
                "structural_facts": original_case.get(
                    "structural_facts",
                    original_case.get("scenario_spec", {}).get(
                        "structural_facts", []
                    ),
                ),
                "user_query": original_case.get("user_query", ""),
                "dimensional_coding": original_case.get("dimensional_coding", {}),
                "defeat_subtype": original_case.get("defeat_subtype", ""),
                "authority_group": original_case.get("authority_group", ""),
                # Full response
                "full_response": full_response,
                # Evaluation data
                "evaluation": evaluation,
                "response_type": category,
                "acknowledges_defeat": ack_defeat,
                "gate_flags": gate_flags,
                "response_preview": response_preview,
                # Evaluator metadata
                "evaluator_model": metadata.get("evaluator_model", ""),
                # Human reviews (all reviewers)
                "human_reviews": reviewer_reviews,
                "review_key": review_key,
            }

            all_evals.append(merged)

    return all_evals


def compute_stats(evaluations: List[dict], reviews: Dict[str, Dict[str, dict]]) -> dict:
    """Compute summary statistics for the stats endpoint."""
    total = len(evaluations)

    # Per-reviewer counts
    reviewer_counts: Dict[str, int] = {r: 0 for r in REVIEWERS}
    for e in evaluations:
        rk = e.get("review_key", "")
        rv = reviews.get(rk, {})
        for r in REVIEWERS:
            if r in rv:
                reviewer_counts[r] += 1

    reviewed = sum(1 for e in evaluations if reviews.get(e.get("review_key", ""), {}))

    # Response type counts
    category_counts: Dict[str, int] = {}
    for e in evaluations:
        cat = e.get("evaluation", {}).get("response_type", "deflects")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Model counts
    model_counts: Dict[str, int] = {}
    for e in evaluations:
        m = e.get("model_slug", "unknown")
        model_counts[m] = model_counts.get(m, 0) + 1

    # Defeat type counts
    defeat_counts: Dict[str, int] = {}
    for e in evaluations:
        dt = e.get("defeat_type", "unknown")
        defeat_counts[dt] = defeat_counts.get(dt, 0) + 1

    # Acknowledges defeat counts
    group_counts: Dict[str, int] = {}
    for e in evaluations:
        g = e.get("evaluation", {}).get("acknowledges_defeat", "no")
        group_counts[g] = group_counts.get(g, 0) + 1

    # Response type counts by model
    category_by_model: Dict[str, Dict[str, int]] = {}
    for e in evaluations:
        m = e.get("model_slug", "unknown")
        cat = e.get("evaluation", {}).get("response_type", "deflects")
        if m not in category_by_model:
            category_by_model[m] = {}
        category_by_model[m][cat] = category_by_model[m].get(cat, 0) + 1

    return {
        "total": total,
        "reviewed": reviewed,
        "reviewer_counts": reviewer_counts,
        "category_counts": category_counts,
        "model_counts": model_counts,
        "defeat_type_counts": defeat_counts,
        "group_counts": group_counts,
        "category_by_model": category_by_model,
    }


def compute_multi_kappa(pairs: list[tuple[str, str]], categories: list[str]) -> float | None:
    """Compute Cohen's kappa for multi-category ratings."""
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    po = agree / n

    # Expected agreement under independence
    pe = 0.0
    for cat in categories:
        p1 = sum(1 for a, _ in pairs if a == cat) / n
        p2 = sum(1 for _, b in pairs if b == cat) / n
        pe += p1 * p2

    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def kappa_label(k: float | None) -> str:
    """Landis & Koch qualitative label for kappa values."""
    if k is None:
        return "N/A"
    if k < 0:
        return "Poor"
    if k < 0.21:
        return "Slight"
    if k < 0.41:
        return "Fair"
    if k < 0.61:
        return "Moderate"
    if k < 0.81:
        return "Substantial"
    return "Almost Perfect"


class EvalReviewHandler(http.server.BaseHTTPRequestHandler):

    # Class-level cache
    _evaluations: Optional[List[dict]] = None

    @classmethod
    def get_evaluations(cls) -> List[dict]:
        if cls._evaluations is None:
            cls._evaluations = load_all_evaluations()
        return cls._evaluations

    @classmethod
    def reload_evaluations(cls) -> List[dict]:
        """Force reload from disk."""
        cls._evaluations = None
        return cls.get_evaluations()

    # -- Routing --

    def do_GET(self) -> None:
        try:
            if self.path == "/":
                self._serve_html()
            elif self.path == "/api/evaluations":
                self._send_evaluations()
            elif self.path == "/api/export":
                self._send_export()
            elif self.path == "/api/stats":
                self._send_stats()
            elif self.path == "/api/irr":
                self._send_irr()
            elif self.path == "/api/reviewers":
                self._send_json({"reviewers": REVIEWERS})
            else:
                self.send_error(404)
        except Exception:
            traceback.print_exc()
            self._send_error_json(500, "Internal server error")

    def do_POST(self) -> None:
        try:
            if self.path == "/api/review":
                self._handle_review()
            elif self.path == "/api/reload":
                self._handle_reload()
            else:
                self.send_error(404)
        except Exception:
            traceback.print_exc()
            self._send_error_json(500, "Internal server error")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # -- Handlers --

    def _serve_html(self) -> None:
        html_path = os.path.join(SCRIPT_DIR, "eval_review.html")
        if not os.path.exists(html_path):
            self.send_error(404, "eval_review.html not found in project root")
            return
        with open(html_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_evaluations(self) -> None:
        evals = self.get_evaluations()
        reviews = load_reviews()
        # Build response with latest reviews without mutating cache
        result = []
        for e in evals:
            merged = dict(e)  # shallow copy to avoid mutating cache
            merged["human_reviews"] = reviews.get(e.get("review_key", ""), {})
            result.append(merged)
        self._send_json(result)

    def _send_export(self) -> None:
        """Return all evaluations with human reviews merged for export."""
        # Reload fresh to include any recent reviews
        evals = self.reload_evaluations()
        reviews = load_reviews()
        result = []
        for e in evals:
            merged = dict(e)
            rk = merged.get("review_key", "")
            merged["human_reviews"] = reviews.get(rk, {})
            result.append(merged)
        self._send_json({
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total": len(result),
            "evaluations": result,
        })

    def _send_stats(self) -> None:
        evals = self.get_evaluations()
        reviews = load_reviews()
        # Build temporary list with latest reviews for stats computation
        evals_with_reviews = []
        for e in evals:
            merged = dict(e)
            merged["human_reviews"] = reviews.get(e.get("review_key", ""), {})
            evals_with_reviews.append(merged)
        stats = compute_stats(evals_with_reviews, reviews)
        self._send_json(stats)

    def _handle_review(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        case_id = body.get("case_id")
        model_slug = body.get("model_slug")
        human_category = body.get("human_category")
        human_acknowledges_defeat = body.get("human_acknowledges_defeat", "agree")
        human_notes = body.get("human_notes", "")
        reviewer = body.get("reviewer")

        if not case_id or not model_slug or not human_category:
            self._send_error_json(
                400, "Missing required fields: case_id, model_slug, human_category"
            )
            return

        if reviewer not in REVIEWERS:
            self._send_error_json(400, f"reviewer must be one of {REVIEWERS}")
            return

        review_key = f"{case_id}__{model_slug}"
        reviews = load_reviews()
        if review_key not in reviews:
            reviews[review_key] = {}
        reviews[review_key][reviewer] = {
            "human_category": human_category,
            "human_acknowledges_defeat": human_acknowledges_defeat,
            "human_notes": human_notes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        save_reviews(reviews)

        # Update in-memory cache
        for e in self.get_evaluations():
            if e.get("review_key") == review_key:
                e["human_reviews"] = reviews[review_key]
                break

        self._send_json({
            "ok": True,
            "review_key": review_key,
            "human_category": human_category,
            "reviewer": reviewer,
        })

    def _handle_reload(self) -> None:
        """Force reload all data from disk."""
        evals = self.reload_evaluations()
        self._send_json({"ok": True, "total": len(evals)})

    def _send_irr(self) -> None:
        """Compute inter-rater reliability between the two human reviewers.

        For each evaluation reviewed by both, resolve effective values
        ("agree" maps to the LLM's value) and compute:
        - Response-type kappa (3 values: helps, hard_refusal, deflects)
        - Acknowledges-defeat kappa (2 values: yes, no)
        """
        reviews = load_reviews()
        evals = self.get_evaluations()

        # Build lookup: review_key -> LLM response_type and acknowledges_defeat
        llm_response_types: Dict[str, str] = {}
        llm_ack_defeats: Dict[str, str] = {}
        for e in evals:
            rk = e.get("review_key", "")
            llm_response_types[rk] = (e.get("evaluation") or {}).get("response_type", "deflects")
            llm_ack_defeats[rk] = (e.get("evaluation") or {}).get("acknowledges_defeat", "no")

        category_pairs: list[tuple[str, str]] = []
        group_pairs: list[tuple[str, str]] = []
        disagreements: list[dict] = []

        for review_key, reviewer_data in reviews.items():
            r1_data = reviewer_data.get(REVIEWERS[0])
            r2_data = reviewer_data.get(REVIEWERS[1])
            if not r1_data or not r2_data:
                continue

            llm_cat = llm_response_types.get(review_key, "deflects")
            llm_ack = llm_ack_defeats.get(review_key, "no")

            # Resolve effective response_type
            r1_cat = r1_data["human_category"]
            if r1_cat == "agree":
                r1_cat = llm_cat
            r2_cat = r2_data["human_category"]
            if r2_cat == "agree":
                r2_cat = llm_cat

            category_pairs.append((r1_cat, r2_cat))

            # Resolve effective acknowledges_defeat
            r1_ack = r1_data.get("human_acknowledges_defeat", "agree")
            if r1_ack == "agree":
                r1_ack = llm_ack
            r2_ack = r2_data.get("human_acknowledges_defeat", "agree")
            if r2_ack == "agree":
                r2_ack = llm_ack
            group_pairs.append((r1_ack, r2_ack))

            if r1_cat != r2_cat:
                disagreements.append({
                    "review_key": review_key,
                    REVIEWERS[0]: r1_cat,
                    REVIEWERS[1]: r2_cat,
                })

        n_dual = len(category_pairs)
        category_kappa = compute_multi_kappa(category_pairs, ALL_CATEGORIES)
        group_kappa = compute_multi_kappa(group_pairs, ALL_GROUPS)

        agreement_pct = round(
            sum(1 for a, b in category_pairs if a == b) / n_dual * 100, 1
        ) if n_dual > 0 else None

        group_agreement_pct = round(
            sum(1 for a, b in group_pairs if a == b) / n_dual * 100, 1
        ) if n_dual > 0 else None

        self._send_json({
            "category_kappa": round(category_kappa, 4) if category_kappa is not None else None,
            "category_kappa_label": kappa_label(category_kappa),
            "group_kappa": round(group_kappa, 4) if group_kappa is not None else None,
            "group_kappa_label": kappa_label(group_kappa),
            "agreement_pct": agreement_pct,
            "group_agreement_pct": group_agreement_pct,
            "n_dual": n_dual,
            "disagreements": disagreements,
            "reviewers": REVIEWERS,
            "counts": {
                r: sum(1 for rv in reviews.values() if r in rv)
                for r in REVIEWERS
            },
        })

    # -- Helpers --

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, code: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        msg = args[0] if args else ""
        if "/api/" in str(msg):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Evaluation review server at http://localhost:{PORT}")
    print(f"Project root: {BASE}")
    print(f"Evaluated dir: {EVALUATED_DIR}")
    print(f"Cases dir: {CASES_DIR}")
    print(f"Responses dir: {RESPONSES_DIR}")
    print(f"Reviews file: {REVIEWS_FILE}")
    print(f"Reviewers: {REVIEWERS}")
    print("Press Ctrl+C to stop.\n")

    http.server.HTTPServer.allow_reuse_address = True
    with http.server.HTTPServer(("", PORT), EvalReviewHandler) as srv:
        srv.serve_forever()
