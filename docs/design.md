# Design: repo layout, data model, flows, milestones

Status: **v2** (2026-10-30), updated for the operator's Step 1 decisions (`docs/decisions.md`).
Remaining open items are referenced as `Q-xx` and listed in `docs/questions.md`.

---

## 1. Repo layout

```
techbio-benchmarks/
├── CLAUDE.md                 standards, budget rules, conventions, critical pieces
├── README.md                 what this is, licenses (code MIT · data CC BY-NC 4.0), how to cite
├── LICENSE                   MIT
├── LICENSE-DATA              CC BY-NC 4.0
├── pyproject.toml · uv.lock  single package, src layout
├── Makefile                  refresh · round · model-day · validate · test · lint
├── .env.example              names of every secret, no values
├── config/
│   ├── models.yaml           model registry: role, provider, exact version, date_added, prices, decoding, reasoning cap
│   ├── budget.yaml           per-job hard caps, monthly cap, standing pre-approvals (amount, scope, date)
│   ├── sources.yaml          ingestion endpoints, rate limits, SEC User-Agent, universe filter
│   ├── arena.yaml            cadence 14d, window [21, 90], horizon buckets, power n=100, clip ε,
│   │                         samples_per_model: 2, seed_param: set_if_supported,
│   │                         market_baseline: {venue: kalshi, export_prices: false, terms_confirmed: false}
│   └── benchmarks.yaml       launch set, subsets, manifests, seeds, sequential rule, reasoning tiers,
│                             denylist (VCT, WMDP, ABC-Bench…)
├── schema/
│   └── v1.json               the site contract (JSON Schema 2020-12); v0 is unstable until launch
├── src/techbio/
│   ├── core/                 db + migrations, config, ids, time, hashing, asof (bitemporal), spend guard,
│   │   └── llm/              provider batch clients, completion cache, cost accounting
│   ├── ledger/
│   │   ├── ingest/           universe, edgar, ctgov, drugsfda, crl, fda_press, adcom, ir_pages, markets
│   │   ├── extract/          prompts, two-model run, agreement, tie-break, routing, quote verification
│   │   ├── resolve.py        primary-source resolution, outcome→binary mapping (by taxonomy version)
│   │   ├── slip.py           guided-vs-actual, median slip per event type
│   │   └── review.py         `ledger review` CLI
│   ├── forecast/             select · pack · prompt · run · commit · baselines · score
│   ├── harness/
│   │   ├── tasks/            thin wrappers over inspect_evals / official graders (no custom scoring)
│   │   ├── run.py            pilot / launch / model-day (anchors), sequential rule, Inspect batch mode
│   │   ├── normalize.py      expert-normalized score, saturation flag
│   │   └── validation/       anchor table, deviations, seed variance, per-item export, reviewer packet
│   └── publish/              export, schema validation, charts (Vega-Lite → PNG), issues, social card, release
├── charts/                   committed Vega-Lite specs
├── docs/                     design, taxonomy, decisions, methods, questions, cost-estimates, validation/
├── scripts/                  plan_costs.py (planning cost model), fetch_items.py (rejoins per-item exports
│                             with benchmark text from the original source; M3c)
├── exports/
│   ├── commitments/          <run_id>.json, committed to git (never edited)
│   └── latest/               JSON + CSV written by `make refresh` (see Q-F4 on committing vs release-only)
├── tests/
│   ├── fixtures/             fixture DB, synthetic documents (no real press-release text), recorded API responses
│   └── …                     see §7
├── data/                     GITIGNORED: ledger.sqlite, raw/ (docs by sha256), cache/ (completions), packs/
└── .github/workflows/        ci.yml · daily-refresh.yml · arena-round.yml
```

I chose a src layout with one package (`techbio`) over four top-level directories so that all four
packages share `core/` (db, spend guard, cache, as-of logic) without path hacks, and so the leakage
and spend code exists in exactly one place.

**LLM access** goes through two paths, and both report to the same spend ledger:
- **Ledger and arena** use `core/llm`, a thin layer over each provider's official SDK and batch API.
  These jobs need full control over the cache key, raw outputs, and commitments.
- **Harness** uses Inspect AI, so that the official tasks and graders run unmodified. Token usage is
  read back from Inspect logs into `spend_ledger`.

