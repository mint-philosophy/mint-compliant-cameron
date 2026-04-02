# Blind Refusal

Dataset and evaluation pipeline for "Blind Refusal: Language Models Refuse to Help Users Evade Unjust, Absurd, and Illegitimate Rules" (Pattison, Manuali, and Lazar, 2026).

Standard refusal benchmarks test whether models refuse harmless prompts. This project tests something different: prompts where the user genuinely seeks to break a rule, but the rule itself does not deserve enforcement. A model that treats all rules as equally worthy of compliance -- refusing to help someone circumvent a discriminatory housing policy the same way it refuses to help someone commit fraud -- makes a moral error, not a safety-preserving one. We call this *blind refusal*.

## Taxonomy

Cases are organized by a matrix of **defeat types** (reasons a rule does not deserve compliance) crossed with **authority types** (who imposed the rule).

**5 defeat families (35 subtypes):**

| Family | What it captures | Subtypes |
|--------|-----------------|----------|
| Control | Just rules (baseline for specificity) | 1 |
| Illegitimate authority | The imposing body lacks standing | 5 |
| Content defeat | The rule's substance is wrong | 6 |
| Application defeat | The rule is applied unfairly | 10 |
| Exception justified | Valid rule, but circumstances warrant breaking it | 13 |

**19 authority types** organized by voluntariness: government (3), non-voluntary (2), semi-voluntary (7), voluntary (7). The full matrix yields 84 populated cells (7 combinations excluded as implausible).

Each case also carries 7 secondary dimensions (kind of rule, harm to others, legality, stakes if caught, compliance ecology, user positionality, evasion type) for fine-grained analysis.

See `data/0_inputs/matrix.json` for the full taxonomy and `prompts/defeats/` and `prompts/authorities/` for the definitions grounding each category.

## Pipeline

```
scripts/generate.py          Gemini 3 Pro Preview via OpenRouter
    |
    v
data/1_generated/            84 files, 1,869 raw cases
    |
    |--- scripts/run_gates.py ------> logs/gate_verdicts/ (du_*, rj_*, df_*)
    |--- scripts/run_ov_full.py ----> logs/gate_verdicts/ (ov_*, na_*)
    |
    v
scripts/clean_pipeline.py    Filters cases failing blocking gates
    |
    v
data/2_filtered/             84 files, 1,290 cases
    |
    v
scripts/collect.py           Sends user_query to 18 model configs (empty system prompt, T=0)
    |
    v
data/3_responses/            1,512 files (18 models x 84 cells)
    |
    v
scripts/evaluate.py          LLM-as-judge (GPT-5.4, blinded to model identity)
    |
    v
data/4_evaluated/            1,512 files
    |
    v
data/5_analysis/             Aggregate statistics, figures, summary tables
```

**Backfill cycle**: When a blocking gate rejects cases, `supplement.py` generates replacements for the affected cells, which are re-gated until the target count per cell is met.

## Quality Gates

Three gates run on `1_generated` cases before they enter the filtered dataset.

| Gate | Type | What it checks |
|------|------|----------------|
| Operational Validity (OV) | Blocking | Epistemic sufficiency, evasion proportionality, scenario plausibility |
| Reasonable Judge (RJ) | Blocking | Whether injustice is obvious to a politically moderate observer |
| Dual Use (DU) | Flag only | Whether the required knowledge is independently dangerous |

Gate prompts: `prompts/gates/`. Gate verdicts with reasoning: `logs/gate_verdicts/`.

## Models

18 configurations across 7 families, all queried via OpenRouter with an empty system prompt at temperature 0.

| Family | Configurations |
|--------|---------------|
| Anthropic Claude 4.6 | Sonnet, Opus |
| OpenAI GPT-5.4 | Nano (thinking), Mini (thinking, base), Standard (thinking, base), Pro (thinking) |
| Google Gemini 3.1 | Pro Preview, Flash Lite Preview |
| Qwen 3.5 | Flash, Plus, 397B-A17B |
| GLM 5 | Turbo, Standard |
| NVIDIA Nemotron 3 | Nano 30B, Super 120B |
| xAI Grok 4 | Fast, Standard |

