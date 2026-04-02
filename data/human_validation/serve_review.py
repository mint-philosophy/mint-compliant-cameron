#!/usr/bin/env python3
"""
Review server for v4 cases with gate results.
Multi-reviewer support with inter-rater reliability.

Run from the v4/ project root and open localhost:8000.

Cases are loaded from per-cell JSON files in data/1_generated/.
Gate results from logs/gate_verdicts/.
"""
from __future__ import annotations

import glob
import json
import os
import http.server

PORT = 8000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CASES_DIR = os.path.join(BASE, "data", "2_filtered")
GATES_DIR = os.path.join(BASE, "logs", "gate_verdicts")
REVIEWS_FILE = os.path.join(SCRIPT_DIR, "reviews.json")
SAMPLE_FILE = os.path.join(SCRIPT_DIR, "sample_ids.json")
REVIEWERS = ["cameron", "lorenzo"]


def load_sample_ids() -> set[str] | None:
    """Load the sample ID list, if it exists. Returns None to use all cases."""
    if not os.path.exists(SAMPLE_FILE):
        return None
    with open(SAMPLE_FILE) as f:
        ids = json.load(f)
    return set(ids)


def load_cases() -> list[dict]:
    """Load cases from all per-cell JSON files in data/1_generated/."""
    all_cases = []
    for filepath in sorted(glob.glob(os.path.join(CASES_DIR, "*.json"))):
        with open(filepath) as f:
            data = json.load(f)

        # Handle both {metadata, cases} and flat array formats
        if isinstance(data, list):
            all_cases.extend(data)
        elif isinstance(data, dict) and "cases" in data:
            all_cases.extend(data["cases"])
        else:
            all_cases.append(data)

    # Filter to sample if sample_ids.json exists
    sample_ids = load_sample_ids()
    if sample_ids is not None:
        all_cases = [c for c in all_cases if c.get("id") in sample_ids]

    return all_cases


def load_reviews() -> dict[str, dict[str, str]]:
    """Load manual review verdicts. Returns {case_id: {reviewer: verdict}}.

    Auto-migrates old format {case_id: verdict_string} -> {case_id: {cameron: verdict}}.
    """
    if not os.path.exists(REVIEWS_FILE):
        return {}
    with open(REVIEWS_FILE) as f:
        data = json.load(f)

    # Auto-migrate old format
    migrated = False
    for key in list(data.keys()):
        if isinstance(data[key], str):
            data[key] = {"cameron": data[key]}
            migrated = True

    if migrated:
        save_reviews(data)

    return data


def save_reviews(reviews: dict[str, dict[str, str]]):
    """Save manual review verdicts."""
    with open(REVIEWS_FILE, "w") as f:
        json.dump(reviews, f, indent=2)


def load_gates() -> dict[str, dict]:
    """
    Load all gate results and index by case_id.
    Returns: {case_id: {ov: {...}, rj: {...}, du: {...}}}

    OV and RJ are loaded from *_full_results.json (dict keyed by case_id).
    DU is loaded from per-cell du_*.json files (arrays of result objects).
    """
    gate_map: dict[str, dict] = {}

    if not os.path.isdir(GATES_DIR):
        return gate_map

    # Load OV and RJ from full_results.json files
    for gate_key, filename in [("ov", "ov_full_results.json"), ("rj", "rj_full_results.json")]:
        filepath = os.path.join(GATES_DIR, filename)
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            results = json.load(f)
        for cid, entry in results.items():
            if cid not in gate_map:
                gate_map[cid] = {}
            reasoning = entry.get("reasoning") or entry.get("overall_reasoning") or ""
            gate_map[cid][gate_key] = {
                "pass": bool(entry.get("pass", False)),
                "reasoning": reasoning,
                "suggested_fix": entry.get("suggested_fix"),
            }

    # Load DU from per-cell files
    for fname in os.listdir(GATES_DIR):
        if not fname.startswith("du_") or not fname.endswith(".json"):
            continue
        filepath = os.path.join(GATES_DIR, fname)
        with open(filepath) as f:
            entries = json.load(f)
        for entry in entries:
            cid = entry.get("case_id")
            if not cid:
                continue
            if cid not in gate_map:
                gate_map[cid] = {}
            gate_map[cid]["du"] = {
                "flagged": entry.get("flagged", entry.get("pass") is False),
                "category": entry.get("category"),
                "reasoning": entry.get("reasoning", ""),
            }

    return gate_map


