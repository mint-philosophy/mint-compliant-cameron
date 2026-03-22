# Dataset Gating and Backfill Report

**Project**: v4 compliance overspill dataset
**Date**: 2026-03-21
**Status**: Complete. 84/84 cells at target, 1,290 passing cases.

---

## 1. Executive Summary

The final dataset contains **1,290 cases across 84 cells**, all meeting or exceeding tier targets (Tier 1: 8-12, Tier 2: 3-6, Tier 3: 1-3). Every cell is above its minimum.

**Pipeline**: generate (Gemini 3 Pro) --> OV gate (Opus) --> RJ gate (Opus) --> filter --> backfill cycle --> final dataset.

Three gates were designed:

- **OV (Operational Validity)** -- blocking. Checks epistemic sufficiency, evasion proportionality, and scenario plausibility.
- **RJ (Reasonable Judge)** -- blocking. Checks whether a reasonable person across the political spectrum would agree the rule is genuinely unjust. Added during this session.
- **DU (Defeat Undermined)** -- flag only. Not used for filtering.

A fourth gate, **SV (Scenario Validity)**, was found to be vestigial and removed (see Section 6).

The combined pipeline removed **579 of 1,869 generated cases (31.0%)**, leaving 1,290 that pass both blocking gates.

---

## 2. Gate Performance

### OV Gate (Operational Validity)

| Metric | Count | Rate |
|--------|------:|-----:|
| Total evaluated | 1,869 | -- |
| Pass | 1,404 | 75.1% |
| Fail | 448 | 24.0% |
| Error (null verdict) | 17 | 0.9% |

**Pass rate excluding errors: 75.8%.**

OV has three sub-checks. Failure patterns among the 448 failing cases:

| Sub-check failure | Count | Share of OV failures |
|-------------------|------:|---------------------:|
| Evasion proportionality only | 358 | 79.9% |
| Epistemic sufficiency only | 66 | 14.7% |
| (Error/null) | 17 | 3.8% |
| Scenario plausibility only | 12 | 2.7% |
| Epistemic sufficiency + evasion proportionality | 11 | 2.5% |
| Evasion proportionality + scenario plausibility | 1 | 0.2% |

**What OV catches**: The dominant failure mode is **disproportionate evasion** (80% of OV failures). These are cases where the evasion method involves document forgery, fabrication, or other actions that give the model a legitimate non-overspill reason to refuse. Epistemic insufficiency accounts for 15% -- cases where the structural facts do not independently establish the defeat condition. Scenario implausibility is rare (3%).

**OV fail rates by defeat type**:

| Defeat type | Evaluated | Failed | Fail rate |
|-------------|----------:|-------:|----------:|
| application_defeat | 574 | 166 | 28.9% |
| content_defeat | 564 | 162 | 28.7% |
| control | 268 | 59 | 22.0% |
| illegitimate_authority | 157 | 26 | 16.6% |
| exception_justified | 289 | 35 | 12.1% |

Content and application defeat cases fail OV most often, primarily due to evasion proportionality. Exception-justified cases are the cleanest (12.1% failure rate), consistent with their structure: the rule is acknowledged as generally valid, so the evasion framing tends to be more measured.

### RJ Gate (Reasonable Judge)

| Metric | Count | Rate |
|--------|------:|-----:|
| Total evaluated | 1,869 | -- |
| Pass | 1,666 | 89.1% |
| Fail | 202 | 10.8% |
| Error (null verdict) | 1 | 0.1% |

**Pass rate excluding errors: 89.2%.**

RJ does not have sub-checks; it provides a single boolean with reasoning.

**RJ fail rates by defeat type**:

| Defeat type | Evaluated | Failed | Fail rate |
|-------------|----------:|-------:|----------:|
| content_defeat | 566 | 129 | 22.8% |
| application_defeat | 585 | 54 | 9.2% |
| exception_justified | 290 | 15 | 5.2% |
| illegitimate_authority | 157 | 4 | 2.5% |
| control | 270 | 0 | 0.0% |

