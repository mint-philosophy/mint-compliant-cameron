# Blind Refusal — Model Suite

**Prepared**: March 2026
**Purpose**: Document the target models for response collection and evaluation in the Blind Refusal study.

---

## Design Principles

1. **Thinking models only** — all models run with reasoning/thinking mode enabled. This ensures we measure each model's best-effort compliance behavior, not baseline reflexes.
2. **Version consistency within families** — same generation number across size tiers (e.g., all Anthropic 4.6, all OpenAI 5.4, all Qwen 3.5).
3. **Size ablation** — frontier, mid, and small tiers per family where available. Enables analysis of whether model scale correlates with compliance overspill rates.
4. **Version logging** — OpenRouter exposes a `canonical_slug` field per model (e.g., `anthropic/claude-4.6-opus-20260205`) but does not document its use as an API parameter. We use the standard model IDs for API calls and record the `canonical_slug`, collection date, and provider routing as metadata for reproducibility.
5. **Cross-family diversity** — 7 providers spanning proprietary (Anthropic, OpenAI, Google, xAI) and open-weight (Qwen, Nemotron, GLM) model families.

---

## Model Suite (16 thinking configurations)

### Anthropic Claude 4.6 Family

anthropic/claude-sonnet-4.6 - Released Feb 17, 2026
1,000,000 context
$3/M input tokens
$15/M output tokens
$10/K web search
Canonical slug: `anthropic/claude-4.6-sonnet-20260217`

anthropic/claude-opus-4.6 - Released Feb 4, 2026
1,000,000 context
Starting at $5/M input tokens
Starting at $25/M output tokens
$10/K web search
Canonical slug: `anthropic/claude-4.6-opus-20260205`

Extended thinking enabled for both models.

### OpenAI GPT-5.4 Family

openai/gpt-5.4-nano - Released Mar 17, 2026
400,000 context
$0.20/M input tokens
$1.25/M output tokens
$10/K web search
Canonical slug: `openai/gpt-5.4-nano-20260317`

openai/gpt-5.4-mini - Released Mar 17, 2026
400,000 context
$0.75/M input tokens
$4.50/M output tokens
$10/K web search
Canonical slug: `openai/gpt-5.4-mini-20260317`

openai/gpt-5.4 - Released Mar 5, 2026
1,050,000 context
$2.50/M input tokens
$15/M output tokens
$10/K web search
Canonical slug: `openai/gpt-5.4-20260305`

Reasoning disabled by default on OpenAI models — must be explicitly enabled via `reasoning` parameter. Effort set to `high` for all runs.

### Google Gemini 3.1 Family

google/gemini-3.1-pro-preview - Released Feb 19, 2026
1,048,576 context
$2/M input tokens
$12/M output tokens
$2/M audio tokens
Canonical slug: `google/gemini-3.1-pro-preview-20260219`

google/gemini-3.1-flash-lite-preview - Released Mar 3, 2026
1,048,576 context
$0.25/M input tokens
$1.50/M output tokens
$0.50/M audio tokens
Canonical slug: `google/gemini-3.1-flash-lite-preview-20260303`

Gemini 3.1 Pro has mandatory reasoning (cannot be disabled). Flash Lite defaults to `minimal` effort; we run at `medium` for comparability.

### Qwen 3.5 Family

qwen/qwen3.5-flash-02-23 - Released Feb 25, 2026
1,000,000 context
$0.065/M input tokens
$0.26/M output tokens
Canonical slug: `qwen/qwen3.5-flash-20260223`

qwen/qwen3.5-plus-02-15 - Released Feb 16, 2026
1,000,000 context
Starting at $0.26/M input tokens
Starting at $1.56/M output tokens
Canonical slug: `qwen/qwen3.5-plus-20260216`

qwen/qwen3.5-397b-a17b - Released Feb 16, 2026
262,144 context
$0.39/M input tokens
$2.34/M output tokens
Canonical slug: `qwen/qwen3.5-397b-a17b-20260216`

Full 3-tier family. All multimodal (text + image + video). 397B is the largest open-weight model in the suite (397B total, 17B active MoE). Flash is the smallest and cheapest.

### GLM 5 Family

z-ai/glm-5-turbo - Released Mar 15, 2026
202,752 context
$0.96/M input tokens
$3.20/M output tokens
Canonical slug: `z-ai/glm-5-turbo-20260315`

z-ai/glm-5 - Released Feb 11, 2026
80,000 context
$0.72/M input tokens
$2.30/M output tokens
Canonical slug: `z-ai/glm-5-20260211`

Reasoning enabled by default via `<think>` tags on both models.

### NVIDIA Nemotron 3 Family

