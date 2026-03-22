# Methods Literature Review: Benchmark Design, Evaluation, and Validation

## E. Synthetic Benchmark Construction

The compliance overspill benchmark generates 791 synthetic cases using LLMs. This places it within a rapidly growing methodological tradition that carries both advantages and documented risks.

The construct validity question comes first. Barr et al. (2025) found that 78.2% of LLM benchmarks define their target phenomenon, but only 53.4% justify why they validly measure it. Russak et al. (2025) complement this with quantitative methods that separate benchmark results from underlying capabilities. Bowman (2021) articulated four criteria for sound benchmarks -- artifact-free design, reliable annotation, sufficient scale, and responsible handling of social bias -- and argued that most NLU benchmarks fail on at least one. BetterBench (Reuel et al., 2024) codified 46 best practices spanning the full benchmark lifecycle and found large quality differences even among major benchmarks. BenchmarkCards (Bai et al., 2025) proposed standardized documentation templates. These papers collectively establish that benchmark quality requires deliberate justification, not just technical execution.

The design of synthetic evaluation data has its own sub-literature. Zellers (2019) introduced Adversarial Filtering, iteratively selecting machine-generated items that are obvious to humans but misclassified by models. S3Eval (Lei et al., 2024) demonstrated that fully synthetic data can avoid contamination while maintaining validity through correlation with real-world benchmarks. LiveBench (White et al., 2024) achieved contamination resistance through temporal freshness and automated scoring. Xu et al. (2024) surveyed contamination at two levels -- semantic (identical content in training data) and informational (metadata, distributions) -- and documented that GPT-4 shows 57% exact match rates on MMLU options, indicating significant contamination in static benchmarks.

A critical caution for the compliance overspill project comes from Baroni et al. (2025): LLM-generated benchmarks are systematically less challenging for LLMs than human-authored counterparts, and synthetic data may not preserve model rankings. The ease of synthetic benchmarks is not explained by systematic biases. Human-authored data contains contextual complexity that LLM generation misses even when the surface format is matched. The large-scale collaborative benchmarks -- HELM (Liang et al., 2023) with its 7-metric, 16-scenario framework, BIG-bench (Srivastava et al., 2023) with 204 tasks, and MMLU (Hendrycks et al., 2021) with 57 subjects -- provide models for multi-dimensional design at scale that the compliance overspill project's matrix of authority types and defeat families follows.

**Connection to the project**: The 791 synthetic cases are LLM-generated (Gemini), placing the project squarely in the construct validity debate. Baroni et al.'s finding that synthetic data is systematically easier than human-authored data means the benchmark may underestimate the severity of compliance overspill in naturalistic settings. The matrix design (crossing authority types with defeat conditions) follows the multi-dimensional logic of HELM and MMLU. Contamination is less of a concern for synthetic cases (they did not exist in training data), but the informational contamination category from Xu et al. -- where models recognize the *structure* of benchmark items -- remains a risk.

| Author(s) | Year | Title | Venue | Rel. | Support | PDF |
|:---|:---|:---|:---|:---:|:---|:---|
| Barr et al. | 2025 | Measuring what Matters: Construct Validity in LLM Benchmarks | arXiv | 5 | emerging | open |
| Zheng et al. | 2023 | Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena | NeurIPS 2023 | 5 | foundational | open |
| Reuel et al. | 2024 | BetterBench: Assessing AI Benchmarks | NeurIPS 2024 (Spotlight) | 5 | emerging | open |
| Bowman | 2021 | What Will it Take to Fix Benchmarking in NLU? | NAACL-HLT 2021 | 5 | well-established | open |
| Baroni et al. | 2025 | What Has Been Lost with Synthetic Evaluation? | arXiv | 5 | emerging | preprint |
| Liang et al. | 2023 | Holistic Evaluation of Language Models | TMLR | 4 | foundational | open |
| Srivastava et al. | 2023 | Beyond the Imitation Game (BIG-bench) | TMLR | 4 | foundational | open |
| Zellers | 2019 | HellaSwag: Can a Machine Really Finish Your Sentence? | ACL 2019 | 4 | foundational | open |
| Hendrycks et al. | 2021 | Measuring Massive Multitask Language Understanding | ICLR 2021 | 4 | foundational | open |
| Bai et al. | 2025 | BenchmarkCards: Standardized Documentation for LLM Benchmarks | NeurIPS 2025 | 4 | emerging | open |
| Xu et al. | 2024 | Benchmark Data Contamination of LLMs: A Survey | arXiv | 4 | well-established | open |
| Lei et al. | 2024 | S3Eval: Synthetic, Scalable, Systematic Evaluation | NAACL 2024 | 4 | emerging | open |
| White et al. | 2024 | LiveBench: A Contamination-Limited LLM Benchmark | ICLR 2025 (Spotlight) | 3 | emerging | open |
| Russak et al. | 2025 | Quantifying Construct Validity in LLM Evaluations | arXiv | 3 | emerging | preprint |

