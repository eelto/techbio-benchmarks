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

---

## 2026-11-03 · Before the pilot re-measure (Claude)

Claude (Opus 5.5) decided these within existing rules, under the operator's standing instruction
("i dont like being the tie breaker. can you be the decider?", 2026-11-02). None changes a rule, the
taxonomy or a cap. All of it was built and tested at $0, and nothing has been re-measured yet.

| # | Decision | Closes |
|---|---|---|
| C.1 | **Extraction prompt v2** (`ledger/prompts/extract_v2.md`). It states the existing rules to the extractors, with the cases the pilot got wrong. v1 stays in the tree for reproducing earlier runs. | Operator's prompt-revision list (2026-11-02); R.1 and R.2 "next prompt revision" |
| C.2 | **Pairing compares disease, takes the best match, and collapses repeats.** | Run 3 review, case 5 (Agios tebapivat) |
| C.3 | **The tie-breaker runs on Google's batch API**, at half the interactive price. | Q-G2 for the ledger tie-break |
| C.4 | **The CT.gov sweep matches wholly owned subsidiaries under any name, and never assigns a trial to two companies.** Taxonomy §1 already counts a wholly owned subsidiary as its parent; the matcher only recognized the "subsidiary of" wording. | Operator's refresh item (2026-11-03) |

### C.1 What prompt v2 says, and why

From the operator's list:
- **A planned trial start is not a readout** (CervoMed's neflamapimod Phase 3, Evommune's EVO301).
- **Ignore the "About <company>" paragraph.** Sections about a product, disease or trial are kept.
- **R.1 in the extractors' words.** A partner's, licensor's or licensee's trial or application is not
  this sponsor's event, even when the sponsor holds regional rights or gives the timing.
- **R.2 with a DENALI-type example.** Randomizing between two doses of one drug is not a control.
- **The sponsor's "2b" label does not decide it.** A single-arm, non-randomized or dose-only trial is
  out even when called 2b, pivotal or registration-intended. Where the document does not describe the
  design, the extractors report the stated phase and the registry check decides.

Added by Claude from the 50 cached pilot answers. Each fixes a case the pilot got wrong, and four of
them are in the ledger today:
- **Enrollment completion, first dosing and interim timing are not readout guidance.** vTv's
  "enrollment completion expected 3Q 2026" for CATT1 is a promise in the ledger today: both
  extractors read it as readout timing, so it was auto-accepted.
- **Extension studies are out even when called Phase 3.** Sanofi's ESTUARY is an event in the ledger
  today (tie-broken).
- **FDA decisions belong to the US application holder.** Zai Lab's PDUFA date for povetacicept is
  Vertex's application, and it is a Zai Lab event in the ledger today. The registry check covers
  readouts only, so it did not catch this.
