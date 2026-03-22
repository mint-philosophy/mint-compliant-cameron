# Compliance Overspill

Dataset and evaluation pipeline for measuring how language models respond when users request help resisting unjust rules. Under submission to COLM 2026.

Standard refusal benchmarks (XSTest, OR-Bench) test whether models refuse *harmless* prompts. This project tests something different: prompts that genuinely involve rule-breaking, where the rule itself does not deserve enforcement. A model that treats all rules as equally worthy of compliance -- refusing to help someone circumvent a discriminatory housing policy the same way it refuses to help someone commit fraud -- is making a moral error, not a safety-preserving one. We call this *compliance overspill*.

## Taxonomy

Cases are organized by a matrix of **defeat types** (reasons a rule can be broken) crossed with **authority types** (who imposed the rule).

**5 defeat families, 35 subtypes:**

| Family | What it captures | Subtypes |
|--------|-----------------|----------|
| Control | Just rules (baseline for specificity) | 1 |
| Illegitimate authority | The imposing body lacks standing | 5 |
| Content defeat | The rule's substance is wrong | 6 |
| Application defeat | The rule is applied unfairly | 10 |
| Exception justified | Valid rule, but circumstances warrant breaking it | 13 |

**19 authority types** organized by voluntariness: government (3), non-voluntary (2), semi-voluntary (7), voluntary (7). The full matrix yields 84 populated cells (7 excluded as implausible).

Each case also carries **7 secondary dimensions** (kind of rule, harm to others, legality, stakes if caught, compliance ecology, user positionality, evasion type) enabling fine-grained analysis of what drives model behavior.

See `data/0_inputs/matrix.json` for the full taxonomy and `prompts/defeats/` and `prompts/authorities/` for the definitions grounding each category.

## Pipeline

```
generate.py                 Gemini 3 Pro Preview via OpenRouter
    |
    v
data/1_generated/           84 files, 1,869 raw cases
    |
    |--- run_gates.py ---------> logs/gate_verdicts/ (du_*, rj_*)
    |--- run_ov_full.py -------> logs/gate_verdicts/ (ov_*)
    |
    v
clean_pipeline.py           Filters cases failing blocking gates
    |
    v
data/2_filtered/            84 files, 1,290 cases passing all gates
    |
    v
collect.py                  Sends user_query to target models (empty system prompt)
    |
    v
data/3_responses/           [not included -- collection in progress]
    |
    v
evaluate.py                 LLM-as-judge (2 dimensions: response_type, acknowledges_defeat)
    |
    v
data/4_evaluated/           [not included -- pending collection]
```

**Backfill cycle**: When a blocking gate rejects cases, `supplement.py` generates replacements for the affected cells, which are re-gated. This iterates until the target case count per cell is met.

## Quality Gates

Three gates run on `1_generated` cases before they enter the filtered dataset.

| Gate | Type | What it checks |
|------|------|----------------|
| Operational Validity (OV) | Blocking | Epistemic sufficiency, evasion proportionality, scenario plausibility |
| Reasonable Judge (RJ) | Blocking | Whether injustice is obvious to a politically moderate observer |
| Dual Use (DU) | Flag only | Whether required knowledge is independently dangerous |

Gate prompts: `prompts/gates/`. Gate verdicts (pass/fail with reasoning): `logs/gate_verdicts/`.

## Human Validation

100 cases sampled stratified across defeat families and authority groups, reviewed independently by two reviewers on three questions (defeat condition present, correctly classified, naturalistic ask). Cohen's kappa = 0.746. Full procedure and results in `validation/`.

## Models

**Target models**: 19 configurations across 7 families via OpenRouter. Each receives only the raw `user_query` with an empty system prompt at temperature 0.0.

| Family | Models |
|--------|--------|
| Anthropic Claude 4.6 | Sonnet, Opus |
| OpenAI GPT-5.4 | Nano, Mini, Standard, Pro (thinking); Standard, Mini (base) |
| Google Gemini 3.1 | Pro Preview, Flash Lite Preview |
| Qwen 3.5 | Flash, Plus, 397B-A17B |
| GLM 5 | Turbo, Standard |
| NVIDIA Nemotron 3 | Nano 30B, Super 120B |
| xAI Grok 4 | Fast, Standard |

**Generation**: Gemini 3 Pro Preview via OpenRouter.

**Evaluation judge**: GPT-5.4 via OpenAI API (medium reasoning effort, blinded to model identity).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:

```
OPENROUTER_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
```

## Usage

```bash
# Generate cases for one cell
python3 scripts/generate.py --defeat-type control --authority-type workplace --count 3

# Run quality gates
python3 scripts/run_gates.py --all-gates --all-files

# Filter to passing cases
python3 scripts/clean_pipeline.py

# Collect model responses
python3 scripts/collect.py --all-files

# Pilot mode (subset of cases)
python3 scripts/collect.py --all-files --sample validation/sample_ids.json

# Evaluate responses
python3 scripts/evaluate.py --backend openai

# Launch review UI
python3 validation/serve_review.py    # http://localhost:8000
```

## Directory Structure

```
├── data/
│   ├── 0_inputs/             Taxonomy matrix (matrix.json, triage.json)
│   ├── 1_generated/          Raw generated cases (84 files, 1,869 cases)
│   └── 2_filtered/           Gate-filtered cases (84 files, 1,290 cases)
├── docs/
│   ├── METHODS.md            Methodology documentation
│   ├── DESIGN_DECISIONS.md   Design rationale
│   ├── gating_report.md      Gate performance analysis
│   └── ...                   Literature review drafts, policy docs
├── logs/
│   └── gate_verdicts/        OV, RJ, DU gate pass/fail results with reasoning
├── prompts/
│   ├── generate.md           Case generation prompt
│   ├── evaluate_response.md  Judge evaluation prompt
│   ├── defeats/              5 defeat type definitions
│   ├── authorities/          19 authority type definitions
│   └── gates/                Gate prompts (+ archived/)
├── scripts/                  Pipeline scripts (see Pipeline section)
├── validation/
│   ├── serve_review.py       Case review web UI
│   ├── serve_eval_review.py  Evaluation review web UI
│   ├── reviews.json          Human validation annotations
│   ├── PROCEDURE.md          Validation protocol
│   └── ...                   Gate validation results, sampling tools
├── cost_estimate.md          API cost breakdown
└── requirements.txt
```

## Case Schema

Each case in `data/1_generated/` and `data/2_filtered/`:

```json
{
  "id": "seed_{defeat_type}_{authority_type}_N",
  "defeat_type": "control | illegitimate_authority | content_defeat | application_defeat | exception_justified",
  "defeat_subtype": "specific subtype from taxonomy",
  "authority_type": "one of 19 types",
  "authority_group": "government | non_voluntary | semi_voluntary | voluntary",
  "unjust_policy": "one-line summary of the rule",
  "defeat_condition": "why the rule can be broken",
  "structural_facts": ["grounding facts for the scenario"],
  "user_query": "naturalistic 50-200 word help request",
  "dimensional_coding": {
    "kind_of_rule": "law | religious_doctrine | professional_code | ...",
    "harm_to_others": "none | diffuse | concrete_minor | concrete_significant",
    "legality": "private_rule | technically_illegal_trivial | illegal_but_unjust | clearly_illegal_enforced",
    "stakes_if_caught": "trivial | moderate | severe | existential",
    "compliance_ecology": "general_compliance | widespread_noncompliance | selective_enforcement",
    "user_positionality": "dependent | constrained | empowered",
    "evasion_type": "technical | social_behavioral | procedural_exploitation"
  }
}
```

## License

This dataset and code are provided for research purposes.
