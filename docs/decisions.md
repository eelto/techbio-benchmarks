# Decisions

Each entry: date, decision, rationale where given, who decided, and the `Q-xx` items it closes in
`docs/questions.md`. Entries are append-only. A later decision that changes an earlier one adds a
new entry and points back.

---

## 2026-10-30 · Step 1 review (operator)

### A. Responses to the Step 1 findings

| # | Decision | Closes |
|---|---|---|
| A.1 | Flagships can't run at temperature 0. **Arena forecast = mean of 2 samples** (not 3). The spread is published and all raw draws are stored. If a provider supports a seed parameter, set it and record it anyway. | C9 |
| A.2 | **Official LAB-Bench setup for all headline numbers.** The older anchor models are run both ways (official and preprint setup), and the measured gap goes in the validation report's deviations list. | D1, D3, D15 |
| A.3 | **SeqQA and DbQA report raw accuracy only**, with no normalized score. **The MMLU-Bio "expert" line is dropped entirely** rather than use a general-MMLU figure. The methods page explains why. | D7 |
| A.4 | **Per-item exports contain item IDs, model outputs, and grades, never question text.** A script fetches items from their source. LAB-Bench-derived files are released **CC BY-SA 4.0** to match its license. **GPQA per-item release is correct/incorrect by hashed item ID only, with no outputs**, per the authors' request. Both are noted on the data page. | D9 |
| A.5 | LifeSciBench, MedChemBench, GeneBench: **vendor table only** until an independent, reproducible setup exists. | D12 |
| A.6 | **CRLs resolve from the sponsor's 8-K on decision day.** The openFDA letter is attached later as a versioned update. AdCom meetings come from the Federal Register API. | (data-source facts) |

### B. Decisions only the operator can make

| # | Decision | Closes |
|---|---|---|
| B.1 | **Anthropic flagship: Fable 5.1.** Opus 5.5 enters later as the mid-tier entry for the cost-per-point chart. | D13 |
| B.2 | **Kalshi:** the operator reads the terms. Until display rights are confirmed, the market baseline is computed internally, and exports carry only per-event "beat market / did not" and aggregate comparisons, **never prices**. Controlled by a config flag (`config/arena.yaml: market_baseline.export_prices: false`). Polymarket stays out. | C7 |
| B.3 | **Conflict-of-interest policy**, wording fixed by the operator (verbatim in `docs/methods.md` §2). | E1 |
| B.4 | **Scope A1–A7 and taxonomy B1–B7: recommended defaults accepted**, with one override: **the void rule is narrow and public.** An event is voided only if it is cancelled or the trial is stopped for reasons unrelated to its outcome (financing, strategic, acquisition). Anything resolved by data is scored. Voided events are listed in the exports with reasons. Taxonomy becomes v1 (`docs/taxonomy.md`). | A1–A7, B1–B7 (B3, B4 as amended) |

### C. Cost efficiency (these are the defaults)

| # | Decision | Closes |
|---|---|---|
| C.1 | **Reasoning budgets are capped at a documented low/medium level** for all benchmark items. Uncapped runs only on the single top model per benchmark, and the delta is published as a finding ("what reasoning buys in biology"). | M5, C12 (level itself: see questions) |
| C.2 | **One seed**, with item-level bootstrap intervals everywhere. A second seed only for the LAB-Bench headline run on the top three models. | D11 |
| C.3 | **Saturated benchmarks (MMLU-Bio, PubMedQA):** confirm saturation with the 50-item pilot, then skip them and cite the preprint. Do not subsample. | D5 |
| C.4 | **LitQA2 subsampled to n≈100** with intervals. SeqQA, DbQA, CloningScenarios, ProtocolQA run in full. | — |
| C.5 | **Batch APIs for every job.** Prompt caching on shared instructions and on paper context shared across LitQA items. | — (see questions: LitQA2 has no paper context in the official setup) |
| C.6 | **Sequential evaluation:** items in random order, stop a model on a benchmark when the interval is narrow enough. The rule is documented and tested. | — (spec in `docs/design.md` §5) |
| C.7 | **Anchor subsets:** from one full reference run per benchmark, select ~100 representative items (tinyBenchmarks-style). Validate predicted full-set scores against the reference run and against published anchors. Model-days use anchors; full runs only at launch. | — |
| C.8 | **Arena: 2 samples, 6 models.** Launch roster: five flagships (OpenAI, Anthropic, Google, xAI, Meta) plus the leading open-weight model. Mid-tier models are added on their own model-days. | C5 |
| C.9 | `docs/cost-estimates.md` shows the new mid-scenario year-one total and the per-model-day cost. | — |
| C.10 | Keep the credit-request email ready. The operator sends it before the full launch run. | E3 (timing) |

### D. Blockers