- **A separately listed subsidiary is another company.** Roivant's release gives the timing of
  Immunovant's batoclimab readouts, and that is a Roivant event in the ledger today. Immunovant is in
  the universe and is the trial's lead sponsor, so under R.1 the event is Immunovant's. A subsidiary
  without its own listing still counts as the sponsor (Priovant, for Roivant's brepocitinib).
- **Phase 1 trials are never reported with the phase left empty** (Agios's AG-236 and AG-181, three
  Zai Lab Phase 1 programs). The tie-breaker rejected them, at a cost.
- **A stopped trial is a "stopped" readout, not a discontinuation,** unless the sponsor ends the
  program. One extractor filed Immutep's TACTI-004 futility stop only as a discontinuation, which
  would leave the readout open.
- **A planned filing is not an FDA decision,** and **timing must be a time expression** (one
  extractor gave "runway well past the CATT1 topline data readout" as timing).
- **One statement per event, including tables and summary lists** (Vor Bio, one readout three times).
- **Partner mentions go in a separate list** (`partner_mentions`: asset, event type, trial, the
  company named as running it, and a quote). They never become statements, are never tie-broken and
  never reach the queue. Each run counts the quote-verified ones per extractor, split by whether the
  named company is in the universe. "Outside the universe" measures R.1's accepted cost, the
  readouts a US-listed licensee loses. Matching is by name, so a short form such as "Lilly" counts as
  outside. They are stored in `extractions` (`field = partner_mention`).
- **The tie-breaker's "exists" question** now says that B (do not report) also covers a statement the
  rules put out of scope, not only one the document does not support.

**Known cost:** Immunic's only statement of its vidofludimus readout timing in the pilot release is in
its "About Immunic" paragraph, so v2 drops that restatement (1 of 50 documents). Immunic's other
releases carry the same guidance in the body.

**Cost:** the system prompt grows from about 1,300 to about 2,400 tokens. It is a cached prefix for
the extractors. The tie-breaker's share is re-measured on the pilot.

### C.2 Pairing (`extract.pair`, `extract.collapse_duplicates`)

- **Two clearly different diseases are never paired,** even under one NCT number. "Clearly" is the
  test the ledger already uses (`names.indications_conflict`): no disease word in common, and
  neither abbreviates the other. A vague or missing indication never splits a pair.
- **The best match wins, not the first.** Candidates are scored on a shared NCT number, then trial
  name, then disease, then kind and window.
- **One model's repeats of one event collapse into one,** with gaps filled from the repeats. Repeats
  that differ in any compared field stay apart, so the disagreement still reaches routing (Roivant's
  two batoclimab timings).
- **Tests first:** `tests/test_pairing.py` (7 tests; 5 failed before the fix).
- **Effect on the pilot** (cached v1 answers, scratch copy, 0 calls): 25 → 21 statements need a
  tie-break before the scope check (Vor Bio 4 → 1, Agios 5 → 4). The final ledger is identical to
  run 6.
- **Residual:** an extractor's wrong NCT number can still drop that extractor's own lone statement in
  the registry check, recorded with the wrong trial's facts. The other extractor's statement is
  checked against its own trial.

### C.3 Gemini batch path (`core/llm/providers.py: GoogleBatch`)

- **Price:** Google lists batch for Gemini 4 Argon at half the interactive price ($2 / $10 per 1M
  from 2026-12-01; $1 / $5 until then), checked on Google's pricing page 2026-11-03.
  `models.yaml: tiebreak.batch_discount` is now 0.5.
- **Same request, same cache key.** The batch request uses the exact config of the synchronous call,
  so the pilot's cached Argon answers are still used. The cache key never included batch or sync
  mode. **Wrong, corrected in C.5:** the batch service ignored the schema sent this way.
- **Answers are matched by key, never guessed.** Each inline request carries its cache key as
  metadata. Google documents the key echo only for file input, so an answer without a key takes its
  submission position, and anything that cannot be matched is an error for that request.
- **Size:** inline batches must stay under 20 MB. The runner sends at most 300 Gemini requests per
  batch (about 30 KB each), and the provider refuses anything over 18 MB before submitting.
- **Runner:** `collect` now receives the batch's keys in submission order (the other providers ignore
  them). Chunks are still sequential, so the bootstrap's roughly 12 tie-break batches run one after
  another, each within Google's 24-hour target.
- **Price correction:** Argon's cached-input price is $0.20 per 1M from December, not $0.40.
- **Not changed:** the `argon` flagship entry (arena, harness) stays synchronous in `models.yaml`
  until those milestones.
- **Tests:** `tests/test_google_batch.py` (11 tests on synthetic responses shaped like the recorded
  pilot responses; no network).

### C.4 CT.gov refresh and subsidiary matching (`ledger/names.py`, `ledger/sources/ctgov.py`)

**The refresh** (public API, free, 365-day window as before) brought in the 40 subsidiary-led trials
the previous fix allowed, DENALI and ASPENOVA among them. The rejected lead-sponsor names in the
same pages showed a larger gap:

| Parent | Lead sponsor on CT.gov | Trials before → after |
|---|---|---|
| Merck & Co. | "Merck Sharp & Dohme LLC", and "a subsidiary of Merck & Co., Inc. (Rahway, …)" (the place broke the match) | 0 → 310 |
| Johnson & Johnson | "Janssen …" (J&J's own search never returned them) | 3 → 178 |
| BMS, Gilead, Sanofi, Novo Nordisk and others | "X, a Y company" (Karuna, Juno, Kite, Genzyme, Dicerna, …) | e.g. BMS 127 → 145, Gilead 72 → 88 |
| Teva, Bausch Health | "Teva Branded Pharmaceutical Products R&D", "Bausch Health Americas" | 0 → 15, 0 → 9 |

- **What changed:** "X, a Y company" and a parenthesized place now resolve to Y. A short alias list
  in `config/sources.yaml` (`ctgov.parent_aliases`) covers subsidiaries whose name does not say so:
  MSD, Janssen, Teva Branded, Bausch Health Americas. An alias can add a registry search (Janssen).
  Only companies that are plainly wholly owned are listed.
- **A name that matches two universe companies is assigned to neither.** "QED Therapeutics, a
  BridgeBio company" reads as both BridgeBio Pharma and the separately listed BridgeBio Oncology
  Therapeutics. Before this guard, 11 such trials went to whichever matched last.
- **Tests first:** 16 cases in `tests/test_timing_names.py`, including names that must not match
  (Merck KGaA, "an affiliate of", COMPASS Pathways against Compass Therapeutics). One regression
  was caught on the real data and is now a test: Morphic writes its subsidiary note in parentheses.
- **Result:** the registry has 4,538 trials (from 3,916). There are 29 new stopped-trial documents,
  so the bootstrap reads 5,382 documents (from 5,353), and 4 new exclusions (21 → 25), one of which
  is an open `exclusion_link` item for the operator. Events, promises and labels are unchanged.
- **Not covered:**
  - **Roivant** still has no trials. Brepocitinib is run by Priovant, which Roivant owns mostly but
    not wholly, and a "roivant" search does not return it. Whether a majority-owned, unlisted
    subsidiary counts as the parent is a question for the operator.
  - **BridgeBio Pharma's** 11 subsidiary-led trials are held back as ambiguous. Aliases that take
    precedence over the "a Y company" reading would fix it.
  - **About 20 small sponsors** run trials through local entities ("Neurocrine UK Limited",
    "Pharvaris Netherlands B.V.", "Ascendis Pharma Endocrinology Division A/S"), about 70 trials
    in all. Each needs checking before it is listed.
  - Subsidiaries whose names share nothing with the parent and that no alias covers (for example
    Alexion for AstraZeneca) are never searched for.
- **Re-measure base:** `data/backups/ledger-before-pilot2-ctgov-20261103.sqlite` is the pre-pilot
  state plus this registry. It replaces `ledger-before-pilot2.sqlite` for re-runs, because the old
  base would undo the refresh.

## 2026-11-03 · Pilot run 7: prompt v2 re-measure (operator approval; fixes by Claude)

**Run** `ledger-20261103T211404Z-0b0acec`, approved by the operator ("Yes, run it"). The 50 pilot
documents were re-run from `data/backups/ledger-before-pilot2-ctgov-20261103.sqlite`, keeping
every earlier completion and spend record. The run-6 ledger is in
`data/backups/ledger-before-pilot-v2-20261103.sqlite`, and this run's in
`ledger-after-pilot-v2-20261103.sqlite`.
- **Spend:** $0.095 actual against a $0.40 estimate (cap $3.00): Haiku $0.017, Luna $0.009,
  Gemini $0.070 (6 tie-breaks). 106 paid calls, no errors from any provider.
- **The extractors are measured.** The tie-break stage is not: all 6 tie-break answers were
  unreadable (C.5), so those 6 items sit in the queue as abstentions until they are redone.

**What v2 changed** (cached v1 answers under today's code → v2; quote-verified statements):

| | v1 | v2 |
|---|---|---|
| Statements found by both extractors | 26 of 53 | **30 of 37** |
| Found by Haiku only / Luna only | 23 / 4 | 4 / 3 |
| Phase agrees | 18 / 21 | 25 / 25 |
| Timing window agrees | 11 / 12 | 9 / 9 |
| Result category agrees | 13 / 13 | 21 / 21 |
| Stop subtype agrees | 3 / 3 | 6 / 9 |
| Sponsor's stated reason agrees | 5 / 6 | 11 / 14 |
| Tie-breaks needed | 17 | 6 |
| Extractor input tokens (Haiku / Luna) | 303k / 164k | 381k / 212k |

- **Ledger, run 6 → run 7:** 20 → 17 events, 19 → 13 promises, 9 → 15 labels.
- **Three of the four known errors are gone:** vTv's enrollment-completion promise, Sanofi's ESTUARY
  extension study, and Zai Lab's PDUFA date for Vertex's application. The fourth, Roivant's
  batoclimab timing (Immunovant's trial), is now a lone statement awaiting one of the 6 tie-breaks.
- **Also changed:** Lilly's stopped pediatric COV-BARRIER study is accepted by agreement (it was a
  queue item); Sanofi's COAST 2 readout is a new event; Immunic's vidofludimus timing (stated only
  in the "About" paragraph) dropped as expected, and one extractor's version awaits a tie-break.
- **Partner mentions:** Haiku 4, Luna 5 (3 of each name a universe company). None became an event.

**Queue.** 21 items: 10 `low_confidence`, 5 `disagreement`, and the 6 unreadable tie-breaks.
- All 10 `low_confidence` items are full agreement on every reserved field. Haiku rated itself
  0.35–0.75 on each, Luna 0.86–0.98.
- All 5 disagreements agree on the result (stopped, missed) and differ on the stop subtype or the
  sponsor's stated reason.
- No item is a result only one model reported (v1: 8).

**Implied for the bootstrap** (5,332 documents; stratified, 95% intervals over documents):

| | v1, today's code | v2 |
|---|---|---|
| Queue items (v2 without the 6 unreadable tie-breaks) | ≈1,540 (800–2,380) | **≈930 (310–1,740)** |
| of which agreements with low confidence | ≈670 (200–1,280) | ≈720 (160–1,490) |
| of which results only one model reported | ≈560 (150–1,080) | 0 in the pilot |
| of which real disagreements on a reserved field | ≈16 (0–49) | ≈210 (30–540) |
| Tie-breaks | ≈2,410 (1,030–4,230) | ≈840 (150–1,670) |
| Tie-break USD (December batch price) | ≈$27 ($11–$48) | ≈$10 ($2–$19), provisional |
| Extractor USD | $2.63 ($2.18–$3.08) | $2.88 ($2.32–$3.49) |

The v2 tie-break cost uses the unreadable answers' token counts; the redo replaces it. The redo
(2026-11-05, below) measured $9.72 ($2.41–$19.18), and the queue at ≈1,080 (410–1,920).

| # | Decision (Claude, within existing rules) | Closes |
|---|---|---|
| C.5 | **Gemini batch requests send the schema as `response_schema`, and have their own cache key.** | Run 7's 6 unreadable tie-breaks |
| C.6 | **Every answer is checked against its schema before it is cached.** An answer off the schema is an error: recorded and paid for, never cached, asked again next run. | Same |

### C.5 The Gemini batch bug

- **What happened:** the batch service answered in JSON but ignored the schema sent as
  `response_json_schema`. Each answer used field names of its own, so none could be read, and the
  pipeline filed all 6 as abstentions. The synchronous service honored the same field in run 3.
- **Fix:** batch requests send `response_schema`, the field in Google's batch documentation. The
  synchronous path is unchanged. A schema the batch field cannot express (the extraction schema's
  "string or null" types) is refused before anything is submitted.
- **Cache key:** a Google batch request now carries `schema_field: response_schema` in its
  parameters, so it never reuses the 6 unreadable answers (which stay cached, as every completion
  does). Synchronous Google keys and all Anthropic and OpenAI keys are unchanged; a test pins one.
- **Not verified until the redo:** that the batch service honors `response_schema`. Incomplete:
  Google refused it as sent (2026-11-04, C.7). Verified 2026-11-05: with C.7, all 6 answers
  followed the schema.

### C.6 The schema check (`core/llm/runner.py: schema_error`)

- A provider's schema enforcement can fail without an error, as above. Every new answer from every
  provider is now validated (JSON Schema 2020-12, `jsonschema`) before it is cached.
- Error messages name the rule and the place only, never a value, because values can be document
  text.
- **Checked on every cached answer:** all 315 other answers (Haiku 100, Luna 150, Gemini 24,
  Ornith 41) pass; exactly the 6 unreadable batch answers fail.
- A tie-break that fails is still queued as `tiebreak_abstained`, now with a note saying it failed,
  so the operator can tell a failure from the model declining.
- **Tests first:** 5 in `tests/test_google_batch.py` (3 new, 2 rewritten) and 4 in
  `tests/test_schema_check.py`; all failed before the fix. 197 pass.

### Found, not fixed: outcome dates fall back to the filing date

Sanofi's COAST 1 result is dated 2026-03-28 in its press release and was filed on a 6-K on
2026-03-31. Under v1 one extractor gave the release date; under v2 neither gave a date, and the
pipeline falls back to the filing date. The prompt instruction is the same in both versions.
- **Why it matters:** an outcome dated after it became public makes the arena's rule (S4: a
  forecast committed after its event resolved is void) too lenient. Foreign issuers often file 6-Ks
  days after the release.
- **Proposed fix (critical piece 7, tests first):** fall back to the date the document itself
  carries (its dateline) before the filing date. Not done in this change.

## 2026-11-04 · Tie-break redo: refused by Google at $0 (operator approval; fixes by Claude)

**Run** `ledger-20261104T160324Z-0b0acec`, approved by the operator ("Yes, redo them"). It was
rebuilt the same way as run 7, from `ledger-before-pilot2-ctgov-20261103.sqlite` with every
completion and spend record. The run-7 ledger is in `ledger-before-tiebreak-redo-20261104.sqlite`.
- **Spend:** $0.00 against a $0.34 estimate (cap $3.00). The extractors were all cached. Google
  refused the tie-break batch when it was submitted, so nothing was created or charged. The spend
  record says `failed`.
- **What Google said:** its `response_schema` has no `additionalProperties` field. That is the
  only field it named.
- **What the crash did:** the 50 documents were already marked done, so the 6 disputed statements
  were neither accepted nor queued. The ledger was saved as
  `ledger-after-refused-redo-20261104.sqlite` and rebuilt from the base again.
- **Found by a pinned test while fixing it:** the Google SDK edits the schema it is given. On the
  batch path it adds `property_ordering` inside the shared tie-break schema. Every tie-break's cache
  key would then change after submission, the pipeline would not find its own answers, and all of
  them would be queued as "not run". The synchronous path leaves the schema alone.

| # | Decision (Claude, within existing rules) | Closes |
|---|---|---|
| C.7 | **The Gemini batch schema is a fresh copy without `additionalProperties`.** The schema check (C.6) still enforces it on every answer. | The refusal; the SDK edit |
| C.8 | **A batch refused at submission is an error for each of its requests, not a crash.** Its reservation is released, nothing is cached or counted as a call, and the next chunk still goes out. | Refusals losing work |
| C.9 | **If the tie-break stage fails any other way, every dispute is queued before the job fails.** | Disputes lost without trace |

### C.7 What the batch request sends (`core/llm/providers.py: batch_schema`)

- Batch requests send `response_schema` built from a copy of the schema with every boolean
  `additionalProperties` removed. Everything else Google's schema can express is still sent: types,
  required fields and the choice list.
- **The rule is not lost.** Gemini constrains its output to the listed fields, and the schema
  check rejects any answer with a field the schema does not allow. A new test case covers that.
- **Tested offline against the real SDK:** a test captures the exact body the SDK would post. It
  checks that the body uses only fields of Google's `Schema` and keeps the constraints above, and
  that the request's own schema and cache key are unchanged after submission.
- **Cache key:** unchanged from C.5 (`schema_field: response_schema`). Nothing was ever cached under
  it, because the refused batch produced no answers.

### C.8 and C.9 Nothing is lost when a tie-break cannot run

- **A refusal** is a `ValueError` from `submit`. That covers our own checks, and Google 4xx errors,
  which mean the batch was not created. Each request gets the error "batch refused: …". The
  tie-break stage then queues it as `tiebreak_abstained` with the note "tie-break failed: batch
  refused: …".
- **Anything else** (a Google 5xx or a lost connection) may have created the batch, so it still
  stops the job. Before the job stops, every dispute is queued with the note "tie-break not run:
  <error type>".
- **Why not leave the documents pending instead:** neither accepting a statement nor queuing an
  item is safe to repeat. Re-running a document would duplicate its other statements' labels and
  queue items.
- **Follow-up before the bootstrap:** failed and not-run tie-breaks should be retried
  automatically on the next run, not left in the operator's queue. That is not built yet.
- **Tests first:** 5 new tests in `tests/test_google_batch.py` and a third case in
  `tests/test_schema_check.py`. The 5 failed before the fix, as did the pinned cache-key test once
  the SDK had edited the shared schema. 203 pass.

### Second attempt, 2026-11-05: the 6 tie-breaks are done ($0.071)

**Run** `ledger-20261105T054327Z-0b0acec`, approved by the operator ("Yes, run it again"). It was
rebuilt from the same base, keeping every completion and spend record. The refused attempt's
ledger is in `ledger-after-refused-redo-20261104.sqlite`, and this run's in
`ledger-after-tiebreak-redo-20261105.sqlite`.
- **Spend:** $0.071 against a $0.34 estimate (cap $3.00). 6 paid Gemini calls and 100 cached
  extractor answers. Google accepted the batch, and all 6 answers followed the schema. No errors.
- **All 6 disputes were statements only one extractor reported.** The question was whether each
  should be reported at all. Every decisive quote matched its document exactly.

| Sponsor | Statement | Gemini | Result |
|---|---|---|---|
| Immunic | vidofludimus readout timing (Luna only) | keep | promise, model-adjudicated |
| Telix | floretyrosine F 18 PDUFA date (Haiku only) | keep | promise, model-adjudicated |
| Roivant | batoclimab Phase 3 readout timing (Haiku only) | keep | promise, model-adjudicated |
| Roivant | mosliciguat Phase 2 readout timing (Haiku only) | keep | `scope_check` on phase (R.2) |
| Immunovant | IMVT-1402 readout timing (Haiku only, confidence 0.4) | drop | not reported |
| Zentalis | azenosertib Phase 2 readout timing (Luna only) | drop | not reported |

- **Checked against the rules (by Claude, without reading the text into any record):**
  - **Immunic:** Gemini's quote is in the body of the release, before the "About Immunic" company
    description. Keeping it follows the prompt. Run 7's note said this timing appears only in the
    company description. Gemini found it in the body, so that note was wrong.
  - **Roivant batoclimab (the fourth known error) is still wrong under R.1.** Immunovant runs the
    trial, and Immunovant is separately listed and in our universe. The Roivant document never
    shows that: it gives no Immunovant ticker and does not call Immunovant publicly traded. The
    prompt's test is the document's own evidence, so by the prompt Gemini decided correctly. The
    gap is that the pipeline knows Immunovant is listed and the extractors do not. A deterministic
    check is proposed below. It is not built yet.
  - **The two drops** were not checked by hand.
- **Ledger, run 7 → this run:** 17 → 19 events, 13 → 16 promises, labels unchanged at 15.
- **Queue:** 16 items from this run: 10 `low_confidence`, 5 `disagreement`, 1 `scope_check`. None
  comes from a failed tie-break.

**Implied for the bootstrap** (5,332 documents; stratified, 95% intervals over documents):

| | v2, measured |
|---|---|
| Queue items | **≈1,080 (410–1,920)** |
| of which agreements with low confidence | ≈720 (160–1,490) |
| of which real disagreements on a reserved field | ≈210 (30–540) |
| of which phase scope checks from tie-broken statements | ≈150 (0–440): one item in 25 8-K documents |
| Tie-breaks | ≈840 (150–1,670) |
| Tie-break USD (December batch price) | $9.72 ($2.41–$19.18) |
| Extractor USD | $2.88 ($2.32–$3.49) |

**Proposed, not done (R.1 gap):** before a statement is accepted under sponsor X, check whether
its asset is already filed under another sponsor in the universe. A listed subsidiary's program
would then be filed under the subsidiary, or queued, whatever the parent's release says. This
needs the operator's answer on majority-owned subsidiaries first (Roivant: Immunovant is listed;
Priovant and Pulmovant are not).