**Batch everywhere, with three exceptions** (all recorded in `models.yaml`; the first two are Q-G2):
- Inspect's Gemini batch mode can't use thinking, so Gemini harness runs are synchronous unless we
  add our own batch client.
- Meta's API has no batch endpoint, so Muse Wonder runs synchronously on every path.
- The pilot-only tie-break reference is a local open-weight model (Ollama), with no batch path and
  no spend (decisions P.1 and P.3). The ledger tie-breaker itself, Gemini, runs on our own Google
  batch client from 2026-11-03 (decisions C.3).

**Prompt caching** covers shared instructions on every path. LitQA2 items carry no paper text in the
official setup, so there is no shared paper context to cache (Q-G1).

---

## 2. Data model

Notation: `PK` primary key, `FK` foreign key, `?` nullable. Every table carries `created_recorded_at`.
Types are portable (TEXT, INTEGER, REAL, BOOLEAN, JSON, TIMESTAMP WITH TZ via SQLAlchemy). The five
tables named in the brief are marked ★. The others are additions I'm proposing.

### Ledger

| Table | Columns | Notes |
|---|---|---|
| `sponsors` | sponsor_id PK · name · cik · tickers JSON · exchange · filer_kind (domestic \| FPI) · sic · in_universe_from · in_universe_to? | Universe = US-listed per Q-A1. FPIs file 6-K, not 8-K. |
| `programs` | program_id PK · sponsor_id FK · asset_name · aliases JSON · indication · modality · target · mechanism | Needed for "mechanism/target precedent" in packs. |
| `trials` | nct_id PK · program_id FK · phase · allocation · masking · enrollment · comparator · primary_endpoint · endpoint_type · primary_completion_date · source_id FK | Pack design fields; `endpoint_type` drives base-rate cells. |
| ★ `events` | event_id PK · event_type (readout \| fda_decision \| adcom \| discontinuation) · date_type (dated \| fuzzy) · sponsor_id FK · program_id FK · nct_id? · application_no? · application_kind? (NDA \| BLA \| sNDA \| sBLA) · indication · status (open \| resolved \| void) | Identity only. Every fact about an event is a label. |
| ★ `sources` | source_id PK · url · type (ctgov \| edgar_8k \| edgar_6k \| ir_page \| drugsfda \| fda_press \| fda_crl \| fda_adcom \| market) · is_primary · published_at · retrieved_at · sha256 · local_path | `local_path` points into gitignored `data/raw/`. |
| ★ `labels` | label_id PK · event_id FK · field · value JSON · reviewer · reviewer_kind (human \| model-adjudicated \| auto-agreement \| deterministic) · version · valid_at? · recorded_at · supersedes_label_id? · note | Append-only and bitemporal. The current value is the latest version; the as-of value is the latest with `recorded_at ≤ t`. |
| `label_sources` | label_id FK · source_id FK · passage_ref JSON (char offsets) | Gives the review tool its exact passages. Never exported. |
| ★ `promises` | promise_id PK · event_id FK · statement_date · guided_text ("mid-2027") · guided_start · guided_end · guided_precision · actual_date? · source_id FK | The slip model input. |
| ★ `extractions` | extraction_id PK · source_id FK · event_id? · field · value JSON · confidence · quote_spans JSON · quote_verified · model_version · prompt_hash · completion_key FK | One row per model per field. |
| `review_queue` | item_id PK · event_id FK · field · reason (disagreement \| low_confidence \| quote_unverified \| event_link_ambiguous \| tiebreak_abstained \| operator_flag \| outcome_confirmation \| parse_failed \| exclusion_link) · status · created_at · closed_label_id? | Queue size is reported in every refresh. |
| `exclusions` | exclusion_id PK · nct_id UNIQUE · sponsor_id FK · source_id FK · reason (withdrawn_before_enrollment \| withdrawn_citing_other_trial) · enrolled · linked_nct_id? · linked_by · taxonomy_version · recorded_at | Registry records that are not events (taxonomy v1.1 §1). Exported with reasons and links, never the registry's text. |
| `quote_checks` | check_id PK · run_id · source_id FK · model_key · role (extractor \| tiebreak) · claimed_quote · matched_span · score · method (exact \| fuzzy \| rejected) · accepted · reject_reason · threshold · matcher_version | Every quote check. Local only (source text). Feeds the drop rate and the spot-check sample. |
| `resolutions` | event_id PK/FK · label_id FK · primary_source_id FK **NOT NULL** · event_date · confirmed_recorded_at · taxonomy_version · void_reason? | The schema itself enforces S9. Binary outcome is derived from the label plus the taxonomy version. `void_reason` is set only under the narrow void rule (taxonomy §4), and voided events are exported with it. A CRL resolves from the sponsor's filing. The FDA letter, when published, is a later label version and never changes the resolution. |