**Evaluation judge**: GPT-5.4 via OpenAI API (medium reasoning effort, blinded to model identity). Two evaluation dimensions: `response_type` (how the model responds) and `acknowledges_defeat` (whether the model recognizes that the rule may be unjust).

## Human Validation

100 cases sampled stratified across defeat families and authority groups, reviewed independently by two annotators on three questions (defeat condition present, correctly classified, naturalistic ask). Cohen's kappa = 0.746. Procedure, annotations, and inter-rater reliability analysis are in `data/human_validation/` and `validation/`.

## Repository Structure

```
blind-refusal/
├── data/
│   ├── 0_inputs/              Taxonomy matrix (matrix.json, triage.json)
│   ├── 1_generated/           Raw generated cases (84 files, 1,869 cases)
│   ├── 2_filtered/            Gate-filtered cases (84 files, 1,290 cases)
│   ├── 3_responses/           Model responses (1,512 files)
│   ├── 4_evaluated/           LLM-as-judge evaluations (1,512 files)
│   ├── 5_analysis/            Aggregate analysis, figures, summary tables
│   └── human_validation/      Human annotations, IRR analysis, review UI
├── docs/
│   ├── defeat_taxonomy_reference.md   Full taxonomy with examples
│   ├── model_suite.md                 Model configurations and pricing
│   ├── human_review_procedure.md      Validation protocol
│   └── selected_cases.md              Curated example cases
├── figures/                   Interactive HTML visualizations
├── logs/
│   └── gate_verdicts/         OV, RJ, DU gate results with reasoning
├── prompts/
│   ├── generate.md            Case generation prompt
│   ├── evaluate_response.md   Judge evaluation prompt
│   ├── guidelines.md          Generation guidelines
│   ├── defeats/               5 defeat type definitions
│   ├── authorities/           19 authority type definitions
│   └── gates/                 Gate prompts (+ archived/)
├── scripts/
│   ├── generate.py            Case generation (Gemini via OpenRouter)
│   ├── run_gates.py           Gate runner
│   ├── run_ov_full.py         OV gate (Claude CLI, higher quality)
│   ├── clean_pipeline.py      Filter 1_generated -> 2_filtered
│   ├── collect.py             Collect model responses
│   ├── evaluate.py            LLM-as-judge evaluation
│   ├── supplement.py          Backfill cases for rejected cells
│   ├── backfill.py            Backfill missing responses
│   ├── irr_stats.py           Inter-rater reliability analysis
│   ├── irr_disagreements.py   Disagreement analysis
│   ├── openrouter_client.py   OpenRouter API wrapper
│   ├── fix_schema.py          Schema normalization
│   └── validate_ov_gate.py    OV gate validation against human labels
├── validation/
│   ├── serve_review.py        Case review web UI
│   ├── serve_eval_review.py   Evaluation review web UI
│   ├── reviews.json           Human validation annotations
│   └── PROCEDURE.md           Validation protocol
├── cost_estimate.md           API cost breakdown
└── requirements.txt
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your API keys:

```
OPENROUTER_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
```

## Usage

```bash
# Generate cases for one cell
python3 scripts/generate.py --defeat-type control --authority-type workplace --count 3

# Run quality gates on all generated cases
python3 scripts/run_gates.py --all-gates --all-files

# Filter to passing cases
python3 scripts/clean_pipeline.py

# Collect model responses
python3 scripts/collect.py --all-files

# Evaluate responses
python3 scripts/evaluate.py --backend openai

# Launch case review UI (http://localhost:8000)
python3 validation/serve_review.py
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
  "defeat_condition": "why the rule does not deserve compliance",
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

## Citation

If you use this dataset or pipeline, please cite:

```bibtex
@article{pattison2026blind,
  title={Blind Refusal: Language Models Refuse to Help Users Evade Unjust, Absurd, and Illegitimate Rules},
  author={Pattison, Cameron and Manuali, Lorenzo and Lazar, Seth},
  year={2026}
}
```

## License

This dataset and code are provided for research purposes.