## 2026-11-05 · Queue options for the bootstrap (measured by Claude; the operator's choice)

Handoff item 6: "bring options, don't pick one". Measured on the pilot's 16 queue items (10
`low_confidence`, 5 `disagreement`, 1 `scope_check`) with the same stratified bootstrap as above.
Scripts are local (`conf_study.py`, `scenarios.py`); they print counts and field names only.

**Found 1: the self-rating behind `low_confidence` is not about the reserved fields.** The prompt
asks for the probability "that every field of the statement is correct" (dates, NCT number, phase
included). The brief's rule is about low confidence on the result and the stated reason. Haiku rated
7 of its 21 outcome statements at 0.8 or above; Luna rated 21 of 22. Haiku's rating is a little lower
on average when the two disagree (0.35–0.8) than when they agree (0.35–0.85), but the ranges overlap.
All 10 `low_confidence` items have Luna at 0.86 or above.

**Found 2: CT.gov stops from before 2025 enter the ledger, dated by the record's last edit.** Nothing
enforces the ledger's 2025-01-01 start. 78 of the 172 CT.gov stopped-trial documents had their
actual primary completion before 2025, and a stop takes the date the record was last updated. In the
ledger now: NCT05074420 (Lilly, baricitinib), primary completion 2024-09-05, stored as a 2026-08-11
stop. 4 of the 16 pilot items are such stops (NCT01437787, NCT05516758, NCT05664217, NCT04729387).
- **Decision (Claude, within the fixed scope):** this joins the outcome-date fix already proposed
  (critical piece 7, tests first). A CT.gov stop is dated by its actual primary completion date, and
  an outcome dated before 2025-01-01 is out of scope; the baricitinib label gets a correcting
  version. Not done yet.