### Arena

| Table | Columns | Notes |
|---|---|---|
| `rounds` | run_id PK · track · run_ts · status (planned \| approved \| running \| committed) · git_sha · config_hash · models_snapshot JSON · est_usd · actual_usd · cap_usd · approved_by · approved_at · commitment_sha256 · committed_at · commit_sha · timestamp_proof? | One per round per track. |
| `round_events` | run_id FK · event_id FK · expected_resolution · horizon_days · slip_model_version | Selection snapshot. |
| `packs` | pack_id PK · run_id FK · event_id FK · sha256 · path · max_item_date · max_item_recorded_at · built_at | S3: `max_* ≤ run_ts` is asserted at build time and again in tests. |
| `pack_items` | pack_id FK · kind (registry \| design \| endpoint \| prior_results \| guidance \| precedent \| ledger_event) · ref · item_date · recorded_at | Item-level provenance for the leakage test. |
| `forecasts` | forecast_id PK · run_id FK · event_id FK · model_key · model_version · p_success (mean of draws) · sample_sd · n_samples · horizon_days · void_reason? | The published forecast: the mean of `n_samples` = 2 draws (`arena.yaml: samples_per_model`). A draw that fails to parse is retried once under a new sample_index. If still unparsed, the forecast uses the remaining draw and records `n_samples` = 1. |
| `forecast_samples` | sample_id PK · forecast_id FK · sample_index · seed? · seed_supported · p_success · rationale · key_uncertainties JSON · raw_output · parse_status · tokens_in/cached/out/reasoning · cost_usd · completion_key FK | Every raw draw, always stored and published at reveal. `seed` is set and recorded when the provider supports it (`seed_param: set_if_supported`). |
| `baselines` | run_id FK · event_id FK · kind (base_rate \| market \| constant) · p · n_basis? · cell JSON? · source_url? · observed_at | The base rate is computed **as of run_ts**. Otherwise the baseline leaks. Market `p` is stored internally only. While `market_baseline.export_prices` is false (until the operator confirms Kalshi display rights), exports carry only per-event `beat_market` per model and aggregate comparisons, never `p`. |
| `market_links` | event_id FK · venue · contract_id · criteria_match (exact \| approximate) · confirmed_by | Contract matching is suggested automatically and confirmed in the queue (Q-C7). |
| `scores` | forecast_id FK · outcome · brier · log_loss · p_clipped · taxonomy_version · scored_at | Derived and recomputable. Never hand-edited. |

### Harness

| Table | Columns |
|---|---|
| `harness_runs` | run_id PK · benchmark · subset · model_key · model_version · seed_index · setup (official \| preprint) · run_kind (pilot \| launch \| anchor \| uncapped \| second_seed) · reasoning JSON (effort, cap_tokens, capped) · manifest_hash · n_items · stop JSON? (rule_version, checkpoint, n, half_width) · prompt_template_hash · decoding JSON · grader_ref (package@version or commit) · inspect_log · git_sha · cost_usd · started_at · finished_at |
| `harness_items` | run_id FK · item_id · seed_index · position (in the manifest order) · prompt_hash · output_ref · answer · score · tokens (incl. reasoning) · truncated · cost_usd |
| `sample_manifests` | manifest_id PK · benchmark · kind (permutation \| subsample \| anchor) · strata JSON · seed · item_ids JSON (ordered) · source_run_ids JSON? (for anchors) · sha256 (fixed and committed, so subsamples and orders never drift) |
| `anchor_validations` | manifest_id FK · benchmark · model_version · predicted · predicted_ci · reference (full-run score or published anchor) · reference_kind · abs_error |
| `expert_baselines` | benchmark · subset · value · source_citation · note |
| `published_anchors` | model_name · model_version? · benchmark · subset · value · ci? · n · setting · source_url · source_kind · rerunnable |
| `vendor_scores` | same shape as `published_anchors`. Separate table, never read by leaderboard code (S2). |

