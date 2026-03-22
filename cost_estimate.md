# Compliance Overspill v4 -- Collection & Evaluation Cost Estimate

Generated: 2026-03-19

---

## 1. Pipeline Architecture

### Collection (`scripts/collect.py`)

- **Input**: 84 files in `data/2_filtered/`, containing 915 total cases
- **Prompt structure**: Each case's `user_query` field is sent as the sole user message. System prompt is empty string (`""`). No wrapping, no additional context, no instructions. The model gets the raw user query and nothing else.
- **API route**: All 5 models are called via OpenRouter (OpenAI SDK with `openrouter.ai/api/v1` base URL)
- **Parameters**: `temperature=0.0`, `max_tokens=2000`, `json_mode=False`
- **Rate limiting**: 2-second delay between cases (`INTER_CASE_DELAY_S = 2.0`)
- **Retry logic**: Exponential backoff, 5 retries with 2.0s base delay
- **Resume support**: `--resume` skips model+file combos with existing output; `--new-only` skips individual cases already collected within a file
- **Storage**: Responses saved to `data/3_responses/{model_slug}_{file_stem}.json` as JSON with metadata envelope

### Evaluation (`scripts/evaluate.py`)

- **Judge model**: `google/gemini-3-pro-preview` via OpenRouter (default), or `claude --print` CLI (Max subscription, no API cost)
- **Parameters**: `temperature=0.1`, `max_tokens=1200`
- **Prompt**: Template at `prompts/evaluate_response.md` -- fills in case metadata + original query + model response, asks for JSON classification on 2 dimensions (`response_type`, `acknowledges_defeat`)
- **Rate limiting**: 0.5-second delay between eval calls
- **Retry**: 3 retries
- **Current state**: 0 evaluations completed (empty `data/4_evaluated/` directory)

---

## 2. Model Suite

| # | OpenRouter Model ID | Slug | Provider |
|---|---|---|---|
| 1 | `anthropic/claude-opus-4.6` | `claude-opus-4-6` | Anthropic via OpenRouter |
| 2 | `openai/gpt-5.2` | `gpt-5-2` | OpenAI via OpenRouter |
| 3 | `google/gemini-3.1-pro-preview` | `gemini-3-1-pro` | Google via OpenRouter |
| 4 | `deepseek/deepseek-v3.2` | `deepseek-v3-2` | DeepSeek via OpenRouter |
| 5 | `meta-llama/llama-4-maverick` | `llama-4-maverick` | Meta via OpenRouter |

---

## 3. Pricing (OpenRouter, March 2026)

| Model | Input $/1M tokens | Output $/1M tokens | Source |
|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | openrouter.ai |
| GPT-5.2 | $1.75 | $14.00 | openrouter.ai |
| Gemini 3.1 Pro Preview | $2.00 | $12.00 | openrouter.ai |
| DeepSeek V3.2 | $0.28 | $0.42 | openrouter.ai |
| Llama 4 Maverick | $0.15 | $0.60 | openrouter.ai |
| **Gemini 3 Pro Preview** (eval judge) | $2.00 | $12.00 | openrouter.ai |

---

## 4. Token Measurements (Actual Data, tiktoken cl100k_base)

### Input Tokens (user_query)

915 cases measured:

| Metric | Tokens |
|---|---|
| Min | 51 |
| Max | 176 |
| Mean | 107.4 |
| Median | 107 |
| P10 | 79 |
| P90 | 136 |
| **Total across all 915** | **98,300** |

The collect script sends only the `user_query` as the user message plus an empty system prompt. OpenRouter adds ~5-10 tokens of API overhead per call (system message wrapper), so effective input is approximately **~115 tokens per call**.

### Output Tokens (model responses, from existing data)

| Model | N responses | Mean | Median | P90 | Total |
|---|---|---|---|---|---|
| Claude Opus 4.6 | 857 | 374 | 337 | 498 | 320,419 |
| GPT-5.2 | 727 | 734 | 708 | 1,061 | 533,854 |
| Gemini 3.1 Pro | 473 | 499 | 520 | 801 | 235,807 |
| DeepSeek V3.2 | 488 | 698 | 631 | 1,317 | 340,441 |
| Llama 4 Maverick | 526 | 122 | 8 | 451 | 64,150 |

**Note on Llama 4 Maverick**: Median output is 8 tokens, suggesting the majority of responses are very short refusals or empty. Mean is pulled up by the minority that produce substantive responses.

---

## 5. Collection Status

| Model | Collected | Missing | % Complete |
|---|---|---|---|
| Claude Opus 4.6 | 857 | 58 | 93.7% |
| GPT-5.2 | 727 | 188 | 79.5% |
| Gemini 3.1 Pro | 473 | 442 | 51.7% |
| DeepSeek V3.2 | 488 | 427 | 53.3% |
| Llama 4 Maverick | 526 | 389 | 57.5% |
| **Total** | **3,071** | **1,504** | **67.1%** |

---

## 6. Cost Calculation -- Remaining Collection

For missing cases, I use the per-model average output tokens from existing data as the best predictor. Input tokens are ~115 per call (user_query + overhead).

### Per-model remaining collection cost

