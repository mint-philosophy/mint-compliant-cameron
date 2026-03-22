#!/usr/bin/env python3
"""
Fix invalid dimensional_coding values in generated cases.
Maps Gemini-invented values to the closest valid taxonomy value.
"""
from __future__ import annotations

import json
import glob
import os
from pathlib import Path

GENERATED_DIR = Path(__file__).resolve().parent.parent / "data" / "1_generated"

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

# Map invalid values to valid replacements
FIXES = {
    "kind_of_rule": {
        "house_rule": "social_norm",
        "household_rule": "social_norm",
        "parental_rule": "social_norm",
    },
    "evasion_type": {
        "physical": "social_behavioral",
        "physical_manipulation": "social_behavioral",
        "physical_modification": "social_behavioral",
    },
    "compliance_ecology": {
        "transgressive": "widespread_noncompliance",
        "dependent": "general_compliance",
        "strict_enforcement": "general_compliance",
    },
    "legality": {
        "civil_dispute": "private_rule",
    },
    "harm_to_others": {
        "existential": "concrete_significant",
    },
}


def fix_file(filepath: str) -> int:
    """Fix invalid dimension values in a single file. Returns count of fixes."""
    with open(filepath) as f:
        data = json.load(f)

    cases = data.get("cases", []) if isinstance(data, dict) else data
    fixes = 0

    for case in cases:
        coding = case.get("dimensional_coding", {})
        for dim, valid_values in VALID_DIMENSIONS.items():
            val = coding.get(dim)
            if val is not None and val not in valid_values:
                replacement = FIXES.get(dim, {}).get(val)
                if replacement:
                    coding[dim] = replacement
                    fixes += 1
                    print(f"  Fixed {case.get('id', '?')}: {dim} '{val}' -> '{replacement}'")
                else:
                    print(f"  UNKNOWN {case.get('id', '?')}: {dim} '{val}' — no mapping defined")

    if fixes > 0:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    return fixes


def main():
    total_fixes = 0
    for filepath in sorted(glob.glob(str(GENERATED_DIR / "*.json"))):
        fname = os.path.basename(filepath)
        n = fix_file(filepath)
        if n > 0:
            print(f"  [{fname}] {n} fix(es)")
        total_fixes += n

    print(f"\nTotal fixes applied: {total_fixes}")


if __name__ == "__main__":
    main()
