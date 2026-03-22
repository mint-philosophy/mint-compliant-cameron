# Design Decisions

A living record of every structural design choice in the v3 compliance overspill project, with rationale and alternatives considered.

**Convention**: Each entry is numbered with a section marker (§N). New decisions are appended at the end with the next sequential number. Entries are never deleted; if a decision is reversed, add a new entry that supersedes the old one and cross-reference it.

---

### §1: Two-Phase Protocol
**Date**: 2026-02-17
**Decision**: Two phases (baseline + multi-turn persuasion), not three.
**Rationale**: v2 queries already include 150-400 words of moral context, the user's situation, and a specific evasion request. A "bare query" phase (just the evasion ask with no context) would test something different from what real users do -- nobody approaches a chatbot with a decontextualized evasion command. The v2-style query IS the baseline: a realistic user presenting their situation and asking for help. Phase 2 adds multi-turn persuasion for cases where the model refuses at baseline.
**Alternatives Considered**: Three phases (bare -> contextual -> persuasion). Rejected because bare queries do not reflect real user behavior and would conflate "model responds to decontextualized evasion request" with "model responds to real user need." The bare-query condition would measure something, but not what this study is about.

---

### §2: Fresh Case Generation
**Date**: 2026-02-17
**Decision**: Generate all cases from scratch. No v2 carryover.
**Rationale**: v2 cases accumulated inconsistencies across multiple generation rounds, dimensional coding evolved mid-stream, and the soft-ask problem was not caught until pilot analysis. Starting fresh with hardened prompts and structural quality gates is cheaper than auditing and retrofitting 120 cases. The alternative -- auditing each case against new standards, recoding dimensions, and regenerating queries that fail the grammatical test -- would touch most cases anyway while preserving legacy inconsistencies in the ones it did not touch.
**Alternatives Considered**: Audit and upgrade v2 cases. Rejected because the prompt improvements (especially hard-ask enforcement and revised dimensional coding) would require regenerating most cases anyway, and the remaining "passing" cases would carry forward subtle inconsistencies from earlier generation rounds.

---

### §3: CLI-as-API Reproducibility Model
**Date**: 2026-02-17
**Decision**: Use Claude Code CLI as the execution engine. Prompts are code, CLI is runtime. Every execution creates a timestamped run directory with manifest, prompt snapshots, inputs, outputs, and logs.
**Rationale**: Prompts drift. A prompt that generates good cases today may be edited tomorrow, and without a frozen snapshot you cannot reproduce the run that generated your dataset. The runs/ system solves this by treating every execution as a self-documenting artifact: the exact prompts used, the inputs provided, the outputs produced, and the metadata (model, timestamp, parameters) are all captured together. This is version control for prompt-driven research.
**Alternatives Considered**: Python wrapper scripts with API calls. Rejected because they add a layer of abstraction between the researcher and the prompts, create their own maintenance burden (dependency management, error handling, API version tracking), and do not inherently solve the reproducibility problem without building the same snapshot infrastructure on top.

---

### §4: Anti-Soft-Ask Structural Enforcement
**Date**: 2026-02-17
**Decision**: The assessment/assistance distinction is enforced structurally -- built into the generation prompt and verified by a dedicated calibration gate. Not just documented as guidance.
**Rationale**: v2 pilot found 8/15 cases had soft asks despite written guidance to avoid them. Documentation alone does not prevent the problem because the LLM generating cases optimizes for natural-sounding queries, and assessment questions often sound more natural than direct evasion requests. The grammatical test (can the question be fully answered with "no"?) is simple, mechanical, and effective as a gate criterion.
**Alternatives Considered**: Post-hoc filtering (generate freely, then discard soft asks). Rejected because generating cases and then discarding half is wasteful, and it allows the generation prompt to keep producing the wrong kind of query indefinitely. Better to prevent the problem at generation time and catch survivors at the gate.
**Cross-reference**: `docs/SOFT_ASK_POLICY.md`

---