| Model | Missing Cases | Input Tokens | Output Tokens | Input Cost | Output Cost | **Total** |
|---|---|---|---|---|---|---|
| Claude Opus 4.6 | 58 | 58 x 115 = 6,670 | 58 x 374 = 21,692 | $0.03 | $0.54 | **$0.57** |
| GPT-5.2 | 188 | 188 x 115 = 21,620 | 188 x 734 = 137,992 | $0.04 | $1.93 | **$1.97** |
| Gemini 3.1 Pro | 442 | 442 x 115 = 50,830 | 442 x 499 = 220,558 | $0.10 | $2.65 | **$2.75** |
| DeepSeek V3.2 | 427 | 427 x 115 = 49,105 | 427 x 698 = 298,046 | $0.01 | $0.13 | **$0.14** |
| Llama 4 Maverick | 389 | 389 x 115 = 44,735 | 389 x 122 = 47,458 | $0.01 | $0.03 | **$0.04** |
| **REMAINING TOTAL** | **1,504** | | | **$0.19** | **$5.28** | **$5.47** |

### Full collection cost (all 915 x 5 = 4,575 calls, for reference)

| Model | Cases | Input Tokens | Output Tokens | Input Cost | Output Cost | **Total** |
|---|---|---|---|---|---|---|
| Claude Opus 4.6 | 915 | 105,225 | 342,210 | $0.53 | $8.56 | **$9.08** |
| GPT-5.2 | 915 | 105,225 | 671,610 | $0.18 | $9.40 | **$9.59** |
| Gemini 3.1 Pro | 915 | 105,225 | 456,585 | $0.21 | $5.48 | **$5.69** |
| DeepSeek V3.2 | 915 | 105,225 | 638,670 | $0.03 | $0.27 | **$0.30** |
| Llama 4 Maverick | 915 | 105,225 | 111,630 | $0.02 | $0.07 | **$0.08** |
| **FULL TOTAL** | **4,575** | | | **$0.96** | **$23.77** | **$24.74** |

---

## 7. Cost Calculation -- Evaluation Pipeline

The eval pipeline sends each successful response to Gemini 3 Pro Preview (or Claude CLI at no API cost).

### Using OpenRouter (Gemini 3 Pro Preview)

Eval input per call = template base (1,075) + system prompt (21) + case metadata (~30) + user_query (~107) + model_response (varies).

| Model Evaluated | Responses to Eval | Avg Input Tokens | Avg Output Tokens | Input Cost | Output Cost | **Total** |
|---|---|---|---|---|---|---|
| Claude Opus 4.6 | 915 | 1,607 | 75 | $2.94 | $0.82 | **$3.76** |
| GPT-5.2 | 915 | 1,967 | 75 | $3.60 | $0.82 | **$4.42** |
| Gemini 3.1 Pro | 915 | 1,732 | 75 | $3.17 | $0.82 | **$3.99** |
| DeepSeek V3.2 | 915 | 1,931 | 75 | $3.53 | $0.82 | **$4.36** |
| Llama 4 Maverick | 915 | 1,355 | 75 | $2.48 | $0.82 | **$3.30** |
| **EVAL TOTAL** | **4,575** | | | **$15.72** | **$4.12** | **$19.83** |

Note: This assumes all 915 cases per model are evaluated. Actual count depends on successful collection. Currently 3,071 successful responses exist, which would cost proportionally less (~$13.34).

### Using Claude CLI (`--judge cli`)

Cost: $0.00 (uses Max subscription). Tradeoff: much slower (subprocess per call, 300s timeout), rate-limited by subscription, and the model/version is whatever Claude CLI defaults to.

---

## 8. Total Cost Summary

| Component | Remaining | Full (from scratch) |
|---|---|---|
| Collection (remaining 1,504 cases) | **$5.47** | -- |
| Collection (full 4,575 cases) | -- | **$24.74** |
| Evaluation (OpenRouter, all 4,575) | **$19.83** | **$19.83** |
| Evaluation (CLI, all 4,575) | $0.00 | $0.00 |
| | | |
| **Collection remaining + Eval (OpenRouter)** | **$25.30** | -- |
| **Collection remaining + Eval (CLI)** | **$5.47** | -- |
| **Full pipeline from scratch (OpenRouter eval)** | -- | **$44.57** |
| **Full pipeline from scratch (CLI eval)** | -- | **$24.74** |

---

## 9. Issues and Gaps

1. **Llama 4 Maverick response quality**: Median output is 8 tokens. Most responses appear to be near-empty refusals or truncated. This could indicate the model is refusing most prompts or that collection encountered silent failures. Worth investigating a sample before completing collection.

2. **Collection completeness is uneven**: Claude is 94% done, but Gemini and DeepSeek are only ~52%. The `--new-only` flag should handle incremental collection correctly.

3. **Error rates**: Claude has 58 errors (6.3%), GPT has 50 (6.5%), Gemini has 51 (9.7%), DeepSeek has 36 (6.9%), Llama has 0 errors but likely has the "short refusal" issue instead. These errors are API-level failures (timeouts, rate limits) rather than model refusals.

4. **Evaluation is at 0%**: No evaluations have been run yet. The `data/4_evaluated/` directory exists but is empty.

5. **Cost is dominated by output tokens, not input**: The user queries are short (~107 tokens). Output varies dramatically by model. Claude Opus's high output pricing ($25/1M) makes it the most expensive model despite producing shorter responses than GPT-5.2.

6. **CLI eval is free but slow**: At ~5-10 seconds per call with 4,575 evaluations, CLI eval would take 6-13 hours. OpenRouter eval at 0.5s delay would take ~40 minutes but costs $19.83.

7. **Gemini 3 Pro Preview vs Gemini 3.1 Pro Preview**: The eval judge uses `google/gemini-3-pro-preview` while the collection target uses `google/gemini-3.1-pro-preview`. These are different models. The eval judge is the older Gemini 3 Pro, not 3.1. Pricing for the eval judge is $2.00 input / $12.00 output per 1M tokens.
