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

---

## 2026-10-31 · Ledger tie-breaker (operator)

### P. Tie-break model

| # | Decision | Closes |
|---|---|---|
| P.1 | **The ledger tie-breaker is Ornith 1.5 122B, run locally,** replacing Gemini 4 Argon. It is an open-weight model (NVFP4) on the operator's Mac Studio, served by Ollama. Rationale: Argon tie-breaks were $69.70 of the $75.28 bootstrap estimate. Locally they cost $0, and excerpts never leave the machine. | — |
| P.2 | **The extraction pilot checks it against Argon.** Argon answers the same disputes. Its choices are reported, never applied. If they disagree too often, the bootstrap stays on Argon. | — |

P.1 was superseded by P.3 on 2026-11-02.

### Measured before deciding (2026-10-31, local, $0)

- **Thinking off:** "neither" or no answer on all three synthetic tie-breaks, and zero events found in
  two real documents.
- **Thinking on:** 3/3 synthetic tie-breaks correct, each with a verbatim quote, in 3–11 s.
- **Speed:** reads about 2,000 tokens/s and writes about 80. Thinking length varies widely. As an
  extractor on six real pilot documents it wrote 1,100–26,700 tokens (14 s to 6 min, about 2 min on
  average).
- **Not an extractor:** at that speed the 5,353 documents would take about 8 days, to save at most
  $2.94.

### How this was implemented (for review)

- **Provider:** `core/llm/providers.py: OllamaSync`, over Ollama's HTTP API.
  - `model_version` pins the manifest digest Ollama reports. The provider refuses to run if the server
    has other weights under the tag, or the tag is missing.
  - The digest is part of the version string, so it is also part of the cache key and of every
    `model-adjudicated:` reviewer string.
- **Settings:** thinking on, a fixed seed (in the cache key), and no other sampling parameters.
  - Output is capped at 8,000 tokens. An answer that hits the cap is an error: never accepted, never
    cached, and the item goes to the queue as `tiebreak_abstained`.
- **Preflight:** the job checks the tie-break server before any extractor spends. A server that is down
  fails the job with nothing spent and no document marked done.
- **Comparison:** `ledger extract --compare-tiebreak` runs Argon after the local model, on the same
  prompts. The summary carries choices only (no quotes or document text).
  - The pilot's ~10 Argon calls run synchronously: a one-off, not worth a batch adapter.
- **Estimates:** the tie-break count is now rounded up. The dry-run gives the local tie-break time
  (about 9 h for the bootstrap, from the measured 80 tokens/s and 2,500 expected tokens per call).

---

## 2026-11-01 · Partner attribution (operator)

### R. Whose event it is

| # | Decision | Closes |
|---|---|---|
| R.1 | **One trial is one event, filed under the company that runs it.** Readouts go to the trial's lead sponsor on ClinicalTrials.gov, FDA decisions and AdComs to the holder of the US application, and discontinuations to the company that owns the program. A partner's or licensee's statement about someone else's trial is never recorded under the partner. If the company that runs the trial is not in the universe, the event is out of scope. Operator's answer: "Partner rule - A". | Run 3 tie-break review, case 3 (Zai Lab on argenx's ALKIVIA) |

**Rationale:**
- **No double counting.** The same readout filed under both partners would count twice in the base
  rates and in the arena.
- **Promises belong to whoever sets the timeline.** Slip tracking asks whether a company keeps its
  own guidance, and a licensee does not control its licensor's trial.
- **Mechanical.** The lead sponsor and the application holder come from primary sources, so the rule
  adds nothing to the review queue.
- **Accepted cost:** a US-listed licensee of a drug whose trial is run by an unlisted licensor loses
  that readout. Counting how often this happens needs the extractors to report partner mentions
  separately, which is proposed with the next extraction-prompt revision.

### How it is implemented

- `docs/taxonomy.md` §1 ("Attribution") and an adjudication-log entry.
- The extraction instructions already ask only for "this sponsor's own programs". Explicit partner
  wording goes into the next revision of the extraction prompt, before the bootstrap, together with
  the trial-start and boilerplate fixes. That revision changes the prompt hash, so the pilot
  extractors re-run, with an estimate first.
- The scoring version stays v1.1: the rule decides which company an event is filed under, not how any
  outcome is scored.

| # | Decision | Closes |
|---|---|---|
| R.2 | **Single-arm and dose-comparison Phase 2s stay out, even when registration-intended.** The Phase 2 rule (randomized and controlled) is kept as written. "Controlled" means a comparator arm, and randomizing between doses of one drug is not one. Operator's answer: "Probably keep the rule if this is outside scope - right- does that mean neither?", then "Fix the gap first". | Run 3 tie-break review, case 4 (Zentalis's DENALI): verdict N, not counted for either tie-breaker |

**Rationale:**
- **"Met" needs a bar.** A single-arm trial is judged against a success threshold that sponsors
  rarely publish, so most of these readouts would end in the human queue.
- **The catalyst is not lost.** If such a trial leads to an accelerated-approval filing, the FDA
  decision is still an event.
- **Accepted cost:** single-arm oncology readouts, a common catalyst class, are not in the ledger.

### The gap the case found, and the fix (2026-11-01, $0)

Nothing enforced the Phase 2 rule after extraction. Both cheap extractors reported DENALI, and the
pilot ledger held two out-of-scope Agios events: tebapivat in LR-MDS (not randomized) and in sickle
cell disease (59 patients). The fix is in `ledger/scope.py` and the extraction routing:

- **Registry facts that fail the rule drop the statement** before any tie-break or operator time is
  spent. Those facts are Phase 1/2, no randomization, or fewer than 100 patients and not called 2b.
  Each drop is recorded as a closed `scope_check` queue item (`closed_by = auto:registry`) with the
  registry facts that decided it.
- **An unconfirmed control goes to the operator** (`scope_check`; keep records the event as "2b").
  So does a plain "Phase 2" with no registry record.
- **Arm types alone cannot decide control.** I fetched CT.gov arm types (free) for the 565
  randomized Phase 2s the registry counts in scope. 73 have no comparator arm type, but at least 10
  of those clearly have one, labelled "experimental" (for example, MORAb-202 versus investigator's
  choice chemotherapy). So the registry only ever confirms a control. Intervention names (placebo,
  sham, observation, standard of care) and comparisons in the title confirm 451 of the 565.
- **Subsidiary lead sponsors** ("X, a wholly owned subsidiary of Y") now match Y. 40 trials in the
  cached CT.gov pages were being dropped, DENALI and ASPENOVA among them. They join the registry at
  the next CT.gov refresh.
- **Each candidate is checked against its own trial.** One extractor's wrong NCT number cannot sink
  the other's reading.
- Migration `0003` adds `scope_check` to `review_queue.reason`.
- The extraction prompt gets a DENALI-type example in its next revision, before the bootstrap.

---

## 2026-11-02 · Ledger tie-breaker, after the pilot review (operator)

| # | Decision | Closes |
|---|---|---|
| P.3 | **The ledger tie-breaker is Gemini 4 Argon. Ornith becomes the free pilot reference.** This is P.2's fallback. Operator's answer: "Yes, switch to Gemini". | Run 3 tie-break review |

**The review:** pilot run 3 had 7 tie-breaks where Ornith and Argon disagreed (9 fields, 5
documents). The operator ruled cases 1–4 and approved Claude's verdict on case 5. Then the operator
asked Claude to decide the rest ("ok i think this approach is not quite working for me. i dont like
being the tie breaker. can you be the decider?"), and Claude (Opus 5.5) decided cases 6 and 7.

| Case | Document | Right | Why |
|---|---|---|---|
| 1 | CervoMed, neflamapimod | Argon | A planned Phase 3 start, not a readout |
| 2 | Evommune, EVO301 | Argon | A planned Phase 2b start, not a readout |
| 3 | Zai Lab, efgartigimod | Ornith | Partner's trial, filed under argenx (R.1) |
| 4 | Zentalis, DENALI | not counted | Out of scope under R.2; neither could reject it |
| 5 | Agios, mismatched tebapivat pair | Ornith | "Neither": two trials paired by our matching bug |
| 6 | Agios, tebapivat in LR-MDS | Argon | Open-label, no control: fails the Phase 2 rule |
| 7 | Agios, tebapivat in sickle cell | Argon | Plain Phase 2, not called 2b, 59 patients |

**Rationale:**
- **Argon 4, Ornith 2.** Argon's four wins are all one failure: Ornith keeping, or hedging on, a
  statement that should not be in the ledger. A false event is the costlier mistake in a public
  ledger.
- **Ornith's two wins do not carry forward.** Case 3 is now a written rule (R.1). Case 5 came from
  our matching bug, and the scope check now drops that pair before any tie-break.
- **Reliability.** Ornith hit its output cap on DENALI in all four runs, and each failure goes to
  the operator's queue.
- **Caveat:** six counted cases is thin evidence.
- **Not chosen on cost or credits (S10).** Argon costs money and Ornith is free.

**Cost and how it is run:**
- With Argon, the bootstrap tie-breaks are estimated at about $79 ($30–$138) at the configured
  December price, plus $2.65 for the extractors. That is above the $75 cap. Google bills about half
  that price before 2026-12-01.
- The scope check and the next prompt revision cut the disputes that reach a tie-break. The cost is
  re-measured on the pilot after that revision and settled in the bootstrap go-ahead.
- Argon runs synchronously until our Google client has a batch path (Q-G2). A batch path would
  roughly halve the cost and is planned before the bootstrap.
- `config/models.yaml` keeps the settings Argon had as the pilot reference, so its run 3 answers are
  cached and re-applying them costs nothing.

### The R.1 gap the replay found, and the fix (2026-11-02, $0)

A $0 replay of the pilot with Argon choosing filed Zai Lab's mention of argenx's ALKIVIA as a Zai
Lab event. Nothing in the code enforced R.1; Ornith had happened to drop it. The operator approved
fixing it before applying P.3 ("Yes, fix it first"). The fix applies R.1 and changes no rule; the
details below are Claude's.

- **The registry decides.** A readout whose trial (by NCT number, else by acronym) is led by
  another company in the universe is dropped before any tie-break. The drop is a closed
  `scope_check` item on `sponsor_id`, with the registry facts and the lead sponsor's name.
- **The trial must test the statement's asset** (its interventions or title name it). 46 acronyms
  belong to more than one sponsor. In the replay, Roivant's brepocitinib VALOR shares its acronym
  with Pfizer's Lyme vaccine trial, and the asset test keeps Roivant's event. A wrong NCT number is
  held to the same test. Titles count because ALKIVIA lists efgartigimod only as "EFG PH20 SC".
- **The sponsor's own trial of that acronym comes first.** With no registry record the extractors'
  reading stands.
- **Replay** (scratch copy, cached answers, 0 paid calls): the ALKIVIA event is the only change. 20
  events and 20 open queue items.
- **Not covered:** a partner's mention of a trial whose lead sponsor is outside the universe, or not
  in the registry yet (the subsidiary-led trials before the next CT.gov refresh). The next
  extraction-prompt revision states R.1 to the extractors as well.