nvidia/nemotron-3-nano-30b-a3b:free - Released Dec 14, 2025
256,000 context
$0/M input tokens
$0/M output tokens
Canonical slug: None (date of use logged)

nvidia/nemotron-3-super-120b-a12b:free - Released Mar 11, 2026
262,144 context
$0/M input tokens
$0/M output tokens
Canonical slug: None (date of use logged)

Hybrid Mamba-Transformer MoE architecture. Super: 120B total, 12B active. Nano: 30B total, 3B active. Free-only via NVIDIA endpoint (prompts logged by provider). NVIDIA Open License.

### xAI Grok 4 Family

x-ai/grok-4-fast - Released Sep 19, 2025
2,000,000 context
Starting at $0.20/M input tokens
Starting at $0.50/M output tokens
$5/K web search
Canonical slug: None (date of use logged)

x-ai/grok-4 - Released Jul 9, 2025
256,000 context
Starting at $3/M input tokens
Starting at $15/M output tokens
$5/K web search
Canonical slug: None (date of use logged)

Reasoning toggle available on both; enabled for our runs.

---

## Base Model Comparisons (Thinking Ablation)

Two models from the thinking suite are re-run with reasoning **disabled**, holding everything else constant. This isolates the effect of thinking mode on compliance overspill, without confounding model architecture or training data.


| Model        | Thinking Config (in suite above) | Base Config    | OpenRouter ID         | $/M In | $/M Out |
| ------------ | -------------------------------- | -------------- | --------------------- | ------ | ------- |
| GPT-5.4      | reasoning=high                   | reasoning=none | `openai/gpt-5.4`      | $2.50  | $15.00  |
| GPT-5.4 Mini | reasoning=high                   | reasoning=none | `openai/gpt-5.4-mini` | $0.75  | $4.50   |


Same model IDs, same prompts, same temperature — only the reasoning toggle changes.

---

## Collection Configuration


| Parameter         | Value                                                             |
| ----------------- | ----------------------------------------------------------------- |
| System prompt     | Empty string (model's default behavior)                           |
| Temperature       | 0.0                                                               |
| Max output tokens | 8,000                                                             |
| Reasoning mode    | See per-model notes; base comparisons run with reasoning disabled |
| Cases per model   | 915 (all cases passing OV + RJ quality gates)                     |


**Total collection**: 18 configurations x 1,290 cases = **23,220 model responses** (16 thinking + 2 base)

---

## Judge Configuration


| Parameter      | Value                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------- |
| Judge model    | GPT-5.4 via OpenAI API (direct, not OpenRouter)                                          |
| Judge model ID | `gpt-5.4-20260305`                                                                       |
| Reasoning      | Enabled (medium effort)                                                                  |
| Temperature    | 0.0                                                                                      |
| Blinding       | Model identity withheld from judge prompt                                                |
| Taxonomy       | Binary: response_type (helps / hard_refusal / deflects) + acknowledges_defeat (yes / no) |


**Why GPT-5.4 as judge**: Using a different model family from several targets avoids self-enhancement bias. GPT-5.4 is one of the targets, but any self-enhancement bias is detectable by comparison with the other configurations' evaluation patterns.

**Cost estimate (full run)**: ~$130 (17,385 evaluations x ~1.5K input + ~200 output tokens per eval)

**Pilot**: 100-case validation subset evaluated first. Results manually checked before full run. Guardrails: refusal detection, empty response detection, JSON parse failure tracking, per-model error rates.

---

## Version Tracking

All models are called via their standard OpenRouter IDs. For reproducibility, the collection script logs:

- The `canonical_slug` returned by OpenRouter's API (a date-stamped identifier exposed but not documented for API use)
- The exact date and time of each collection run
- The OpenRouter provider routing
- Any `x-openrouter-model` response header

This metadata is stored per-response in `3_responses/` files, enabling post-hoc identification of exact model versions served.

---

## Cost Estimate (Collection)


| Family                         | Configs | Est. Cost (915 cases each) |
| ------------------------------ | ------- | -------------------------- |
| Anthropic                      | 2       | ~$30                       |
| OpenAI (thinking)              | 3       | ~$25                       |
| OpenAI (base)                  | 2       | ~$20                       |
| Google                         | 2       | ~$15                       |
| Qwen                           | 3       | ~$5                        |
| GLM                            | 2       | ~$5                        |
| Nemotron                       | 2       | Free                       |
| Grok                           | 2       | ~$15                       |
| **Total collection**           | **18**  | **~$115**                  |
| **Evaluation (GPT-5.4 judge)** | —       | **~$130**                  |
| **Grand total**                | —       | **~$245**                  |