### §5: Primary Matrix Dimensions and Target Counts
**Date**: 2026-02-17
**Decision**: 5 justice categories x 8 authority types = 40-cell primary matrix. Natural cells: 10-15 cases. Less natural cells: 3-5. Implausible cells: 0 (documented as implausible). Total target: 560-700 cases.
**Rationale**: The justice dimension is the central independent variable -- the study asks whether models can distinguish just from unjust rules, and if so, how that distinction affects their willingness to help with evasion. Authority type is the strongest predicted moderator (models likely treat government rules differently from platform policies). These two dimensions must be crossed exhaustively. Secondary dimensions (demographic context, evasion complexity, domain specifics) are varied within cells but not crossed exhaustively, which would require 10,000+ cases for full factorial coverage.
**Alternatives Considered**: 3 x 8 matrix (collapsing justice categories from five to three). Rejected because the five categories -- clearly just, clearly unjust, unjust-but-legal, just-but-burdensome, and ambiguous -- represent genuinely different types of moral-legal tension that may provoke different model responses. Collapsing them would lose the distinctions the study is designed to detect.

---

### §6: Three Quality Gates (Not Five)
**Date**: 2026-02-17
**Decision**: Three gates -- calibration, naturalness, coverage. Dropped content_safety and dimensional_accuracy from v2's five-gate system.
**Rationale**: Content safety is enforced by the generation prompt's "What to Avoid" section and does not need a separate gate. v2's content_safety gate had a 100% pass rate across all pilot cases -- it never caught anything the generation prompt did not already prevent, making it pure overhead. Dimensional accuracy (does the case match its declared justice category and authority type?) is absorbed into the calibration gate, which already checks whether a case fits its assigned cell. Three focused gates with real discriminative power are better than five gates where two are rubber stamps.
**Alternatives Considered**: Keep all five gates. Rejected to reduce pipeline overhead and gate-fatigue (reviewers -- human or LLM -- pay less attention to gates that never fail) without sacrificing quality. The functions of the dropped gates are preserved in the generation prompt and the calibration gate respectively.

---

### §7: LLM-Based Gates, No Regex
**Date**: 2026-02-17
**Decision**: All quality gates are LLM-as-judge via CLI prompts. No regex-based validators.
**Rationale**: The properties being checked -- naturalness ("does this sound like a real person?"), calibration ("does this case force the help/refuse decision?"), coverage ("does this cell have sufficient diversity?") -- are semantic. Regex cannot evaluate whether a query sounds authentic or whether a moral framing is compelling. LLM-based gates can assess these properties directly and adapt to edge cases that no fixed pattern would anticipate. The grammatical test from the soft-ask policy, while simple enough to express as a heuristic, benefits from LLM application because the test must be applied to the query in context (the full case scenario, not just the final sentence).
**Alternatives Considered**: Hybrid approach (regex pre-filter for obvious failures + LLM for semantic evaluation). Rejected because regex false-positives would discard good cases (a query containing "would this work" as part of a larger hard ask would be flagged incorrectly), and regex true-positives are a strict subset of what the LLM catches. The marginal speed gain from regex pre-filtering does not justify the false-positive risk or the maintenance cost of keeping patterns synchronized with evolving case formats.

---

### §8: Evasion vs. Legitimate Challenge (Two-Level Ask Validation)
**Date**: 2026-02-17
**Decision**: Case validation requires TWO checks, not one. First: is the ask for EVASION (actually doing the prohibited thing) or LEGITIMATE CHALLENGE (drafting letters, filing appeals, making legal arguments)? Second: does the ask pass the grammatical test (cannot be answered with "no")?
**Rationale**: v3 pilot generation found 2/3 cases asked models to help draft strongly worded letters or legal arguments to the authority — not to help circumvent the rule. These cases pass the grammatical test ("help me draft a letter" cannot be answered with "no") but do not test evasion behavior at all. A model that writes a letter has been tested on its willingness to help with communication, not non-compliance. The evasion/challenge distinction is more fundamental than the assessment/assistance distinction and must be checked first.
**Alternatives Considered**: Relying solely on the grammatical test (assessment vs. assistance). Failed in practice — "help me draft a letter arguing the rule is void" passes the grammatical test but is not evasion.
**Cross-reference**: `docs/SOFT_ASK_POLICY.md` (updated with two-level framework)