def load_gate_stats() -> dict:
    """
    Compute per-cell gate failure statistics from full_results.json files.
    Returns: {cell_stem: {ov_total, ov_fail, rj_total, rj_fail, combined_fail_rate}}
    """
    stats: dict[str, dict] = {}

    # Parse cell stem from case_id: seed_{defeat}_{authority}_{N}
    def cell_from_id(cid: str) -> str:
        parts = cid.split("_")
        if parts[0] == "seed":
            parts = parts[1:]
        return "_".join(parts[:-1])

    for gate_key, filename in [("ov", "ov_full_results.json"), ("rj", "rj_full_results.json")]:
        filepath = os.path.join(GATES_DIR, filename)
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            results = json.load(f)
        for cid, entry in results.items():
            cell = cell_from_id(cid)
            if cell not in stats:
                stats[cell] = {"ov_total": 0, "ov_fail": 0, "rj_total": 0, "rj_fail": 0}
            stats[cell][f"{gate_key}_total"] += 1
            if not entry.get("pass", False) or entry.get("error"):
                stats[cell][f"{gate_key}_fail"] += 1

    # Compute combined fail rates
    for cell, s in stats.items():
        total = max(s["ov_total"], s["rj_total"], 1)
        combined_fails = s["ov_fail"] + s["rj_fail"]
        s["combined_fail_rate"] = round(combined_fails / (total * 2) * 100, 1) if total else 0
        s["ov_fail_rate"] = round(s["ov_fail"] / s["ov_total"] * 100, 1) if s["ov_total"] else 0
        s["rj_fail_rate"] = round(s["rj_fail"] / s["rj_total"] * 100, 1) if s["rj_total"] else 0

    return stats


def merge(cases: list[dict], gate_map: dict[str, dict], reviews: dict[str, dict[str, str]]) -> list[dict]:
    """Augment each case with gate results and manual reviews."""
    empty_blocking = {"pass": None, "reasoning": "", "suggested_fix": None}
    empty_du = {"flagged": None, "category": None, "reasoning": ""}

    for case in cases:
        cid = case.get("id", "")
        gates_for_case = gate_map.get(cid, {})

        ov = gates_for_case.get("ov", empty_blocking)
        rj = gates_for_case.get("rj", empty_blocking)
        du = gates_for_case.get("du", empty_du)

        all_pass = (
            ov.get("pass") is True
            and rj.get("pass") is True
        )

        case["gates"] = {
            "ov": ov,
            "rj": rj,
            "du": du,
            "all_pass": all_pass,
        }

        # Attach all reviewer verdicts
        if cid in reviews:
            case["manual_reviews"] = reviews[cid]

    return cases


def compute_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Compute Cohen's kappa for a list of (rater1, rater2) verdict pairs (binary: pass/fail)."""
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    po = agree / n

    n1_pass = sum(1 for a, _ in pairs if a == "pass")
    n2_pass = sum(1 for _, b in pairs if b == "pass")
    pe = (n1_pass * n2_pass + (n - n1_pass) * (n - n2_pass)) / (n * n)

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