---

## F. LLM-as-Judge Methodology

The compliance overspill project uses Gemini as an LLM judge to classify 3,096 model responses across 9 dimensions. This methodology has strong empirical support -- and well-characterized failure modes.

Zheng et al. (2023) established the paradigm with MT-Bench and Chatbot Arena, showing that GPT-4 matches human preference agreement at >80% and identifying three systematic biases: position (favoring responses by placement), verbosity (preferring longer answers), and self-enhancement (favoring own outputs). Panickssery et al. (2024) confirmed the self-preference bias causally: LLMs distinguish their own generations from others' with non-trivial accuracy, and self-recognition drives self-preference. For the compliance overspill project, which uses Gemini to judge outputs from multiple models including Gemini variants, this is a concrete validity threat. Ye et al. (2024) extended the taxonomy to 12 bias types, several directly relevant here: authority bias (responses citing safety guidelines may receive unwarranted credibility from a judge trained on the same guidelines), verbosity bias (refusals are shorter than compliant responses), and sentiment bias.

The rubric-based evaluation approach the project uses has strong precedent. FLASK (Ye et al., 2024) decomposed evaluation into 12 fine-grained skills and demonstrated that multi-dimensional evaluation increases both interpretability and human-model correlation. Prometheus (Kim et al., 2024) showed that open-source models can match GPT-4's evaluation capability when fine-tuned on rubric-based feedback data. LLM-Rubric (Hashemi et al., 2024) -- the closest methodological analog to the project -- uses a 9-question rubric framework, achieving 2x error reduction compared to uncalibrated holistic evaluation by leveraging LLM probability distributions over rubric responses. Prometheus 2 (Kim et al., 2024) unified direct assessment and pairwise ranking, validating that structured criteria enable domain-specific evaluation.

The limitations literature is equally relevant. Shankar et al. (2024) identified "criteria drift" as a fundamental challenge: evaluation criteria and outputs co-evolve rather than being independently definable. For normatively loaded categories like "refusal reasoning" or "compliance overspill," this means the judge's interpretation may shift across the evaluation. Dubois et al. (2024) demonstrated that length bias is tractable with regression-based debiasing, improving correlation with human preferences from 0.94 to 0.98. AlpacaFarm (Dubois et al., 2023) and Chiang and Lee (2023) validated that LLM judgments can substitute for human annotation when properly calibrated. Kocmi and Federmann (2023) showed this extends to specialized domains. Gu et al. (2024) surveyed the full LLM-as-Judge field, identifying prompt engineering, multi-judge panels, and domain adaptation as key reliability strategies. Zheng et al. (2025) sounded a cautionary note: null models (constant outputs) achieve top-tier scores on automatic benchmarks, exposing the susceptibility of LLM judges to stylistic manipulation independent of content quality.

**Connection to the project**: The 9-dimensional classification scheme follows the FLASK/LLM-Rubric multi-dimensional model, which has documented advantages over holistic scoring. The use of Gemini as both a case generator and judge raises self-enhancement concerns (Panickssery et al., 2024). Position and verbosity biases are relevant because refusal responses differ structurally from compliant ones. Human validation of judge outputs (Phase 1 of the project) is the standard mitigation, and the 0.746 kappa reported suggests adequate but not strong calibration.