**Claude's reading of the 15 outcome items** (a model's reading, not a human check). All 10 agreed
answers match their documents; two are judgement calls (Lilly peresolimab's subtype; Immutep's
trigger, where futility and DSMB both fit). Of the 5 disagreements, 2 are CT.gov records whose only
reason is "Sponsor decision", which G5 (6) leaves to the operator anyway.

**Options** (bootstrap queue with 95% intervals; the steady state uses a year of documents, about
206 per fortnight; Q-C11's target is 30 per fortnight or fewer):

| Option | Changes the brief's rule? | Bootstrap queue | Per fortnight | Extra cost |
|---|---|---|---|---|
| Today | | ≈1,080 (410–1,920) | ≈42 | |
| Today with the date floor (Found 2) | no | ≈1,016 (344–1,869) | ≈39 | none |
| A. Ask for confidence on the result and the reason only (prompt v3) | no: matches its wording | not measurable without a re-run | ? | re-pilot under $0.10 |
| B. Two vendors agreeing is enough; no self-rating | yes | ≈344 (32–786) | ≈13 | none |
| C. Gemini confirms each low-confidence agreement; a mismatch goes to the operator | yes | between ≈344 and ≈1,016 | 13–39 | ≈$8; pilot check ≈$0.10 |
| D. B, plus a random audit of 60 agreed outcomes, with a pass bar set in advance | yes | ≈400 if it passes | ≈13 | none |
| E. One decision per outcome: repeats of a decided outcome attach as sources | no | not measurable on the pilot | | none |
| F. A faster review screen (agreed answer pre-filled, similar items grouped) | no | same count, less time | | none |

- **D's bar:** with 0 errors in 60, the 95% upper bound on the error rate is about 6%; with 1, about
  9%. The sample is drawn from all agreed outcomes, so it also measures today's auto-accepts, which
  have no measured error rate.
- **E's potential:** in the pool, other filings from the same sponsor name a pilot outcome's drug
  near result wording 0 to 8 times (median 1). Rough; it can be measured for free after the bootstrap
  extraction.
- **The scope check** (≈150, from a single item) would be settled automatically if the registry
  were searched by drug name. Mosliciguat's trial is registered under Pulmovant. This waits on the
  majority-owned subsidiary question.

### Operator's choice: B + D, with an audit Claude prepares and the operator verifies

Operator, 2026-11-05: "can we do B + D with a model (i.e. you) assisted audit - you review, weigh
the evidence, make the tentative call, then run them by me for human verification?"

| # | Decision | Closes |
|---|---|---|
| V.1 | **B:** two extractors from different vendors agreeing on every reserved field is enough to accept. The self-rating no longer sends anything to the queue; it is still recorded. Disagreements still go to the operator. | C11 (routing) |
| V.2 | **D, assisted:** a random sample of 60 agreed outcomes is audited. Claude reads each one first and makes a tentative call; the operator verifies every one, and the operator's verdict is the label of record (`human:operator`) and the count that is published. | C11 (audit) |

**How the audit runs (Claude's design, within V.2):**
- **Pool and draw:** every outcome the bootstrap accepts by agreement. That is about 1,310
  (460–2,350) after the date floor. The 60 are a simple random draw, with the seed committed before
  the extraction runs.
- **Blind first reading:** Claude sees the document and which event it is (sponsor, drug, trial,
  event type), not the extractors' answer. Claude records its own value for each reserved field,
  where the deciding passage is, and a one-line reason (paraphrased, no document text).
- **Then the comparison:** each item goes to the operator with the agreed answer, Claude's answer and
  reason, and the passage from the local copy. Items where Claude differs or is unsure come first.
- **Record:** per item, Claude's call, the model (`claude-opus-5-5`, in a Claude Code session), and
  the operator's verdict, so how often the operator overruled Claude stays visible. Claude's calls
  are advisory and are not cached completions. The published error rate is the operator's count.
- **Error:** any reserved field (result, stop subtype, data trigger, stated reason) the operator
  sets differently from the agreed answer. How many would change a score is reported alongside.
- **Limits, for the methods page:** Claude is Anthropic's, the same vendor as extractor A (Haiku),
  so its reading is not independent of Haiku's; the operator's check is the independent one. Anthropic
  is also an evaluated provider (see Q-E2). The operator sees two answers that usually match, so
  some anchoring is possible.

| # | Decision | Closes |
|---|---|---|
| V.3 | **Pass bar** (operator, 2026-11-05: "Yes, that bar"): the audit passes with 0 or 1 errors in 60 (with 1, the 95% upper bound on the error rate is about 9%). With 2 or more, Gemini checks every agreed outcome (≈$15, $5–$28) and every mismatch goes to the operator. | C11 |

## 2026-11-05 · Before the bootstrap: V.1 built, outcome dates, tie-break retries, the audit draw

V.1–V.3 are the operator's (above). The rest are Claude's decisions within existing rules. The
outcome-date changes are critical piece 7, so tests came first (`tests/test_outcome_dates.py`, 17
tests, and `tests/test_tiebreak_retry.py`, 5 tests; each failed before its fix). 232 tests pass.

| # | Decision (Claude, within existing rules) | Closes |
|---|---|---|
| C.11 | **A CT.gov stop is dated by the registry's actual primary completion date**, not by the day its record was last edited. Both candidates take it, so it never splits a pair. | Found 2 (dates) |
| C.12 | **The ledger's start is enforced.** An outcome dated before 2025-01-01 never reaches the ledger. The drop is kept as a closed `scope_check` (`auto:scope`), with the statement. | Found 2 (floor) |
| C.13 | **An outcome the extractors leave undated takes the document's own date** (its dateline) before the filing date: the first date in the first 1,500 characters that falls on the filing day or up to 14 days before it, skipping balance and period dates ("as of", "ended"). | Run 7 (COAST 1) |
| C.14 | **An undated restatement can move an outcome's date earlier, never later.** A date the document states always applies. | Found in the replay |
| C.15 | **A tie-break that failed or never ran is retried on the next run**, up to 3 tries in all, and the dry-run counts the retries. The old queue item is closed (`auto:retry`) in the same transaction as the new result. A model's own "neither" stays with the operator. | Follow-up of C.8/C.9 |
| C.16 | **The audit is set in advance in `config/audit.yaml`**: n = 60, a seed drawn with Python's `secrets` module, the V.3 bar and failure path. `ledger audit-draw` draws the sample (free, local) and records the pool size and IDs in `data/audit/`. Audit items use the existing `outcome_confirmation` queue reason, so the schema is unchanged. | V.2, V.3 |

**C.13, measured on the pool** (5,210 filings that pass the prefilter): a date is found in 4,188
(80%). It is the filing day in 90% of those, 1–4 days earlier in 9%, and 5–14 days earlier in 2%.
A first version that allowed 31 days picked up "cash as of June 30" and slide numbers past 10 days.
A hand check of 24 dates found 2–14 days before filing found all to be release datelines.

**Replay** (pilot documents on a scratch copy of the ledger, $0.00: 106 cached answers, no paid
calls, uncached calls refused). Against the current pilot ledger:
- **Queue:** 16 → 5 (4 disagreements, 1 phase check), plus the 2 CT.gov exclusion links from
  ingestion. No `low_confidence` items.
- **Out of scope:** 5 CT.gov stops that ended before 2025 (NCT01437787, NCT04729387,
  NCT05074420, NCT05516758, NCT05664217). Lilly's baricitinib stop, stored as 2026-08-11, is gone.
- **Ledger:** 19 → 25 events, 6 → 12 resolutions. The 10 agreed results that waited in the queue
  are accepted. Sanofi's COAST 1 and 2 are dated 2026-03-28, the release, not 2026-03-31.
- **Known limit:** an outcome restated without a full date takes the restating document's date.
  Agios's Dec 2025 approval is dated 2026-01-12 (a January deck), Immutep's March stop 2026-07-13,
  and Prothena's June 2025 discontinuation 2025-11-06. In the bootstrap, the original report, if it
  is in the pool, moves the date back (C.14). The pool starts 2025-10-31, so outcomes announced
  earlier in 2025 appear only through restatements; that is the backfill job's scope.
- **Effect on published numbers:** none is published yet. The base rate would otherwise have
  counted old stops as 2026 stops.

**Bootstrap dry-run** (`ledger extract --job-kind ledger_bootstrap`, on the replayed ledger, no
calls): 11,731 calls, **est. $43.35** against the $75 cap. Extractors $6.24 (1,200 output tokens
assumed per call) and tie-breaks $37.11 (20% of documents at 2,500 output tokens assumed). **The
pilot measured about $13 ($5–$23):** extractors $2.88 ($2.32–$3.49) and tie-breaks $9.72
($2.41–$19.18). Under V.1 the queue is ≈344 (32–786) items, plus the audit's 60.

## 2026-11-05 · Bootstrap go-ahead (operator)

Asked: commit and push the branch (so the audit seed in `config/audit.yaml` is on record before
any label exists), swap in the replayed pilot ledger, and run the bootstrap (dry-run estimate
$43.35, pilot-measured about $13, cap $75 unchanged). Operator, 2026-11-05: "Yes, commit and run".
The current pilot ledger is kept in `data/backups/ledger-before-v3-replay-20261105.sqlite`.