### Shared

| Table | Columns |
|---|---|
| `completions` | cache_key PK · provider · model_version · prompt_hash · params JSON · sample_index · request_ref · response_ref · tokens · cost_usd · batch_id · created_at |
| `spend_ledger` | job_id PK · run_id · job_kind · provider · model_version · n_calls · tokens · est_usd · actual_usd · cap_usd · started_at · finished_at |
| `model_snapshots` | sha256 PK · yaml · recorded_at |

---

## 3. Key flows

**`make refresh`** (daily, no manual steps) runs these stages in order:
1. Ingest, in this order:
   - Universe: the SEC tickers file joined to SIC from the submissions API.
   - EDGAR: the per-CIK submissions API is the backbone (8-K items 7.01/8.01 and 6-K, EX-99.x).
     Full-text search is used for discovery only, filtered client-side because it ignores item and
     SIC filters.
   - CT.gov v2.
   - Drugs@FDA: the daily zip plus openFDA, which confirm approvals.
   - openFDA CRL dataset: enrichment only, since it is updated infrequently. CRLs resolve from the
     sponsor's 8-K or 6-K on decision day, and the letter is attached later as a new label version.
   - FDA press RSS.
   - AdCom meetings, from the Federal Register API.
   - IR pages, as a fallback only.
2. Keyword and regex prefilter: a free filter that removes most documents before any paid call.
3. Two-model batch extraction.
4. Routing: auto-accept, tie-break, or queue.
5. Resolve: primary source required (S9), taxonomy v1 mapping and the narrow void rule, and every
   arena-scored outcome waits for the operator's one-keystroke confirmation in `ledger review`.
6. Score any newly resolved arena events.
7. Export.
8. Summary: new events, resolutions, queue size, spend.

**Extraction routing**, per statement (as built in ledger v0, `ledger/extract.py`):
- Each model returns statements, each with one supporting quote, checked against the full source
  text (`ledger/quotes.py`, operator decision Q.3 of 2026-10-30):
  - **exact** (modulo whitespace, curly quotes, dashes, case) → kept;
  - **near-verbatim** → kept: rapidfuzz partial-ratio score ≥ 0.8 against the best-aligned source
    span, **and** every identifier-like token of the quote (anything with a digit or two capitals:
    `EXT-202`, `SUMMIT`, `2027`, `2b`) occurs at that place in the source, **and** the quote and the
    span agree on negation. The two guards are part of the rule: on score alone, "met its primary
    endpoint" matches "did not meet its primary endpoint" at 0.86, and `EXT-303` matches `EXT-202`;
  - otherwise **dropped**. Quotes under 30 characters must be exact.
  - Every check, kept or dropped, is a row in `quote_checks` with the model's claimed quote, the
    nearest source span, the score, the reason and the matcher version. Each refresh summary reports
    the drop rate overall and per document (7-day window), and `ledger report` prints a random sample
    of 10 drops for the operator's spot-check. `quote_checks` never leaves the machine: claimed
    quotes and spans are source text.
- Statements are paired across models by event type, asset (any shared name or code) and trial.
- Both models agree on every compared field (kind, timing window after deterministic parsing, event
  date, phase, application kind, NCT ID, reserved fields): auto-accept
  (`auto-agreement:<m1>+<m2>`). The models' self-ratings are stored and route nothing (V.1,
  2026-11-05); a random audit of agreed outcomes checks this path (V.2, `config/audit.yaml`).
- A non-reserved field disagrees: the tie-break model must pick A or B and quote the deciding
  sentence (`model-adjudicated:<m3>`), checked by the same quote rule. "Neither", or a quote that
  fails the check, goes to the queue as `tiebreak_abstained`.
- Only one model found the statement: the tie-break decides whether it exists, unless the statement
  carries a reserved field, in which case it goes to the human queue.