| Author(s) | Year | Title | Venue | Rel. | Support | PDF |
|:---|:---|:---|:---|:---:|:---|:---|
| Kim et al. | 2024 | Prometheus: Fine-grained Evaluation in Language Models | ICLR 2024 | 5 | well-established | open |
| Ye et al. | 2024 | FLASK: Fine-grained Evaluation based on Alignment Skill Sets | ICLR 2024 (Spotlight) | 5 | well-established | open |
| Shankar et al. | 2024 | Who Validates the Validators? | UIST 2024 | 5 | emerging | open |
| Ye et al. | 2024 | Justice or Prejudice? Biases in LLM-as-a-Judge | arXiv | 5 | emerging | open |
| Panickssery et al. | 2024 | LLM Evaluators Recognize and Favor Their Own Generations | NeurIPS 2024 (Oral) | 5 | well-established | open |
| Hashemi et al. | 2024 | LLM-Rubric: Multidimensional Calibrated Evaluation | ACL 2024 | 5 | well-established | open |
| Zheng et al. | 2023 | Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena | NeurIPS 2023 | 5 | foundational | open |
| Kim et al. | 2024 | Prometheus 2: Open Source Evaluation Model | EMNLP 2024 | 4 | well-established | open |
| Dubois et al. | 2024 | Length-Controlled AlpacaEval | ICLR 2025 | 4 | well-established | open |
| Gu et al. | 2024 | A Survey on LLM-as-a-Judge | arXiv | 4 | emerging | open |
| Zheng et al. | 2025 | Cheating Automatic LLM Benchmarks: Null Models Achieve High Win Rates | ICLR 2025 | 4 | emerging | open |
| Dubois et al. | 2023 | AlpacaFarm: Simulation Framework for Human Feedback Methods | NeurIPS 2023 (Spotlight) | 3 | foundational | open |
| Chiang and Lee | 2023 | Can LLMs Be an Alternative to Human Evaluations? | ACL 2023 | 3 | well-established | open |
| Kocmi and Federmann | 2023 | LLMs Are SOTA Evaluators of Translation Quality | EAMT 2023 | 3 | well-established | open |

---

## G. Human Validation and Inter-Rater Reliability

The compliance overspill project reports a Phase 1 kappa of 0.746 on 100 cases. Interpreting this number requires the full apparatus of the IRR literature.

Cohen (1960) defined kappa as a chance-corrected agreement measure, and it remains the default in NLP annotation. Krippendorff (2019) proposed alpha as a more general alternative that handles any number of raters, missing data, and different measurement scales, with thresholds of 0.80 for reliable conclusions and 0.67-0.80 for tentative ones. Artstein and Poesio (2008) -- the definitive survey for computational linguistics -- clarified when each measure is appropriate: kappa for identified raters with stable biases, alpha for interchangeable raters. Sim and Wright (2005) showed that kappa's magnitude is affected by prevalence and rater bias, not just true agreement: low prevalence can produce low kappa even with high percentage agreement. Bujang and Baharum (2017) provided sample size guidelines; for binary classification with equal marginals, 15-28 cases may suffice for large effects, but narrower comparisons (kappa = 0.70 vs. 0.80) require much larger samples. Whether 100 cases is sufficient depends on the effect size being tested and the marginal distributions of the project's categories.

The deeper question is what disagreement means. Plank (2022) argued that the single-ground-truth assumption is often false for subjective tasks, and that aggregation methods (majority vote, adjudication) systematically erase meaningful variation. Pavlick and Kwiatkowski (2019) showed that NLI disagreement is structurally inherent, not noise -- more data does not eliminate it. Rottger et al. (2022) distinguished prescriptive annotation (minimize variation through clear guidelines) from descriptive annotation (preserve variation as signal about the range of valid interpretations), arguing the choice depends on downstream use. For compliance overspill, where "overspill" is a normatively contested concept, this distinction matters: disagreement between annotators may reflect genuine philosophical disagreement about when refusal is appropriate rather than annotation error.

