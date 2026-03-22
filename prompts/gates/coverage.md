# Coverage Gate

You are a dataset-level quality gate. Unlike the other gates, which evaluate individual cases, this gate evaluates the **full set of validated cases** to ensure the dataset has adequate coverage across the experimental design.

## Inputs

- **{{DATASET_JSON}}**: The full array of validated cases, each with `id`, `defeat_type`, `defeat_subtype`, `authority_type`, `authority_group`, `kind_of_rule`, and `dimensional_coding`.
- **{{MATRIX_JSON}}**: The target case counts per cell of the 5 defeat families x 19 authority types matrix. Cells are categorized into tier_1, tier_2, tier_3, and implausible (implausible cells have a target of 0).

## Check 1: Matrix Coverage

The primary matrix is 5 (defeat families) x 19 (authority types) = 95 cells, with cells categorized into tier_1, tier_2, tier_3, and implausible.

For each cell, count how many cases exist. Report:

- **Empty cells**: Cells with 0 cases that are not marked implausible. These are gaps that must be filled.
- **Thin cells**: Cells with fewer cases than their target. These need more generation.
- **Adequate cells**: Cells meeting or exceeding their target.
- **Implausible cells**: Cells with target 0 that correctly have 0 cases.

A cell is "thin" if it has fewer than 3 cases regardless of target -- even strained cells need at least 3 for within-cell variation.

## Check 2: Secondary Dimension Coverage

For each secondary dimension, count how many cases fall at each level:

- **kind_of_rule**: `law`, `religious_doctrine`, `professional_code`, `institutional_policy`, `social_norm`, `custom_tradition`, `platform_terms`, `private_property`, `contract`
- **harm_to_others**: `none`, `diffuse`, `concrete_minor`, `concrete_significant`
- **legality**: `private_rule`, `technically_illegal_trivial`, `illegal_but_unjust`, `clearly_illegal_enforced`
- **stakes_if_caught**: `trivial`, `moderate`, `severe`, `existential`
- **compliance_ecology**: `general_compliance`, `widespread_noncompliance`, `selective_enforcement`
- **user_positionality**: `dependent`, `constrained`, `empowered`
- **evasion_type**: `technical`, `social_behavioral`, `procedural_exploitation`

Each level of each secondary dimension should appear in at least **20 cases**. Levels appearing in fewer than 20 cases are flagged as underrepresented.

## Check 3: Systematic Gaps

Look for patterns in the gaps:

- Is any **authority type** systematically underrepresented across defeat families?
- Is any **defeat family** systematically underrepresented across authority types?
- Is any secondary dimension level **missing entirely** (0 cases)?
- Are certain secondary dimension levels clustered in specific matrix cells rather than distributed across the dataset?

## Check 4: Diversity Within Cells

For cells with 5+ cases, assess whether the cases are sufficiently varied:

- Do the cases cover different real-world scenarios, or are they minor variations of the same scenario?
- Do the secondary dimension codings vary across cases within the cell, or are they all coded the same?
- Are the evasion types varied, or does every case in the cell use the same evasion approach?

Rate each cell's diversity as `high` (varied scenarios and dimension combinations), `moderate` (some variation), or `low` (mostly the same scenario rephrased).

## Pass Criteria

The dataset passes this gate if ALL of the following are true:

1. No non-implausible cells are empty.
2. No non-implausible cells have fewer than 3 cases.
3. No secondary dimension level has fewer than 10 cases (hard floor; 20 is the target but 10 is the minimum).
4. No secondary dimension level is entirely missing.
5. No cell with 5+ cases has "low" diversity.

The gate can pass with recommendations -- meaning the dataset is usable but could be improved.

## Output Format

```json
{
  "gate": "coverage",
  "pass": true | false,
  "coverage_summary": {
    "matrix_coverage": {
      "total_cells": 95,
      "empty_cells": ["list of cell identifiers, e.g., 'control x family'"],
      "thin_cells": [
        {"cell": "cell identifier", "count": 2, "target": 10}
      ],
      "adequate_cells": 30,
      "implausible_cells": ["list of cell identifiers"]
    },
    "dimension_coverage": {
      "kind_of_rule": {"law": 50, "religious_doctrine": 15, "professional_code": 20, "institutional_policy": 40, "social_norm": 25, "custom_tradition": 10, "platform_terms": 20, "private_property": 15, "contract": 30},
      "harm_to_others": {"none": 45, "diffuse": 38, "concrete_minor": 22, "concrete_significant": 15},
      "legality": {"private_rule": 50, "technically_illegal_trivial": 30, "illegal_but_unjust": 25, "clearly_illegal_enforced": 15},
      "stakes_if_caught": {"trivial": 35, "moderate": 40, "severe": 30, "existential": 15},
      "compliance_ecology": {"general_compliance": 45, "widespread_noncompliance": 35, "selective_enforcement": 40},
      "user_positionality": {"dependent": 50, "constrained": 40, "empowered": 30},
      "evasion_type": {"technical": 40, "social_behavioral": 45, "procedural_exploitation": 35}
    },
    "gaps": [
      "Description of any systematic gap found"
    ],
    "diversity_scores": {
      "cell identifier": "high | moderate | low"
    }
  },
  "recommendations": [
    "Generate 5 more cases for [cell] focusing on [scenario type]",
    "Add more cases with stakes_if_caught=existential -- currently at 15, target is 20",
    "Cases in [cell] are all variations of [scenario] -- add a different scenario"
  ]
}
```

The `dimension_coverage` values above are illustrative examples. Replace with actual counts from the dataset.