class ReviewHandler(http.server.BaseHTTPRequestHandler):

    # Class-level cache — loaded once on first request
    _cases: list[dict] | None = None

    @classmethod
    def get_cases(cls) -> list[dict]:
        if cls._cases is None:
            raw = load_cases()
            gates = load_gates()
            reviews = load_reviews()
            cls._cases = merge(raw, gates, reviews)
        return cls._cases

    @classmethod
    def reload_cases(cls) -> list[dict]:
        """Force reload from disk (after writing)."""
        cls._cases = None
        return cls.get_cases()

    # ── Routing ──────────────────────────────────────────────

    def do_GET(self):
        if self.path == "/":
            self.serve_html()
        elif self.path == "/api/cases":
            self.send_cases()
        elif self.path == "/api/export":
            self.send_export()
        elif self.path == "/api/irr":
            self.send_irr()
        elif self.path == "/api/gate_stats":
            self.send_json(load_gate_stats())
        elif self.path == "/api/reviewers":
            self.send_json({"reviewers": REVIEWERS})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/review":
            self.handle_review()
        elif self.path == "/api/reload":
            self.handle_reload()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Handlers ─────────────────────────────────────────────

    def serve_html(self):
        html_path = os.path.join(SCRIPT_DIR, "review.html")
        if not os.path.exists(html_path):
            self.send_error(404, "review.html not found in project root")
            return
        with open(html_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_cases(self):
        # Reload reviews fresh to pick up other reviewer's changes
        reviews = load_reviews()
        cases = self.get_cases()
        for case in cases:
            cid = case.get("id", "")
            if cid in reviews:
                case["manual_reviews"] = reviews[cid]
            elif "manual_reviews" in case:
                del case["manual_reviews"]
        self.send_json(cases)

    def send_export(self):
        """Return all cases (merged from per-cell files) with reviews."""
        cases = load_cases()
        reviews = load_reviews()
        for case in cases:
            cid = case.get("id", "")
            if cid in reviews:
                case["manual_reviews"] = reviews[cid]
        self.send_json(cases)

    def handle_reload(self):
        """Force reload all data from disk."""
        cases = self.reload_cases()
        self.send_json({"ok": True, "total": len(cases)})

    def handle_review(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        case_id = body.get("case_id")
        verdict = body.get("verdict")
        reviewer = body.get("reviewer")
        confound = body.get("confound")
        note = body.get("note")
        q_defeated = body.get("q_defeated")
        q_classified = body.get("q_classified")
        q_natural = body.get("q_natural")

        if not case_id:
            self.send_json_error(400, "Missing case_id")
            return
        if reviewer not in REVIEWERS:
            self.send_json_error(400, f"reviewer must be one of {REVIEWERS}")
            return

        # Save to reviews.json
        reviews = load_reviews()
        if case_id not in reviews:
            reviews[case_id] = {}

        # Store verdict if provided
        if verdict is not None:
            if verdict not in ("pass", "fail"):
                self.send_json_error(400, "verdict must be 'pass' or 'fail'")
                return
            reviews[case_id][reviewer] = verdict

        # Store confound flag if provided
        if confound is not None:
            reviews[case_id][reviewer + "_confound"] = bool(confound)

        # Store note if provided
        if note is not None:
            reviews[case_id][reviewer + "_note"] = str(note)

        # Store question answers if provided
        if q_defeated is not None:
            reviews[case_id][reviewer + "_q_defeated"] = bool(q_defeated)
        if q_classified is not None:
            reviews[case_id][reviewer + "_q_classified"] = bool(q_classified)
        if q_natural is not None:
            reviews[case_id][reviewer + "_q_natural"] = bool(q_natural)

        save_reviews(reviews)

        # Update in-memory cache
        for case in self.get_cases():
            if case.get("id") == case_id:
                case["manual_reviews"] = reviews[case_id]
                break

        self.send_json({"ok": True, "case_id": case_id, "verdict": verdict, "reviewer": reviewer})

    def send_irr(self):
        """Compute and return inter-rater reliability stats."""
        reviews = load_reviews()
        pairs = []
        disagreements = []

        for case_id, reviewer_verdicts in reviews.items():
            r1 = reviewer_verdicts.get(REVIEWERS[0])
            r2 = reviewer_verdicts.get(REVIEWERS[1])
            if r1 and r2:
                pairs.append((r1, r2))
                if r1 != r2:
                    disagreements.append({
                        "case_id": case_id,
                        REVIEWERS[0]: r1,
                        REVIEWERS[1]: r2,
                    })

        kappa = compute_kappa(pairs)
        n_dual = len(pairs)
        agreement_pct = round(
            sum(1 for a, b in pairs if a == b) / n_dual * 100, 1
        ) if n_dual > 0 else None

        self.send_json({
            "kappa": round(kappa, 4) if kappa is not None else None,
            "kappa_label": kappa_label(kappa),
            "agreement_pct": agreement_pct,
            "n_dual": n_dual,
            "disagreements": disagreements,
            "reviewers": REVIEWERS,
            "counts": {
                r: sum(1 for rv in reviews.values() if r in rv)
                for r in REVIEWERS
            },
        })

    # ── Helpers ──────────────────────────────────────────────

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, code: int, message: str):
        body = json.dumps({"error": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quiet logging — only show API calls
        msg = args[0] if args else ""
        if "/api/" in str(msg):
            super().log_message(format, *args)


if __name__ == "__main__":
    sample_ids = load_sample_ids()
    print(f"Review server at http://localhost:{PORT}")
    print(f"Project root: {BASE}")
    print(f"Cases dir: {CASES_DIR} (filtered dataset)")
    print(f"Gates dir: {GATES_DIR}")
    if sample_ids:
        print(f"Sample: {len(sample_ids)} cases (from sample_ids.json)")
    else:
        print("Sample: ALL cases (no sample_ids.json)")
    print(f"Reviewers: {REVIEWERS}")
    print("Press Ctrl+C to stop.\n")
    http.server.HTTPServer.allow_reuse_address = True
    with http.server.HTTPServer(("", PORT), ReviewHandler) as srv:
        srv.serve_forever()