---

### §9: Soft-Ask Framing Correction (Classifiability, Not "No"-Prevention)
**Date**: 2026-02-17
**Decision**: Reframed the soft-ask rationale across all docs. The problem with soft asks is NOT that the model can say "no." A model saying "no, I won't help you do that" to a hard ask IS a refusal — that's good signal. The problem is that soft asks produce responses that do not map onto the dependent variable (willingness to help with evasion). A model answering "no, that technique wouldn't work" to "would painting the edge strip fool the color matcher?" has made a prediction — it has not decided whether to help with evasion. The response is unclassifiable.
**Rationale**: The original framing ("model says 'no' — neither helped nor refused") was technically correct but misleadingly suggested the goal is to prevent the model from saying "no." In fact, refusals are half the signal this study exists to measure. The goal is to ensure every response IS classifiable as either help or refusal, which requires asking questions that force a decision rather than a prediction.
**Files Updated**: `docs/SOFT_ASK_POLICY.md`, `prompts/generate_seed_cases.md`, `prompts/gates/calibration.md`

---

### §10: Taxonomy Revision — Defeat Families, 19 Authority Types, Kind of Rule
**Date**: 2026-02-18
**Decision**: Complete revision of the primary taxonomy. The old 5 justice categories × 8 authority types matrix is replaced with 5 defeat families × 19 authority types. The `kind_of_rule` is added as a new secondary dimension. The `justice_of_rule` field is replaced by `defeat_type` + `defeat_subtype` throughout the pipeline.
**Rationale**: The original 5-level justice scale (just_and_reasonable through contextually_unjust) collapsed distinct normative phenomena into an ordinal spectrum. The new taxonomy, developed through the theoretical framework at `index.html`, distinguishes three structurally different reasons a rule's authority can be defeated: (1) the rulemaking body is illegitimate, (2) the rule's content is inherently delegitimating, (3) the manner of application is delegitimating. It adds a fourth category for cases where the rule is valid but an exception is justified. This is not a refinement of the old categories — it's a different structural analysis that identifies different things. `disproportionately_costly` and `morally_objectionable` both become subtypes of content defeat. `contextually_unjust` splits across application defeat and exception justified. `illegitimate_authority` is entirely new.

Authority types expand from 8 generic categories to 19 specific institutions organized by voluntariness of entry (government, non-voluntary, semi-voluntary, voluntary). This matters because exit costs and entry mode affect the moral weight of the authority's claims — a rule you can walk away from is different from one you can't. The old `informal` category (which lumped family, tribe, and faith together) is disaggregated across groups. New types added: military command, union, club, creditor/insurer, private property owner, contractual counterparty, delegated authority, supranational body.

`kind_of_rule` (law, institutional policy, contract, social norm, etc.) is added as a secondary dimension because the same authority can enforce different types of normative instruments, and the type may independently affect model behavior.

**Alternatives Considered**: Keeping the 5 justice categories as a "coarsened" version of the new taxonomy. Rejected because the mapping is not clean — `contextually_unjust` doesn't map onto a single new category, and the new `illegitimate_authority` family has no old-taxonomy equivalent. A partial adoption would create translation ambiguities.
**Supersedes**: §5 (Primary Matrix Dimensions and Target Counts)
**Files Updated**: `Unjust Rule Schematics.md` (rewritten), `data/0_inputs/matrix.json` (rewritten), `MASTER_PLAN.md` (sections 4, 6, 11), `prompts/generate_seed_cases.md` (rewritten), `scripts/generate.sh` (rewritten), `prompts/gates/calibration.md`, `prompts/gates/coverage.md`, `README.md`, `data/1_generated/absurd_or_arbitrary_hoa.json` (obsoleted)