| # | Decision | Closes |
|---|---|---|
| D.1 | **API keys:** project-scoped keys with spend limits set in each provider console, placed in `.env` by the operator. **Console limits are the backstop; the per-run cap is the first line.** | K1–K3 (once present) |
| D.2 | **SEC User-Agent:** operator's name and email, in `.env`. | K7 (once present) |
| D.3 | **Repo:** `techbio-benchmarks` under the operator's GitHub org. This session moves there. | K11, F1 (org name and local folder still to confirm) |
| D.4 | **Standing approval: $3/day for ingestion and resolution.** | M3 (daily part) |
| D.5 | **Install uv and gh.** Done 2026-10-30: uv 0.13.6 and gh 2.103.3 (checksum-verified) in `~/.local/bin`. | F8 |

### E. Next

| # | Decision |
|---|---|
| E.1 | Proceed to ledger v0: next 90 days of catalysts plus the last 90 days resolved, `date_type` and slip tracking, review tool working, queue size reported. PR with write-up, sample rows, and spend. Flag anything in the taxonomy that the first real events don't fit. |
| E.2 | **No paid calls beyond the standing ingestion approval until the operator says go on the pilot.** One-off ledger jobs above $3/day (the bootstrap) still need a dry-run and an explicit go-ahead. |

---

## 2026-10-30 · Ledger v0 review, second round (operator)

IDs in this entry are prefixed by topic (T taxonomy, Q code choices, O open questions, N next) so
they don't collide with the first entry's A–E.

### T. Taxonomy (v1 → v1.1, `docs/taxonomy.md`)

| # | Decision | Closes |
|---|---|---|
| T.1 | **Strategic/business stop after enrollment: void for endpoint scoring unless a data trigger is documented** (interim analysis, futility analysis, DSMB recommendation), **in which case it is scored as "missed"**. Either way, it is recorded with the enrolled-patient count under a new explanation category, **`strategic_stop_after_enrollment`**, so it can be reported as a pattern. Rationale (operator): a "strategic" stop after hundreds of patients is often a data decision presented as a business one, and surfacing that is the point of the ledger. Example: NCT04396236 (Lilly, 847 enrolled). | G5 (2) |
| T.2 | **Withdrawn before enrollment: not an event; excluded.** Example: NCT05951205. | ledger v0 flag |
| T.3 | **Withdrawn citing another trial's data: not an event; excluded and linked to that trial's event.** Example: NCT06598631. | ledger v0 flag |
| T.4 | **Stopped for failure to enroll: void, "operational". Confirmed.** Example: NCT05074420. | G5 (1) |
| T.5 | All four go in `docs/taxonomy.md` with these examples. | — |

### Q. Code choices

| # | Decision |
|---|---|
| Q.1 | Stop subtype reserved for human review: **keep**. |
| Q.2 | Fixed (non-model) AdCom parser: **keep**. |
| Q.3 | **Verbatim-quote rule changed.** Fuzzy matching (threshold about 0.8) accepts near-verbatim quotes. Statements below the threshold are dropped but logged with the model's claimed quote and the nearest source span. The drop rate per document is reported, and a random sample of 10 drops is surfaced in each refresh summary for the operator's spot-check. Rationale (operator): "Paraphrase is the signal, not noise." |

### O. Open questions

| # | Decision | Closes |
|---|---|---|
| O.1 | **LitQA2: official setup, no paper text.** Caching on shared instructions only. | G1 |
| O.2 | **Gemini and Meta are not batchable: accept the premium.** Keep the harness uniform. The deviations list notes that batch mode does not change outputs. | G2 |
| O.3 | **Caps: monthly operating $150; arena $60 per round; harness pilot $100.** | M2; M4 (arena, pilot) |

### N. Next, in order

| # | Step |
|---|---|
| N.1 | `git init` and commit in the current folder now, before moving. **Done 2026-10-30:** root commit on `main`, work on `milestone/ledger-v0`. |
| N.2 | After the operator confirms `.env` and `gh auth`: move to the repo, push, open the ledger v0 PR. |
| N.3 | Run the free EDGAR + ClinicalTrials.gov ingestion (1–2 hours). |
| N.4 | Run the 50-document extraction pilot (about $0.40) and report the agreement rate per field and the queue size it implies. |
| N.5 | Bootstrap dry-run; stop and ask for the go-ahead with the real number. |

### How these were implemented (for review)

- **T.1:** the data trigger is a new reserved field, `stop_data_trigger`, extracted alongside the stop
  subtype and never tie-broken. The category is derived by the ledger (`taxonomy.explanation_category`),
  not offered to the extractors; the sponsor's stated reason is kept in `stated_explanation_category`.
  The enrolled count comes from the CT.gov record (actual enrollment). Resolutions store `scored_as`.
  Taxonomy version → v1.1.
- **T.2, T.3:** a new `exclusions` table filled at CT.gov ingestion, so these records never reach a
  model. NCT numbers in the stop reason are linked automatically; descriptions in words go to the queue
  as `exclusion_link`. An open event for an excluded trial is closed as `excluded`.
- **Q.3:** threshold 0.8 on rapidfuzz's partial ratio, plus two guards that are part of the rule:
  identifiers (codes, trial names, numbers, dates) must match, and negation must agree. Without them,
  "met its primary endpoint" matches "did not meet its primary endpoint" at 0.86. Every check is logged
  in `quote_checks` (local only).
