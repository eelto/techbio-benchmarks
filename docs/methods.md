# Methods and data page (draft)

Draft text for the site's methods and data pages. The site renders its own copy. This file is the
source of truth, and changes to it go through a PR. Sections marked **(operator-confirmed)** use
wording the operator fixed. Everything else is a draft for review before launch.

---

## 1. What we measure

- **Static benchmarks:** how frontier models score on published biology benchmarks, run with the
  benchmark authors' official graders and checked against published results.
- **Forecasting arena:** how well models forecast real, still-unresolved biotech catalysts (Phase
  2b/3 readouts, FDA decisions, advisory committee votes). Outcomes don't exist when the forecast is
  made, so this part can't be contaminated by training data.

## 2. Independence and conflicts of interest (operator-confirmed)

Conflict-of-interest policy, in the operator's words:

- no trading by me in any sponsor while forecasts on its events are open
- my holdings disclosed in aggregate annually
- all labels and forecasts are hashed and public before resolution so nothing can be shaded after the fact
- evaluation credits and any future sponsors are disclosed and never influence model selection, settings, or benchmark inclusion

Annual holdings disclosure: _[first disclosure, date]_.

### Evaluation credits and sponsors

| Provider | Amount | Dates | Terms |
|---|---|---|---|
| _none yet_ | | | |

Every provider is offered the same terms (`docs/credit-request-email.md`): disclosure here, no
influence on models or settings, results published regardless, no preview.

### Pending disclosure (operator to decide, Q-E2)

Whether to state that the pipeline code was written with assistance from Claude (Anthropic, an
evaluated provider). Proposed default: yes.

## 3. Models and settings

- **Roster rule:** each provider's top-tier, generally available API model, as listed on that
  provider's own model-overview page. Price plays no part. Launch roster: GPT-6 Astra, Claude Fable
  5.1, Gemini 4 Argon, Grok 4.7, Muse Wonder 1.0, and the leading open-weight model (GLM-5.3).
  Mid-tier models, starting with Claude Opus 5.5, enter later on their own model-days for the
  cost-per-point chart.
- **Uniform settings:** prompts, decoding, and reasoning settings are set per tier in a public config
  and are identical across providers.
- **Reasoning:** capped at a documented low/medium level on every benchmark item. The single top
  model per benchmark is also run uncapped, and the difference is published as a finding: what
  reasoning buys in biology.
- **Sampling:** most current flagships no longer accept temperature 0, so every model call is a
  random draw. Arena forecasts are the **mean of 2 independent samples**. The spread is published,
  and all raw draws are stored. Where a provider supports a seed parameter, it is set and recorded.

## 4. Static benchmarks

- **Setup:** every headline number uses the benchmark authors' official setup. For LAB-Bench that
  is FutureHouse's own prompt, answer parser, and scorer. Our anchor preprint (arXiv 2505.06108)
  used a different setup (zero-shot, letter answer, no "insufficient information" option). Older
  models with published preprint scores are run both ways, and the measured gap is listed in the
  validation report's deviations.
- **Samples and intervals:** one sample per item, with 95% intervals from an item-level bootstrap.
  The LAB-Bench headline run for the top three models gets a second sample, and the seed-to-seed
  difference is reported.
- **Subsets:** LitQA2 is a fixed random subsample of about 100 items. SeqQA, DbQA,
  CloningScenarios, and ProtocolQA run in full at launch, except that SeqQA and DbQA use the
  sequential rule below.
- **Sequential evaluation:** for benchmarks over 200 items, items are run in one fixed random order
  (the same for every model), and a model stops at the first pre-declared checkpoint where its 95%
  interval is narrow enough. The interval is adjusted for the number of checkpoints, so stopping
  early doesn't overstate precision. Every result reports n and the checkpoint where it stopped.
- **New models (model-days):** run on anchor subsets of about 100 items per large benchmark, selected
  from the full launch runs and validated against them and against published scores. The predicted
  full-set score is published with its interval and marked as anchor-based.
- **Saturated benchmarks:** MMLU-Bio and PubMedQA are checked on a 50-item pilot. If the pilot
  confirms they are saturated for current flagships, they aren't run further, and we cite the
  preprint's results. _(Wording to finalize after the pilot.)_
- **Expert baselines and normalized scores:** normalized score = (model − expert) / (1 − expert),
  only where a published aggregate expert baseline exists.
  - **SeqQA and DbQA report raw accuracy only.** No aggregate expert baseline exists: the LAB-Bench
    paper reports human performance per subtask, with partial coverage.
  - **There is no MMLU-Bio expert line.** The figure often quoted (89.8%) is the MMLU paper's
    estimate for experts across all MMLU subjects, not a biology-specific measurement. We don't
    substitute a general figure.
- **Vendor-built benchmarks:** LifeSciBench, MedChemBench, and GeneBench were built by a model
  provider. Their scores appear only in the vendor-reported table, never on an independent
  leaderboard, until an independent, reproducible setup exists.
- **Contamination:** static benchmarks can't establish that a model never saw the items in training.
  The forecasting arena is the contamination-proof measurement.

## 5. Forecasting arena

- **Rounds:** every 14 days, on events expected to resolve 21–90 days later. Models see a frozen,
  hashed information pack and nothing published after the run timestamp. The hash of every round's
  forecasts is published before any of its events resolves.
- **Scoring:** Brier score and log loss on the published forecast (the mean of the two draws), with
  event-level bootstrap intervals, against three baselines: the ledger base rate as of the run, the
  market-implied probability, and 0.5. Per-model rankings appear only once a model version has at
  least 100 resolved forecasts.
- **Void rule (operator-confirmed):** an event is voided only if it is cancelled or the trial is
  stopped for reasons unrelated to its outcome (financing, strategic, acquisition). Anything resolved
  by data is scored. **Every voided event is listed in the exports with its reason.** Separately, a
  forecast is void if its event resolved before the round's commitment, and those are counted too.
- **Market baseline:** computed internally from Kalshi. Until the operator confirms display rights,
  exports carry only whether each model beat the market on each event, and aggregate comparisons.
  **Market prices are never exported.**
- **Outcome confirmation:** the operator confirms every outcome that is scored, so no model alone
  ever decides a score that ranks models.

## 6. Data page: licenses and what is released

- **Code:** MIT. **Data:** CC BY-NC 4.0, except as below.
- **Ledger exports:** structured facts (dates, categories, identifiers) and links to primary sources.
  Never press-release or filing text, and never figure images.
- **Per-item benchmark results:** item IDs, model outputs, and grades. **Never question text.** A
  script in the repo fetches the items from their original source, so anyone with access to the
  benchmark can rejoin them.
  - **LAB-Bench-derived files are released under CC BY-SA 4.0**, matching LAB-Bench's license.
  - **GPQA:** at the GPQA authors' request that items not be revealed online, per-item results are
    released as **correct/incorrect by hashed item ID only, with no model outputs**.
- **Corrections:** every label change creates a new version. The change log ships with each release
  (Q-E4).

## 7. Reviewers

Validation packet reviewers: _[names, once confirmed]_.
