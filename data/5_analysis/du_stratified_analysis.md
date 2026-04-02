# Dual-Use Stratified Analysis

**Question**: Is the control vs. defeated delta in helps rate driven by models appropriately refusing dual-use content, or does it reflect sensitivity to rule-breaking per se (compliance overspill)?

**Test**: Compare the control vs. defeated helps-rate delta within DU-flagged and non-DU cases separately. If the delta persists in clean (non-DU) cases, dual-use content cannot explain the refusal pattern.

---

## Data provenance

- Total evaluation records: 23,189
- Records with DU flag populated: 23,189 (100.0%)
  - DU-flagged (requires dangerous knowledge): 13,320 (57.4% of gated)
  - Non-DU (clean cases): 9,869 (42.6% of gated)
- Records without DU flag (gate not run): 0

> **Note on DU flag rate**: 60.8% of unique cases are flagged as dual-use, primarily cybersecurity (43.5%) and physical security (26.4%). The gate uses a broad definition that includes defeating access controls and monitoring systems, which overlap substantially with the algorithmic intermediary and workplace authority types in this dataset. The high flag rate does not necessarily indicate the gate is over-triggering — these categories were designed to capture cases where circumvention methods transfer to harmful uses. Readers should treat DU-stratified results as exploratory pending closer inspection of gate calibration.

---

## 1. Overall helps rate by DU status

| Stratum | Helps % | N |
| :--- | ---: | ---: |
| DU-flagged | 10.2% | 13,320 |
| Non-DU | 36.2% | 9,869 |

Non-DU cases have substantially higher helps rates (36.2% vs 10.2%), consistent with models appropriately applying more caution to dual-use content. This is the *expected* pattern regardless of whether compliance overspill exists.

---

## 2. Control vs. defeated delta within each DU stratum

This is the primary test. If the delta is driven by DU-based refusal, it should be near zero in non-DU cases.

| Stratum | Control helps % | Defeated helps % | Delta (pp) | N (ctrl) | N (defeated) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| DU-flagged | 2.8% | 12.0% | +9.2pp | 2,499 | 10,821 |
| Non-DU (clean) | 7.1% | 40.4% | +33.3pp | 1,260 | 8,609 |

*For reference: overall delta (gated records) = 4.2% → 24.6%, delta = +20.3pp*

> **Interpretation**: If the delta in non-DU cases is large, this is evidence that models refuse defeated-rule requests even when the content is not independently dangerous — i.e., the refusal is about the rule-breaking signal, not the harm potential of the content.

---

## 3. Pure overspill rate in non-DU defeated cases

Pure overspill: the model refuses, does not engage with the defeat condition, and does not cite independent harm. In non-DU defeated cases, this is the most conservative signal of compliance overspill — it cannot be explained by harm avoidance because the DU gate says the case content is not independently dangerous.

| Cases | Pure Overspill % | N |
| :--- | ---: | ---: |
| Non-DU, defeated (primary test) | 9.7% | 8,609 |
| Non-DU, control | 21.4% | 1,260 |
| DU-flagged, defeated (for comparison) | 16.9% | 10,821 |

> **Limitation**: The 'independent_harm' flag is assigned by the same LLM judge that classifies response type. It may be over-triggered (see Section 5), which would artificially *lower* the pure overspill count by reclassifying pure overspill cases as 'Safety-Grounded'. The true pure overspill rate may be higher than reported here.

---

## 4. Per-model control vs. defeated delta (non-DU cases only)

Sorted by delta (descending). Models with no non-DU control cases are omitted.

| Model | Control helps % | Defeated helps % | Delta (pp) | N |
| :--- | ---: | ---: | ---: | ---: |
| gemini-3-1-pro | 4.3% | 64.3% | +60.0pp | 549 |
| gemini-3-1-flash-lite | 7.1% | 63.7% | +56.5pp | 549 |
| grok-4-fast | 8.6% | 62.2% | +53.6pp | 549 |
| claude-opus-4-6 | 1.4% | 50.2% | +48.8pp | 548 |
| nemotron-3-super | 7.1% | 53.0% | +45.9pp | 549 |
| glm-5-turbo | 1.4% | 46.8% | +45.3pp | 549 |
| glm-5 | 1.4% | 44.7% | +43.2pp | 549 |
| claude-sonnet-4-6 | 1.4% | 42.9% | +41.5pp | 538 |
| nemotron-3-nano | 14.3% | 50.8% | +36.6pp | 548 |
| qwen-3-5-397b | 0.0% | 27.3% | +27.3pp | 549 |
| qwen-3-5-plus | 1.4% | 24.6% | +23.2pp | 549 |
| grok-4 | 61.4% | 83.3% | +21.9pp | 549 |
| gpt-5-4-thinking | 0.0% | 18.8% | +18.8pp | 549 |
| gpt-5-4-base | 2.9% | 20.9% | +18.0pp | 549 |
| gpt-5-4-mini-thinking | 2.9% | 19.0% | +16.1pp | 549 |
| qwen-3-5-flash | 1.4% | 16.7% | +15.3pp | 549 |
| gpt-5-4-mini-base | 1.4% | 15.9% | +14.4pp | 549 |
| gpt-5-4-nano-thinking | 8.6% | 22.3% | +13.8pp | 549 |

> **Note on grok-4**: The control helps rate in non-DU cases (61.4%) is high, indicating this model assists with rule-breaking even when rules are just and the content is clean. Its large delta is therefore less informative about defeat-condition sensitivity and more about an overall permissiveness profile.

---

## 5. Limitations and alternative interpretations

**DU gate calibration**: The gate flags 60.8% of cases, dominated by cybersecurity and physical security categories. Some of these may be false positives — cases where the 'cybersecurity' framing (e.g., defeating employer monitoring software) does not actually require transferable dangerous knowledge. If the gate over-flags, the non-DU stratum is biased toward lower-stakes, more easily helpable cases, which would inflate the non-DU delta independently of any compliance overspill effect. A closer manual review of a sample of flagged cases is warranted.

**Independent harm over-triggering**: The `independent_harm` flag (used to compute pure overspill) is assigned by the LLM judge at 70% overall. This rate is too high to reflect only cases where the model explicitly cites a specific, independent harm to justify refusal. Over-triggering here moves responses from 'Pure Overspill' into 'Safety-Grounded' or 'Engaged + Safety', potentially understating the compliance overspill rate.

**Selection effects across defeat × authority cells**: The DU flag is not uniformly distributed across defeat types or authority types. If certain cells (e.g., algorithmic intermediary × application defeat) are disproportionately flagged, the non-DU stratum may not be a balanced sample of the full matrix. Per-cell stratification would be needed to rule this out.

**Ecological validity of 'non-DU'**: Even in non-DU cases, the requests involve rule-breaking. A model that refuses all rule-breaking requests regardless of DU status would show the same delta pattern we observe. The analysis demonstrates that the control vs. defeated delta is not *explained* by DU content, but does not establish that the refusal is *wrong* in any particular non-DU case.