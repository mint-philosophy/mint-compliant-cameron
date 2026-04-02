#!/usr/bin/env python3
"""
Audit collection data for 6 completed models in the compliance overspill project.
Checks: completeness, schema, response quality, usage data, case ID coverage.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path("/Users/cameronpattison/Documents/Academic Documents/2025-6/playground/evading_unjust_policy/v4")
FILTERED_DIR = PROJECT_ROOT / "data" / "2_filtered"
RESPONSES_DIR = PROJECT_ROOT / "data" / "3_responses"
OUTPUT_PATH = PROJECT_ROOT / "logs" / "collection_audit_complete_models.json"

MODELS = [
    "claude-sonnet-4-6",
    "gemini-3-1-flash-lite",
    "gpt-5-4-mini-thinking",
    "gpt-5-4-nano-thinking",
    "grok-4-fast",
    "nemotron-3-nano",
]

REQUIRED_FIELDS = [
    "case_id", "model", "user_query", "response",
    "timestamp", "status", "error_message", "gate_flags", "usage"
]

# Patterns that indicate a response IS an error message (not just mentioning errors).
# Only flag if the response is short (<300 chars) AND matches one of these,
# OR if the entire response matches a known API error format.
STRICT_ERROR_PATTERNS = [
    r"^[\s]*\{.*\"error\"",                  # Raw JSON error
    r"^[\s]*Error:",                          # Starts with "Error:"
    r"^[\s]*API error",                       # Starts with API error
    r"^[\s]*503 Service",
    r"^[\s]*502 Bad Gateway",
    r"^[\s]*429 Too Many",
    r"^[\s]*Connection refused",
    r"^[\s]*Internal Server Error",
    r"OPENROUTER",                            # Infrastructure leak
    r"^[\s]*upstream error",
]

# Broader patterns checked only on short responses (<300 chars)
SOFT_ERROR_PATTERNS = [
    r"API error",
    r"rate limit(?:ed)?",
    r"internal server error",
    r"503 Service",
    r"502 Bad Gateway",
    r"429 Too Many",
    r"Connection refused",
    r"timed? ?out",
    r"upstream error",
]


def load_filtered_case_ids() -> dict[str, set[str]]:
    """Load all case IDs from filtered dataset, grouped by scenario file key."""
    all_ids = set()
    per_file = {}
    for fname in sorted(os.listdir(FILTERED_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = FILTERED_DIR / fname
        with open(fpath) as f:
            data = json.load(f)
        key = fname.replace(".json", "")
        ids = {c["id"] for c in data["cases"]}
        per_file[key] = ids
        all_ids.update(ids)
    return per_file, all_ids


def load_model_responses(model_slug: str) -> tuple[list[dict], list[Path]]:
    """Load all response records for a model, returning (responses, file_paths)."""
    responses = []
    files = []
    for fname in sorted(os.listdir(RESPONSES_DIR)):
        if not fname.startswith(model_slug + "_") or not fname.endswith(".json"):
            continue
        fpath = RESPONSES_DIR / fname
        files.append(fpath)
        with open(fpath) as f:
            data = json.load(f)
        for r in data.get("responses", []):
            responses.append(r)
    return responses, files


def parse_case_id(case_id: str) -> tuple[str | None, str | None]:
    """Extract defeat_type and authority_type from case_id.

    Patterns:
      seed_{defeat_type}_{authority_type}_{number}
      supplement_{defeat_type}_{authority_type}_{number}

    defeat_types: application_defeat, content_defeat, control,
                  exception_justified, illegitimate_authority
    authority_types: algorithmic_intermediary, club, contractual_counterparty,
                     creditor_insurer, delegated_authority, faith_group, family,
                     housing_association, landlord, military_command, national_government,
                     private_property_owner, profession, school, subnational_government,
                     supranational_body, tribe, union, workplace
    """
    DEFEAT_TYPES = [
        "application_defeat", "content_defeat", "control",
        "exception_justified", "illegitimate_authority"
    ]
    AUTHORITY_TYPES = [
        "algorithmic_intermediary", "club", "contractual_counterparty",
        "creditor_insurer", "delegated_authority", "faith_group", "family",
        "housing_association", "landlord", "military_command", "national_government",
        "private_property_owner", "profession", "school", "subnational_government",
        "supranational_body", "tribe", "union", "workplace"
    ]

    # Strip prefix (seed_ or supplement_)
    rest = case_id
    for prefix in ("seed_", "supplement_"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break

    # Try to match defeat_type
    found_defeat = None
    for dt in sorted(DEFEAT_TYPES, key=len, reverse=True):
        if rest.startswith(dt + "_"):
            found_defeat = dt
            rest = rest[len(dt) + 1:]
            break

    # Try to match authority_type
    found_auth = None
    for at in sorted(AUTHORITY_TYPES, key=len, reverse=True):
        if rest.startswith(at):
            found_auth = at
            break

    return found_defeat, found_auth


def audit_model(model_slug: str, per_file_ids: dict[str, set[str]], all_case_ids: set[str]) -> dict:
    """Run all audit checks for a single model."""
    responses, files = load_model_responses(model_slug)

    result = {
        "files": len(files),
        "total_responses": len(responses),
        "successful": 0,
        "errors": 0,
        "error_case_ids": [],
        "missing_cases": [],
        "schema_issues": [],
        "null_user_query": [],
        "null_usage": [],
        "short_responses": [],
        "error_like_responses": [],
        "duplicate_responses": [],
        "avg_response_length_chars": 0,
        "usage_coverage": "",
        "avg_input_tokens": 0,
        "avg_output_tokens": 0,
        "avg_reasoning_tokens": 0,
        "suspicious_token_counts": [],
        "defeat_types_found": [],
        "authority_types_found": [],
        "defeat_type_counts": {},
        "authority_type_counts": {},
        "coverage_gaps": [],
        "pass": True,
        "issues": [],
    }

    # ── 1. Response completeness ──
    seen_case_ids = set()
    successful_responses = []

    for r in responses:
        cid = r.get("case_id")
        if cid:
            seen_case_ids.add(cid)

        status = r.get("status", "")
        if status == "success":
            result["successful"] += 1
            successful_responses.append(r)
        else:
            result["errors"] += 1
            result["error_case_ids"].append(cid)

    # Missing cases
    missing = sorted(all_case_ids - seen_case_ids)
    result["missing_cases"] = missing
    if missing:
        result["issues"].append(f"{len(missing)} cases missing from responses")

    # ── 2. Schema check ──
    for r in responses:
        missing_fields = [f for f in REQUIRED_FIELDS if f not in r]
        if missing_fields:
            result["schema_issues"].append({
                "case_id": r.get("case_id", "UNKNOWN"),
                "missing_fields": missing_fields
            })

        if r.get("user_query") is None:
            result["null_user_query"].append(r.get("case_id", "UNKNOWN"))

        if r.get("usage") is None and r.get("status") == "success":
            result["null_usage"].append(r.get("case_id", "UNKNOWN"))

    if result["schema_issues"]:
        result["issues"].append(f"{len(result['schema_issues'])} records with missing fields")
    if result["null_user_query"]:
        result["issues"].append(f"{len(result['null_user_query'])} records with null user_query")
    if result["null_usage"]:
        result["issues"].append(f"{len(result['null_usage'])} successful records with null usage")

    # ── 3. Response quality ──
    response_lengths = []
    response_texts = []

    for r in successful_responses:
        text = r.get("response", "") or ""
        rlen = len(text)
        response_lengths.append(rlen)
        response_texts.append(text)

        # Short responses
        if rlen < 50:
            result["short_responses"].append({
                "case_id": r.get("case_id"),
                "length": rlen,
                "text_preview": text[:100]
            })

        # Error-like responses: strict patterns always checked,
        # soft patterns only on short responses
        flagged = False
        for pat in STRICT_ERROR_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                result["error_like_responses"].append({
                    "case_id": r.get("case_id"),
                    "matched_pattern": pat,
                    "text_preview": text[:200],
                    "severity": "high"
                })
                flagged = True
                break
        if not flagged and rlen < 300:
            for pat in SOFT_ERROR_PATTERNS:
                if re.search(pat, text, re.IGNORECASE):
                    result["error_like_responses"].append({
                        "case_id": r.get("case_id"),
                        "matched_pattern": pat,
                        "text_preview": text[:200],
                        "severity": "low"
                    })
                    break

    if response_lengths:
        result["avg_response_length_chars"] = round(sum(response_lengths) / len(response_lengths), 1)

    # Exact duplicate responses
    text_counter = Counter(response_texts)
    for text, count in text_counter.items():
        if count > 1:
            # Find all case_ids with this exact text
            dup_ids = [r.get("case_id") for r in successful_responses if (r.get("response") or "") == text]
            result["duplicate_responses"].append({
                "count": count,
                "case_ids": dup_ids,
                "text_preview": text[:150]
            })

    if result["short_responses"]:
        result["issues"].append(f"WARNING: {len(result['short_responses'])} responses under 50 chars (likely refusals)")
    if result["error_like_responses"]:
        high = sum(1 for e in result["error_like_responses"] if e.get("severity") == "high")
        low = sum(1 for e in result["error_like_responses"] if e.get("severity") == "low")
        parts = []
        if high:
            parts.append(f"{high} high-severity")
        if low:
            parts.append(f"{low} low-severity")
        result["issues"].append(f"{'FAIL' if high else 'WARNING'}: {' + '.join(parts)} error-like responses")
    if result["duplicate_responses"]:
        total_dups = sum(d["count"] for d in result["duplicate_responses"])
        result["issues"].append(f"WARNING: {len(result['duplicate_responses'])} duplicate response groups ({total_dups} total responses)")

    # ── 4. Usage data ──
    input_tokens = []
    output_tokens = []
    reasoning_tokens = []
    suspicious = []
    usage_present = 0

    for r in successful_responses:
        usage = r.get("usage")
        if usage is None:
            continue
        usage_present += 1

        pt = usage.get("prompt_tokens", 0) or 0
        ct = usage.get("completion_tokens", 0) or 0
        rt = usage.get("reasoning_tokens", 0) or 0
        vt = usage.get("visible_tokens", 0) or 0

        input_tokens.append(pt)
        output_tokens.append(ct)
        reasoning_tokens.append(rt)

        # Suspicious: very low input (< 20) or very high output (> 5000 visible)
        if pt < 20 and pt > 0:
            suspicious.append({
                "case_id": r.get("case_id"),
                "issue": f"Very low input tokens: {pt}"
            })
        if vt > 5000:
            suspicious.append({
                "case_id": r.get("case_id"),
                "issue": f"Very high visible output tokens: {vt}"
            })
        if ct == 0:
            suspicious.append({
                "case_id": r.get("case_id"),
                "issue": f"Zero completion tokens"
            })

    if result["successful"] > 0:
        result["usage_coverage"] = f"{usage_present}/{result['successful']}"
        if usage_present < result["successful"]:
            result["issues"].append(f"Only {usage_present}/{result['successful']} successful responses have usage data")
    else:
        result["usage_coverage"] = "0/0"

    if input_tokens:
        result["avg_input_tokens"] = round(sum(input_tokens) / len(input_tokens), 1)
    if output_tokens:
        result["avg_output_tokens"] = round(sum(output_tokens) / len(output_tokens), 1)
    if reasoning_tokens:
        result["avg_reasoning_tokens"] = round(sum(reasoning_tokens) / len(reasoning_tokens), 1)

    result["suspicious_token_counts"] = suspicious
    if suspicious:
        result["issues"].append(f"{len(suspicious)} suspicious token counts")

    # ── 5. Case ID verification ──
    defeat_types = set()
    authority_types = set()
    dt_counts = Counter()
    at_counts = Counter()
    parse_failures = []

    for r in responses:
        cid = r.get("case_id", "")
        dt, at = parse_case_id(cid)
        if dt is None or at is None:
            parse_failures.append(cid)
        else:
            defeat_types.add(dt)
            authority_types.add(at)
            dt_counts[dt] += 1
            at_counts[at] += 1

    EXPECTED_DEFEAT_TYPES = {
        "application_defeat", "content_defeat", "control",
        "exception_justified", "illegitimate_authority"
    }
    EXPECTED_AUTHORITY_TYPES = {
        "algorithmic_intermediary", "club", "contractual_counterparty",
        "creditor_insurer", "delegated_authority", "faith_group", "family",
        "housing_association", "landlord", "military_command", "national_government",
        "private_property_owner", "profession", "school", "subnational_government",
        "supranational_body", "tribe", "union", "workplace"
    }

    result["defeat_types_found"] = sorted(defeat_types)
    result["authority_types_found"] = sorted(authority_types)
    result["defeat_type_counts"] = dict(sorted(dt_counts.items()))
    result["authority_type_counts"] = dict(sorted(at_counts.items()))

    missing_dt = EXPECTED_DEFEAT_TYPES - defeat_types
    missing_at = EXPECTED_AUTHORITY_TYPES - authority_types

    gaps = []
    if missing_dt:
        gaps.append(f"Missing defeat types: {sorted(missing_dt)}")
    if missing_at:
        gaps.append(f"Missing authority types: {sorted(missing_at)}")
    if parse_failures:
        gaps.append(f"{len(parse_failures)} case IDs could not be parsed: {parse_failures[:5]}")

    result["coverage_gaps"] = gaps
    if gaps:
        result["issues"].extend(gaps)

    # ── Overall pass/fail ──
    # FAIL conditions: missing cases, schema issues, null user_query, coverage gaps
    # WARN conditions: errors (logged but model still responded to all cases),
    #   short responses (may be refusals), duplicates, suspicious tokens, low-sev error-like
    if result["missing_cases"]:
        result["pass"] = False
    if result["schema_issues"]:
        result["pass"] = False
    if result["null_user_query"]:
        result["pass"] = False
    if result["coverage_gaps"]:
        result["pass"] = False
    # High-severity error-like responses = FAIL
    high_sev_errors = [e for e in result["error_like_responses"] if e.get("severity") == "high"]
    if high_sev_errors:
        result["pass"] = False
    # Errors are warnings if no cases are missing (errors have status != success but case still exists)
    # Short responses, duplicates, suspicious tokens are warnings only

    if not result["issues"]:
        result["issues"] = "No issues found"
    else:
        result["issues"] = "; ".join(result["issues"])

    return result


def main():
    print("Loading filtered dataset...")
    per_file_ids, all_case_ids = load_filtered_case_ids()
    print(f"  Total filtered cases: {len(all_case_ids)}")
    print(f"  Scenario files: {len(per_file_ids)}")

    audit_results = {
        "audit_timestamp": __import__("datetime").datetime.now().isoformat(),
        "models_audited": len(MODELS),
        "total_filtered_cases": len(all_case_ids),
        "overall_pass": True,
        "per_model": {},
    }

    for model in MODELS:
        print(f"\nAuditing {model}...")
        result = audit_model(model, per_file_ids, all_case_ids)
        audit_results["per_model"][model] = result

        if not result["pass"]:
            audit_results["overall_pass"] = False

        # Print summary
        print(f"  Files: {result['files']}")
        print(f"  Total responses: {result['total_responses']}")
        print(f"  Successful: {result['successful']}, Errors: {result['errors']}")
        print(f"  Missing cases: {len(result['missing_cases'])}")
        print(f"  Schema issues: {len(result['schema_issues'])}")
        print(f"  Short responses: {len(result['short_responses'])}")
        print(f"  Error-like: {len(result['error_like_responses'])}")
        print(f"  Duplicates: {len(result['duplicate_responses'])}")
        print(f"  Usage coverage: {result['usage_coverage']}")
        print(f"  Avg response length: {result['avg_response_length_chars']} chars")
        print(f"  Avg tokens (in/out/reasoning): {result['avg_input_tokens']}/{result['avg_output_tokens']}/{result['avg_reasoning_tokens']}")
        print(f"  Coverage gaps: {len(result['coverage_gaps'])}")
        status = "PASS" if result["pass"] else "FAIL"
        print(f"  Status: {status}")
        if result["issues"] != "No issues found":
            print(f"  Issues: {result['issues']}")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(audit_results, f, indent=2)
    print(f"\nAudit results written to: {OUTPUT_PATH}")
    print(f"Overall: {'PASS' if audit_results['overall_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