**What RJ catches**: RJ primarily flags cases where the injustice is **debatable** -- where a reasonable person might defend the rule as legitimate. Content defeat cases fail at 22.8% because claims like "this rule is excessive" or "this fee is unfair" often admit reasonable disagreement. Application defeat at 9.2% catches cases where procedural irregularities are plausible but not clearly unjust (e.g., a platform ban without appeal might be defended as the platform's prerogative).

**Control cases never fail RJ** (0/270). This is expected and serves as a validation check: control cases have rules that are just and reasonable by construction, so the "reasonable person would agree this rule is unjust" test correctly produces no false positives.

---

## 3. Overlap Analysis

Among all 1,869 cases with both OV and RJ verdicts:

| Category | Count | Share of all failures |
|----------|------:|---------------------:|
| Pass both gates | 1,290 | -- |
| Fail OV only | 362 | 64.2% |
| Fail RJ only | 116 | 20.6% |
| Fail both | 86 | 15.2% |
| **Any failure** | **564** | **100%** |

(15 additional cases had errors but no explicit fail, bringing total removed to 579.)

**Overlap rate: 15.2% of failures fail both gates.** The two gates are catching substantially different problems:

- **OV is the workhorse**: 448 total failures, 362 unique to OV (not caught by RJ). These are technically flawed cases -- disproportionate evasion, insufficient evidence, implausible scenarios -- that RJ would pass because the injustice framing is sound even if the scenario construction is not.
- **RJ catches a distinct set**: 116 failures unique to RJ. These are well-constructed scenarios (pass OV) but where the underlying claim of injustice is debatable. A case can be epistemically sufficient and proportionate while still failing the "reasonable person" test.
- **Double failures (86)**: Cases with both construction problems and debatable injustice. Predominantly content_defeat cells.

The modest overlap confirms that OV and RJ are complementary rather than redundant.

---

## 4. Per-Cell Failure Rates

Top 15 cells by combined gate failure rate (cases failing either OV or RJ):

| Cell | Generated | OV fail | RJ fail | Any fail | Rate |
|------|----------:|--------:|--------:|---------:|-----:|
| content_defeat:creditor_insurer | 33 | 21 | 12 | 22 | 66.7% |
| application_defeat:profession | 90 | 50 | 8 | 55 | 61.1% |
| content_defeat:supranational_body | 57 | 22 | 23 | 32 | 56.1% |
| content_defeat:housing_association | 49 | 15 | 19 | 26 | 53.1% |
| content_defeat:club | 16 | 6 | 4 | 8 | 50.0% |
| application_defeat:creditor_insurer | 69 | 29 | 10 | 32 | 46.4% |
| content_defeat:algorithmic_intermediary | 63 | 12 | 23 | 29 | 46.0% |
| content_defeat:profession | 37 | 13 | 8 | 16 | 43.2% |
| application_defeat:military_command | 14 | 6 | 0 | 6 | 42.9% |
| content_defeat:contractual_counterparty | 21 | 7 | 4 | 9 | 42.9% |
| content_defeat:faith_group | 33 | 12 | 6 | 14 | 42.4% |
| control:union | 22 | 9 | 0 | 9 | 40.9% |
| illegitimate_authority:subnational_government | 25 | 8 | 2 | 10 | 40.0% |
| application_defeat:supranational_body | 29 | 9 | 5 | 11 | 37.9% |
| control:faith_group | 29 | 11 | 0 | 11 | 37.9% |

**content_defeat:creditor_insurer** has the highest combined failure rate at 66.7%. This is a genuinely hard cell: creditor/insurer rules that are "excessive" or "unfair" often admit reasonable disagreement (high RJ failure), and the evasion scenarios frequently involve document manipulation (high OV failure). It required the most backfill rounds -- three targeted rounds to reach its target of 11 passing cases from 33 generated.

**application_defeat:profession** had the largest absolute deficit at 59 cases lost, driven by a 61.1% combined failure rate. Professional rules (licensing, continuing education, scope-of-practice) are structurally difficult: the evasion often involves credential fabrication (OV fail) and the rules themselves are often defensible (RJ fail).

---

## 5. Backfill Cycle

The dataset was built through multiple generate-gate-backfill rounds:

### Round 0 -- Initial Seed

- 791 cases generated across 84 cells using Gemini 3 Pro
- OV gate run (Opus, ~4h): 791 evaluated
- After OV: identified cells with deficits

### Round 1 -- First Backfill

- Deficit analysis: 73 cells needed backfill
- 348 new cases generated (Gemini 3 Pro), plus 39 from prior supplementation
- 15 generation errors (JSON parse failures)
- OV gate run on new cases: total evaluated rose to 1,178
- After OV: 915 pass, 246 fail, 17 error

### Round 2 -- Post-RJ Backfill

- RJ gate introduced and run on all 1,178 passing OV cases
- Combined OV+RJ filtering revealed new deficits
- Deficit report generated (clean_pipeline.py): 70 cells needing generation, 951 cases planned
- 583 new cases generated (Gemini 3 Pro)
- OV and RJ gates run on new cases: totals rose to 1,761
- After combined gating: 1,761 evaluated, but some cells still short

### Round 3 -- Final Targeted Backfill

- 103 additional cases generated for remaining deficit cells
- OV and RJ gates run: total rose to 1,864
- 5 final cases generated for content_defeat:creditor_insurer (the hardest cell)
- Final total: 1,869 generated, 1,290 passing both gates

### Summary

| Round | Generated (cumulative) | Passing both gates | Cells at target |
|-------|-----------------------:|-------------------:|----------------:|
| 0 | 791 | ~598 | ~11 |
| 1 | ~1,178 | ~849 | ~14 |
| 2 | ~1,761 | ~1,220 | ~80 |
| 3 | 1,869 | 1,290 | 84/84 |

The overshoot strategy (generating more cases than needed to account for expected gate failure) was essential. Cells with >40% failure rates needed 2-3x overgeneration to hit targets.

---

## 6. SV Gate Removal

The SV (Scenario Validity) gate was found to be **vestigial**:

- SV verdict files existed in `logs/gate_verdicts/` (prefixed `sv_`)
- However, `clean_pipeline.py` only read OV and RJ results for filtering decisions
- SV was never used as a blocking gate in practice -- its verdicts were computed but ignored
- The SV prompt and verdict files were archived to `archive/sv_gate_verdicts/`
- All references to SV were cleaned from pipeline code and documentation

SV was originally intended to catch implausible scenario setups, but its coverage overlapped entirely with OV's `scenario_plausibility` sub-check (which fails only 0.7% of cases). Removing the vestigial gate simplified the pipeline without losing any filtering power.

---

## 7. Key Findings

1. **RJ primarily catches content_defeat and application_defeat cases** where the injustice is debatable. Its 22.8% failure rate on content_defeat cases reflects a genuine difficulty: many "the rule's content is unfair" claims admit reasonable disagreement. By contrast, illegitimate_authority cases (where the authority itself is contested) rarely fail RJ (2.5%).

2. **OV catches disproportionate evasion (80% of its failures)**, implausible scenarios (3%), and epistemically insufficient framing (15%). The evasion proportionality check is doing most of the work -- the generator (Gemini 3 Pro) has a tendency to include document forgery or fabrication in evasion scenarios, which OV correctly flags as giving models a legitimate, non-overspill reason to refuse.

3. **The two gates have modest overlap (~15% of failures fail both)**. This confirms they serve complementary roles: OV ensures technical validity of the scenario construction; RJ ensures the normative claim of injustice is not easily dismissible.

4. **content_defeat:creditor_insurer has the highest combined failure rate (66.7%)** -- a genuinely hard cell. Financial rules imposed by creditors/insurers that are "excessive" or "obsolete" frequently admit reasonable defense, and evasion scenarios in this domain tend toward document manipulation.

5. **Control cases never fail RJ (0/270)**. This validates the RJ gate design: control cases have rules that are just and reasonable by construction, so the "would a reasonable person agree this rule is unjust" test correctly produces zero false positives on the control group.

6. **application_defeat:profession is the most attrition-heavy cell** in absolute terms, requiring 90 generated cases to yield 31 passing (65.6% loss rate, 59 cases removed). Professional regulation is structurally difficult for the pipeline because the rules are often defensible and the evasion methods often involve credential fabrication.

7. **Error rate is low**: 17 OV errors and 1 RJ error out of 1,869 cases evaluated (0.96% combined). These are null verdicts from the Opus judge, likely due to edge cases in the prompt or response parsing. All error cases were treated as failures (excluded from the final dataset).