Uma et al. (2021) surveyed soft-label approaches and found that training with probability distributions over categories outperforms aggregated hard labels when sufficient annotations are available. Passonneau (2014) argued that probabilistic annotation models estimating item difficulty and annotator reliability jointly produce higher-quality labels than majority voting. Basile et al. (2021) argued that minimizing disagreement is a "gross oversimplification" and that three sources of disagreement (annotator, data, context) should be documented separately. Wong et al. (2021) challenged the practice of interpreting kappa against arbitrary thresholds (Landis and Koch's "substantial" > 0.61), arguing that a kappa of 0.60 might be excellent for one task and poor for another; their cross-replication reliability (xRR) approach measures whether replicated annotation produces the same aggregate labels. Bayerl and Paul (2011) provided meta-analytic evidence that guideline complexity, annotator expertise, number of categories, and domain all significantly affect agreement. Gorman and Bedrick (2019) connected annotation agreement to benchmark reliability, showing that items with low inter-annotator agreement destabilize system rankings. Daniel et al. (2018) surveyed quality control for crowdsourced annotation, covering task design, worker selection, and output assessment.

**Connection to the project**: The 0.746 kappa falls below Krippendorff's 0.80 threshold for reliable conclusions but above his 0.67 floor for tentative ones. Given that compliance overspill classification involves normative judgment (not just pattern recognition), this level of agreement is expected. The key question is whether the disagreement is structured -- concentrated on inherently ambiguous cases -- or distributed randomly. If structured, the Plank/Pavlick tradition suggests modeling disagreement rather than resolving it. The project should report prevalence-adjusted kappa or PABAK alongside raw kappa, given Sim and Wright's (2005) warning about prevalence effects.

| Author(s) | Year | Title | Venue | Rel. | Support | PDF |
|:---|:---|:---|:---|:---:|:---|:---|
| Cohen | 1960 | A Coefficient of Agreement for Nominal Scales | Educ. Psych. Measurement | 5 | foundational | paywall |
| Krippendorff | 2019 | Content Analysis (4th ed.) | SAGE (book) | 5 | foundational | paywall |
| Artstein and Poesio | 2008 | Inter-Coder Agreement for Computational Linguistics | Computational Linguistics | 5 | foundational | open |
| Sim and Wright | 2005 | Kappa Statistic in Reliability Studies | Physical Therapy | 5 | well-established | open |
| Plank | 2022 | The 'Problem' of Human Label Variation | EMNLP 2022 | 5 | well-established | open |
| Pavlick and Kwiatkowski | 2019 | Inherent Disagreements in Human Textual Inferences | TACL | 5 | well-established | open |
| Rottger et al. | 2022 | Two Contrasting Data Annotation Paradigms | NAACL 2022 | 5 | well-established | open |
| Uma et al. | 2021 | Learning from Disagreement: A Survey | JAIR | 5 | well-established | open |
| Passonneau | 2014 | The Benefits of a Model of Annotation | TACL | 4 | well-established | open |
| Basile et al. | 2021 | We Need to Consider Disagreement in Evaluation | BPPF 2021 | 4 | emerging | open |
| Bayerl and Paul | 2011 | Determinants of Inter-Coder Agreement | Computational Linguistics | 4 | well-established | open |
| Wong et al. | 2021 | Cross-replication Reliability | ACL-IJCNLP 2021 | 4 | emerging | open |
| Bujang and Baharum | 2017 | Minimum Sample Size for Cohen's Kappa | Epidemiol. Biostat. Public Health | 4 | well-established | open |
| Daniel et al. | 2018 | Quality Control in Crowdsourcing: A Survey | ACM Computing Surveys | 3 | well-established | preprint |
| Gorman and Bedrick | 2019 | We Need to Talk about Standard Splits | ACL 2019 | 3 | well-established | open |

---

## H. Behavioral Classification and Response Taxonomies

Classifying LLM outputs requires a taxonomy fine-grained enough to capture meaningful behavioral distinctions but coarse enough to achieve reliable annotation. The compliance overspill project uses a 9-dimension classification scheme; the literature offers both models and warnings.

Bai et al. (2022) established the foundational helpful/harmless binary that structures the field. Llama Guard (Inan et al., 2023) showed that an LLM can serve as a reliable classifier against a customizable safety taxonomy, matching or exceeding purpose-built classifiers. SORRY-Bench (Xie et al., 2024) developed the most granular safety taxonomy to date with 45 categories and demonstrated that surface-level linguistic variation (language, dialect, style) affects refusal rates even for identical harmful content -- a finding relevant to compliance overspill, where framing effects may influence whether models recognize a rule as unjust. Demleitner et al. (2024) introduced a distinction between epistemic ("cannot") and normative ("should not") refusals with a 16-category taxonomy, and showed that cost-effective specialized classifiers can outperform expensive LLMs (including GPT-4) on fine-grained refusal classification. This cannot/should-not distinction maps directly onto the project's need to separate refusals based on genuine safety concerns from refusals based on misidentified risk.

SALAD-Bench (Li et al., 2024) modeled hierarchical classification with 6 domains, 16 tasks, and 66 categories. SimpleSafetyTests (Vidgen et al., 2024) showed that minimal, well-designed test suites (100 prompts, 5 categories) can reliably identify critical safety gaps, finding dramatic differences between open-source models (27% unsafe response rate) and closed-source models (2%). Wilkens et al. (2024) provided the theoretical framework the project implicitly relies on: Signal Detection Theory, which distinguishes sensitivity (ability to discriminate safe from unsafe content) from response bias (threshold for flagging content as unsafe). High false positive rates (overrefusal) and false negative rates (safety failures) are not independent -- they are determined by the same underlying signal detection parameters. A model with high response bias will over-refuse; adjusting it reduces overrefusal but increases safety failures. The compliance overspill benchmark measures response bias specifically in the domain of rule-following.

**Connection to the project**: The 9-dimension classification scheme is more granular than the foundational binary (Bai et al., 2022) but less granular than SORRY-Bench's 45 categories or Demleitner et al.'s 16-category refusal taxonomy. The Demleitner cannot/should-not distinction is the closest existing analog to the project's distinction between legitimate refusal and compliance overspill. The Signal Detection Theory framing (Wilkens et al., 2024) provides the formal apparatus for discussing the tradeoff the benchmark measures.

| Author(s) | Year | Title | Venue | Rel. | Support | PDF |
|:---|:---|:---|:---|:---:|:---|:---|
| Bai et al. | 2022 | Training a Helpful and Harmless Assistant with RLHF | arXiv (Anthropic) | 5 | foundational | open |
| Inan et al. | 2023 | Llama Guard: LLM-based Input-Output Safeguard | arXiv (Meta) | 5 | well-established | open |
| Xie et al. | 2024 | SORRY-Bench: Evaluating Safety Refusal Behaviors | ICLR 2025 | 5 | well-established | open |
| Demleitner et al. | 2024 | Cannot or Should Not? Analysis of Refusal Composition | EMNLP 2025 | 5 | emerging | open |
| Li et al. | 2024 | SALAD-Bench: Hierarchical Safety Benchmark | Findings of ACL 2024 | 3 | well-established | open |
| Vidgen et al. | 2024 | SimpleSafetyTests: Identifying Critical Safety Risks | arXiv | 3 | well-established | open |
| Wilkens et al. | 2024 | Effective Human Oversight: A Signal Detection Perspective | Minds and Machines | 4 | emerging | paywall |

---

## Methodological Implications

Drawing on the 49 papers in Domains E-H, the following recommendations apply to the compliance overspill project:

**1. Construct validity requires explicit justification.** Barr et al. (2025) found that nearly half of benchmarks do not justify why they validly measure their target phenomenon. The project should articulate why its synthetic cases validly test the defeat conditions they claim to test -- not just that the cases exist, but that LLM responses to them reveal something about compliance overspill as a behavioral disposition. The BetterBench 46-point checklist (Reuel et al., 2024) provides a concrete validation framework.

**2. Synthetic data introduces a documented downward bias on difficulty.** Baroni et al. (2025) showed that LLM-generated benchmarks are systematically easier for LLMs. The project should acknowledge this as a limitation: compliance overspill rates measured on synthetic cases may *underestimate* the phenomenon in naturalistic settings. This strengthens the project's findings (if models over-comply even on cases designed by an LLM, they will likely over-comply more on real-world cases) but must be stated explicitly.

**3. Self-preference bias in the LLM judge demands mitigation.** Panickssery et al. (2024) established that LLM judges favor their own outputs. Using Gemini as both case generator and judge, and potentially as one of the evaluated models, compounds this risk. The project should report whether Gemini-evaluated Gemini responses differ systematically from Gemini-evaluated responses from other models. If Phase 2 is feasible, a second judge model would provide a cross-validation check.

**4. The kappa of 0.746 should be reported with prevalence context.** Sim and Wright (2005) showed kappa is sensitive to category prevalence. If compliance overspill is rare in the dataset (most responses are straightforwardly compliant or straightforwardly refused), kappa may be deflated. Prevalence-adjusted kappa (PABAK) or kappa per category would give a more interpretable picture. Wong et al.'s (2021) cross-replication reliability provides an alternative: would a different pair of annotators produce the same aggregate classifications?

**5. Disagreement on normatively loaded items is signal, not noise.** Plank (2022), Pavlick and Kwiatkowski (2019), and Rottger et al. (2022) all argue that for subjective tasks, annotator disagreement reflects genuine ambiguity. The project should identify which of its 9 dimensions produce the most disagreement and interpret high-disagreement dimensions as marking the boundaries of the compliance overspill concept rather than annotation failure.

**6. Multi-dimensional classification outperforms holistic scoring.** FLASK (Ye et al., 2024), LLM-Rubric (Hashemi et al., 2024), and Prometheus (Kim et al., 2024) all demonstrate that rubric-based, dimension-specific evaluation is more reliable and interpretable than single-score assessment. The project's 9-dimension scheme is well-supported by this literature.

**7. Response classification should distinguish epistemic from normative refusals.** Demleitner et al.'s (2024) cannot/should-not distinction is directly applicable. A model that refuses because it genuinely cannot help (capability limitation) differs from one that refuses because it judges the request to violate a rule (normative refusal). The compliance overspill concept applies only to the latter. Ensuring the classification scheme captures this distinction is methodologically important.