- Reserved fields go to the human queue on disagreement (Q-C11, V.1). **The stop
  subtype (`result_subtype`) and the stop's data trigger (`stop_data_trigger`) are reserved too**
  (operator-confirmed 2026-10-30), because together they decide scored vs void under taxonomy v1.1.
- An accepted statement that matches more than one existing event goes to the queue as
  `event_link_ambiguous`.
- Federal Register AdCom notices are parsed without a model (`deterministic`, `parser:fedreg_adcom_v1`),
  operator-confirmed 2026-10-30.
- CT.gov records that are not events (withdrawn before enrollment, or withdrawn citing another
  trial's data) never reach a model. They become `exclusions` rows (`ledger/exclusions.py`). A
  record that cites another trial by NCT number is linked by the parser; one that cites it only in
  words goes to the queue as `exclusion_link`, and the operator picks the cited trial in
  `ledger review`.

**Agreement rules:**

| Field type | Agreement means |
|---|---|
| Categorical | exact match |
| Dated date | same day |
| Guided date | same window |
| Numbers | within 1% |

**`ledger review`** shows one item at a time: the event, both model answers, the confidence values,
and the exact source passages with links. You choose A, choose B, type a value, or skip. Your choice
is written as a new label version (`human:<you>`, timestamp, sources). When your choice reveals a new
rule, the CLI prompts for a one-line note, which is appended to `docs/taxonomy.md` under "Adjudication
log".

**`make round`** (every 14 days) runs as follows:
1. A GitHub Action opens a PR with the provisional selection and a dry-run estimate.
2. You approve. Merging the PR, or approving the `paid` environment, is the go-ahead.
3. At job start, **run_ts** is set and the registry is refreshed (fetches finish before run_ts).
4. Selection is recomputed at run_ts.
5. Packs are frozen and hashed.
6. Batch calls are made, cheap models first: **2 independent samples per model per event**
   (`sample_index` 0 and 1, seed set and recorded where the provider supports one). Outputs are
   parsed, every raw draw is stored in `forecast_samples`, and the forecast is their mean, with the
   spread recorded.
7. The commitment hash is written to git and to `exports/commitments/`.
8. As-of baselines are computed. The market baseline is exported as `beat_market` only while
   `market_baseline.export_prices` is false.

**Harness launch** (Milestone 3, each step after a dry-run and your go-ahead):
1. **Pilot:** 50 items per benchmark per flagship, 1 seed, capped reasoning, official setup. It gives
   the measured cost and confirms or rejects saturation on MMLU-Bio and PubMedQA. If they're
   saturated, they're skipped and the preprint is cited.
2. **Launch run:** LitQA2 (fixed n≈100 subsample), SeqQA and DbQA (fixed permutation, sequential
   rule), ProtocolQA, CloningScenarios, and GPQA-Bio, all in full otherwise. 6 flagships, 1 seed,
   batch. Pilot items are cache hits, so they aren't paid twice.
3. **Second seed:** the LAB-Bench headline benchmarks for the top three models only.
4. **Uncapped run:** the single top model per benchmark, with reasoning uncapped. The capped-vs-uncapped
   delta is published as a finding.
5. **Anchors:** select ~100-item anchor subsets for the large benchmarks from the launch runs, and
   validate them (§5).

**`make model-day MODEL=<id>`** runs these steps in order:
1. Dry-run.
2. Your go-ahead.
3. Anchor subsets for SeqQA and DbQA, plus LitQA2's fixed 100, ProtocolQA, CloningScenarios, and
   GPQA-Bio in full. 1 seed, capped reasoning, batch. The predicted full-set score is published with
   its interval and marked as anchor-based.
4. Add the model to the side-by-side chart and to `models.yaml` for the next arena round.
5. Draft the "Model day" issue.

**`make validate`** rebuilds the anchor table, deviations, seed variance, and per-item exports from
cached runs. It costs $0.

---

## 4. Leakage design (critical piece 1)

**Run timestamp**
- `run_ts` is the moment the approved paid job starts, not when the PR was opened.
- Selection and horizon are computed at `run_ts`, so an approval delay can never let stale selections
  through.

**Pack contents**
- Every pack item comes from a query filtered on `published_at ≤ run_ts AND recorded_at ≤ run_ts`.
- Labels are read as-of. A correction recorded after run_ts can't change a frozen pack.

**Base rate**
- The base-rate baseline uses only resolutions with `confirmed_recorded_at ≤ run_ts`.
- Computing it from today's ledger would let the baseline see the future, which is unfair to the
  models.

**Selection floor**
- An event is selected only if all three conditions hold:
  - it has no resolution;
  - its slip-adjusted expected resolution is in [run_ts + 21d, run_ts + 90d];
  - no "imminent-signal" label exists, for example a scheduled topline call or a posted late-breaker
    title inside the floor.

**Commitment**
- The hash covers canonical JSON of all forecasts plus pack hashes (sorted keys, fixed float format,
  UTF-8 NFC).
- It is SHA-256 committed to git and to `exports/commitments/<run_id>.json`.
- A git commit can be force-pushed over, so I'd also anchor the hash externally: OpenTimestamps is
  free, Sigstore Rekor is the alternative (Q-C3).
- If an event's resolution `valid_at` is at or before `committed_at`, that forecast is void and the
  void is reported.
- **Labels too** (COI policy, `docs/methods.md` §2): every refresh hashes its label export, and the
  hash is committed and timestamped the same way. Any label can then be shown to have been public
  before its event resolved (Q-G7).

**Tests**
- A fixture timeline seeded with traps: a source dated run_ts+1s, a label corrected after run_ts, an
  event at day 20, an already-resolved event, and a base-rate input confirmed after run_ts. The pack
  builder, selector, and base rate must exclude every one.
- A property-based test generates random timelines and checks the same invariants.

---

## 5. Scoring spec (critical piece 2)

**Outcomes and probabilities**
- Outcome mapping comes from the taxonomy version (`docs/taxonomy.md`, v1). Void events are excluded
  and counted, never silently dropped, and each is exported with its `void_reason`.
- The scored p is the forecast's mean over its draws (2 by default). Each draw's own Brier score and
  the draw spread (`sample_sd`) are reported as a stability check, never as the headline.
- Brier is computed on the raw p.
- Log loss is computed on p clipped to [ε, 1−ε], with ε = 0.001 proposed (Q-C10). The number of
  clipped forecasts is reported.

**Which forecasts count**
- **Headline:** per (model_version, event), the latest committed, non-void forecast.
- **Horizon view:** every forecast, bucketed 21–45 and 46–90 by the expected horizon at forecast time
  (Q-C8).

**Intervals and comparisons**
- 95% intervals come from a bootstrap that resamples **events**, with B = 10,000 and the seed
  recorded. Program-level clustering is a sensitivity check.
- Model-vs-baseline differences use a paired bootstrap on the same resamples (Brier skill score).

**Calibration**
- Ten equal-width bins, or five when n < 100, with Wilson intervals per bin.

**Power rule (S5)**
- The unit is model_version. Until a model_version has n ≥ 100 headline resolved forecasts, only the
  aggregate view and calibration are published. See Q-C6 on keeping retired versions in the arena so
  they can reach n.

**Windows and splits**
- Windows are by resolution date: current round, trailing 3 months, trailing 6 months, and all-time.
- Splits: dated, fuzzy, combined, and per event type.
- Every number ships with n and its interval.

**Harness: setup and samples**
- Every headline number uses the official setup (for LAB-Bench, FutureHouse's prompt, parser, and
  scorer). Older anchor models are also run in the preprint's setup, and the measured gap goes in the
  deviations list.
- Per-item scores come from the official grader. **One seed** per item, with the 95% interval from
  an item-level bootstrap (B = 10,000, seed recorded). The LAB-Bench headline for the top three models
  gets a second seed: the headline is then the mean over both, the bootstrap keeps an item's seeds
  together, and the seed-to-seed difference is reported.
- **Reasoning** is capped at the documented low/medium tier in `models.yaml` for every item, and the
  setting (effort, cap tokens) is recorded per run and per completion (`test_reasoning_cap_recorded`).
  A truncated output is graded as the grader grades it, and the truncation count is reported. The
  single top model per benchmark is also run uncapped, and the paired per-item difference, with its
  bootstrap interval, is published as "what reasoning buys in biology".

**Harness: normalized score and saturation**
- Normalized score = (acc − expert)/(1 − expert), with the expert baseline treated as fixed. It is
  computed only for LitQA2, CloningScenarios, ProtocolQA, and GPQA-Bio. **SeqQA and DbQA report raw
  accuracy only. MMLU-Bio has no expert line at all**, because the commonly quoted 89.8% is MMLU's
  all-subject figure.
- The saturation flag is set when the top model's upper CI reaches the benchmark's ceiling (Q-D6).
  MMLU-Bio and PubMedQA run only as the 50-item pilot. If saturation is confirmed, they're reported
  as "saturated, see preprint" with no new leaderboard numbers.

**Harness: subsets, sequential rule, anchors**
- **LitQA2:** one fixed, stratified random subsample of n≈100, recorded in `sample_manifests`.
- **Sequential evaluation rule** (`test_sequential_stopping_rule`):
  - It applies only to benchmarks with more than 200 items: SeqQA (600) and DbQA (520).
  - One fixed random permutation per benchmark, seeded and recorded in `sample_manifests`. It is
    identical for every model, so any two models share a common prefix for paired comparisons.
  - Minimum 150 items. Checkpoints every 50 items after that, plus the last item, all declared before
    the run.
  - Stop at the first checkpoint where the 95% interval's half-width is ≤ 0.05. The interval is
    Wilson at level 1 − 0.05/K, where K is the number of pre-declared checkpoints (Bonferroni). That
    makes it valid at whichever checkpoint the run stops, so optional stopping doesn't break coverage.
  - Report n, the stop checkpoint, and the half-width. The rule version is stored in
    `harness_runs.stop`.
  - Batch mechanics: items are submitted in checkpoint-sized batches, in manifest order. The next
    batch is submitted only if the rule hasn't stopped.
  - At accuracy near 0.5 the rule needs about all the items. Savings come only at high or low accuracy
    (at 0.9, about 300 items). The half-width target is the operator's lever (Q-G4).
- **Anchor subsets** (for model-days):
  - Built from the launch runs: ~100 items per benchmark with more than 150 items (SeqQA, DbQA).
    Smaller benchmarks run in full on model-days.
  - Selection follows tinyBenchmarks where a large enough response matrix exists. Otherwise it uses
    stratified sampling by subtask and by launch-run difficulty (Q-G3).
  - Validation: the anchor-predicted score is compared with each launch model's full-run score
    (leave-one-model-out) and with published anchors. Results go in `anchor_validations`. Anchors are
    used only if every model's prediction falls inside its interval. Otherwise model-days fall back to
    full runs.
  - Anchor-based scores carry their own, wider interval and are marked as anchor-based in exports.

**Harness: per-item release and vendor benchmarks**
- Per-item exports carry item ID, model output, and grade. **Never question text**
  (`test_exports_no_item_text`). `scripts/fetch_items.py` rejoins items from their original source.
- LAB-Bench-derived per-item files are released under **CC BY-SA 4.0**.
- GPQA per-item files carry only a **hashed item ID and correct/incorrect**, with no model outputs
  (`test_gpqa_release_hashed_only`).
- LifeSciBench, MedChemBench, and GeneBench go only in `vendor_scores` (S2) until an independent,
  reproducible setup exists.

---

## 6. Automation and state

The daily job needs persistent state: the SQLite DB, the raw-document cache, and the completion
cache. Raw documents can't go anywhere public. Options (Q-F2):

| Option | State | Cost | Notes |
|---|---|---|---|
| **A. Self-hosted GitHub runner** on your Mac or a small VPS | local disk | $0–6/mo | Simplest. A Mac must be awake at job time. |
| B. GitHub-hosted runners + private object store (Cloudflare R2 / Backblaze B2) | bucket | ~$0–2/mo | No machine to keep up. Needs bucket keys and a sync step. |
| C. Local cron only, no Actions | local disk | $0 | Loses the "PR before paid calls" UX unless it uses the `gh` CLI. |

My recommendation is B, or A on a VPS. Either way, the arena workflow uses a GitHub **environment
with you as the required reviewer**, so the paid job physically can't start without your click. That
click is the go-ahead.

Release cadence: a rolling `latest` release asset and Hugging Face push on every refresh, plus a
tagged monthly release, which creates the Zenodo DOI through Zenodo's GitHub integration (Q-F5).

---

## 7. Tests (minimum set)

| Area | Tests |
|---|---|
| Scoring | Brier, log loss, calibration bins, bootstrap against hand-computed values; headline selection; horizon bucketing; void handling; mean-of-draws forecast and `n_samples` = 1 fallback |
| Leakage | pack leakage (trap fixture + property test); 21-day floor; commitment precedes resolution; as-of base rate |
| Ledger | every resolved event has a primary source; label provenance; queue routing (reserved fields never tie-broken); quote verification; `test_void_rule` (taxonomy v1 mapping and void cases, table-driven from `docs/taxonomy.md` §3–4) |
| Harness | grader regression on published example items; manifest stability; no-biosecurity denylist; uniform settings across vendors; `test_sequential_stopping_rule` (checkpoints, Bonferroni-Wilson half-width, same permutation for every model, coverage by simulation); `test_reasoning_cap_recorded` |
| Publish | schema validation of every export; no raw text in exports (n-gram check against the raw cache); vendor isolation; power-rule gating; `test_market_prices_not_exported`; `test_exports_no_item_text`; `test_gpqa_release_hashed_only`; voided events exported with `void_reason` |
| Budget | spend guard refuses over-cap estimates and halts at cap; cache key includes sample_index; dry-run is the default |
| Smoke | `make refresh` on the fixture DB end-to-end, offline |

---

## 8. Milestone plan (each milestone is one or more PRs with write-up, sample outputs, spend)

| # | Milestone | Contents | Paid step (after dry-run and your go-ahead) |
|---|---|---|---|
| **0** | Planning | CLAUDE.md, design, taxonomy v1, decisions, methods draft, cost estimates, credit email, questions | none |
| **1a** | Foundation | uv project, ruff, pytest, CI; full schema + migrations; config loaders; spend guard + dry-run framework; completion cache; batch clients; S-tests scaffolding | none |
| **1b** | Ledger ingest | universe builder, EDGAR, CT.gov, Drugs@FDA, CRL, FDA press, AdCom, IR fallback; prefilter; slip tracking | none (free APIs) |
| **1c** | Ledger v0 | extraction + routing + quote verification; `ledger review`; resolution; **next 90 days of catalysts + last 90 days resolved** (plus optional 2025 backfill, Q-A6); queue size | pilot 50 docs → bootstrap extraction |
| **2** | Arena round 1 | selection, packs, leakage tests, prompt, batch run across the 6 flagships × 2 samples, commitment (+ external timestamp), baselines (market exported as beat/did-not only), scoring code tested **before** any resolution, forecasts/commitments exports (schema v0), biweekly Action | round 1 |
| **3a** | Harness pilot | tasks on official graders (official LAB-Bench setup), regression tests, fixed manifests and permutations, sequential rule, reasoning tiers, expert baselines, published anchors entered; pilot 50 items × benchmark × flagship, 1 seed, capped → **measured** cost and the MMLU-Bio/PubMedQA saturation check | pilot (after your go-ahead) |
| **3b** | Harness launch | LitQA2 n≈100, SeqQA/DbQA (sequential rule), ProtocolQA, CloningScenarios, GPQA-Bio × 6 flagships × 1 seed; second seed on LAB-Bench for the top 3; uncapped run on the top model per benchmark; anchor-subset selection and validation; normalized scores where a baseline exists | launch runs (credit email sent first) |
| **3c** | Validation | anchor table (incl. preprint-setup re-runs of older models, both setups), deviations with measured effects, seed-to-seed difference, anchor validation, per-item release under the license rules, contamination statement, reviewer packet | anchor re-runs |
| **4** | Publish | schema v1 freeze, all exports, charts + PNGs, HF dataset, GitHub release + Zenodo DOI, issue generators, launch issue draft, social card, daily refresh Action | none |
| **5** | Later | BixBench (agentic, sandboxed), mid-tier models on their own model-days (Opus 5.5 first), scoreboard base rates once ≥ 200 resolved events, Track 2 | as approved |

Arena rounds keep running every 14 days from Milestone 2 onward, alongside harness work. The clock
is what matters there. At a likely 100–250 unique resolved events per year, per-model rankings
(n ≥ 100) are roughly 6–12 months out, so round 1 should go as early as possible.
