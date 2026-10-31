# Questions for the operator (v3)

Updated 2026-10-30 after your Step 1 review, and again after your ledger v0 review (decisions T, Q,
O, N). **Decided items are in `docs/decisions.md`.** They stay
listed here as one-line pointers, so every `Q-xx` reference still resolves.

**How to answer quickly:** every open item has a **default** (my recommendation). Reply "defaults OK
except …" with IDs and your changes.
- ⛔ = blocks the next milestone (ledger v0 PR).
- ⏳ = needed by the milestone shown.
- ✅ = decided.

**Keys:** put them in `.env` yourself. Never paste them into chat. I only need to know they're there.

---

## G: New questions raised by your decisions

| ID | Question | Default |
|---|---|---|
| ✅ G1 | Decided (O.1): official setup, no paper context. **LitQA2 paper context.** In the official setup the model gets no paper text, only the question, because LitQA2 was built for retrieval agents. Adding paper context would make it a different task (reading comprehension) and break comparability with published scores. So prompt caching applies to shared instructions only. | Official setup, with no paper context. Optionally, a separately labeled "with-context" variant later. It would never be mixed into the headline. |
| ✅ G2 | Decided (O.2): accept the premium; harness stays uniform; deviations list says batch mode doesn't change outputs. **"Batch for every job": two exceptions.** Inspect's Gemini batch mode can't use thinking, and Meta has no batch API. Together they're about 40% of launch-run spend. | Accept synchronous for both at launch, recorded in `models.yaml`. Write our own Gemini batch client only if Gemini's share of measured pilot cost justifies it (it saves about $30 at mid). |
| ⏳ G3 | **Anchor selection.** tinyBenchmarks fits an IRT model on a response matrix from many models, and one reference run can't fit IRT. | Use the six launch runs plus the preprint's per-item results if its repo releases them. If that matrix is still too thin, use stratified anchors (by subtask and launch-run difficulty) with honestly wider intervals. Anchors are used only if leave-one-model-out validation passes, and otherwise model-days run in full (about $77 mid for a top-priced model). |
| ⏳ G4 | **Sequential-stopping target.** At accuracy ≈ 0.5 the rule (half-width ≤ 0.05, Bonferroni-Wilson) needs about all the items. Savings come only at high or low accuracy (about 300 items at 0.9). The half-width target is your lever: at 0.07, SeqQA stops by about 400 items at accuracy 0.5 and about 300 at 0.8, at the cost of wider published intervals. | Half-width 0.05, with a minimum of 150 items and checkpoints every 50. |
| ⏳ G5 | **Partly decided:** (1) confirmed (T.4); (2) replaced by T.1 (data trigger → missed, else void). (3)–(6) still open. **Taxonomy readings of your void rule** (`docs/taxonomy.md` §7). The code implements them as written until you change them: (1) operational stops → void; (2) a business stop that *discloses* topline data → void as written, though I recommend scoring it on the data; (3) withdrawn for a financial or strategic reason → void, otherwise 0; (4) split = a tie on the deciding question → 0, so it can no longer be void; (5) AdCom held without a vote → void; (6) a stop with no stated reason → never void, and you assign the subtype in review. | As listed, except (2): score on the data when primary-endpoint results are disclosed. **Needed before the first arena event is scored.** |
| ⏳ G6 | **MMLU-Bio and PubMedQA, pilot-only.** They'd appear on the site only as "saturated: see preprint", with the pilot's 50-item accuracy and interval as evidence and no leaderboard numbers. If the pilot shows a flagship clearly *below* ceiling, the decision comes back to you. | Yes |
| ⏳ G7 | **"Hashed and public before resolution" (your COI policy).** For forecasts this matches commit-reveal (Q-C2): the hash is public at run time and the forecasts at resolution. Publishing live forecasts on open catalysts would publish trading signals. For labels, it means each refresh's label export is hashed and timestamped. Confirm that reading. | Forecasts: hash public before resolution, content at resolution. Labels: public daily in exports, plus a hashed and timestamped snapshot per refresh. |
| ⏳ G8 | **The documented capped reasoning tier.** It has to be one named setting, identical across vendors. | Provider effort "low" where effort levels exist, plus a 4,096-token reasoning cap where the API takes a budget, and max output 6,000 tokens. Truncations are counted and reported. Measured on the pilot. If truncation exceeds 2% of items, it comes back to you before launch. |
| ⏳ G9 | **Suspended trials** (`docs/taxonomy.md` §7.9). CT.gov `SUSPENDED` is often a clinical hold, and the trial may resume. It is currently treated like a stop, so a hold could resolve a readout as stopped/safety (0). | A suspension does not resolve the event. It is recorded, and the event stays open until the trial is terminated or reads out. **Needed before the first arena event is scored.** |
| ⏳ G10 | **Stopped after enrollment, citing another trial's results** (§7.7). It is an event, but its own data didn't decide the stop. | Void, linked to the cited trial, as for the withdrawn case (T.3). |
| ⏳ G11 | **One-off ledger jobs and the $150 monthly cap.** The cap applies to every `ledger_*` and `arena_*` job, so the bootstrap ($75 cap) and the backfill ($150 cap) count toward it. The backfill could never run in a month with any other spend. | Exclude bootstrap and backfill from the monthly cap. They keep their own hard caps and each needs your explicit go-ahead anyway. |
| ⏳ G12 | **A business stop after a positive interim** (§7.8). T.1 scores a documented data trigger as missed. | When the sponsor reports the interim as a success, the subtype is `efficacy` (scored 1), not business. |

---

## K: Keys and accounts

| ID | What | Status |
|---|---|---|
| ⛔ K1–K3 | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | ✅ decided (D.1): project-scoped keys with console spend limits. Blocking until they're in `.env`. |
| ⛔ K7 | `SEC_USER_AGENT`: a real name and contact email | ✅ decided (D.2). Blocking until it's in `.env`. |
| ⛔ K11 | GitHub repo `techbio-benchmarks` under your org | ✅ decided (D.3). Still needed: **the org name**, and `gh auth login` run once by you (gh is now installed). |
| ⏳ K4 | `XAI_API_KEY` | arena, harness (M2) |
| ⏳ K5 | `META_API_KEY` (Meta Model API, dev.meta.ai) | `muse-wonder-1.0` (M2). It has no batch API. Never use `-contributor` models, which train on your data. |
| ⏳ K6 | `TOGETHER_API_KEY` | GLM-5.3 (M2) |
| ⏳ K8 | `OPENFDA_API_KEY` (free) | raises the limit from 1k to 120k requests/day. Effectively needed for backfill. |
| ⏳ K9 | `HF_TOKEN`, with the GPQA gated-dataset terms accepted on that account | GPQA (M3), and dataset push (M4) |
| ⏳ K10 | Zenodo account linked to GitHub, plus your ORCID | DOI per tagged release (M4) |
| ⏳ K12 | R2 or B2 object-storage keys, only if F2 = B | state for the daily Action (M4) |

---

## M: Money (figures from `docs/cost-estimates.md`, revised)

| ID | Question | Default |
|---|---|---|
| ⏳ M1 | Harness launch budget | Decide after the pilot. New estimates for pilot, launch run, second seed, and uncapped run: $470 / **$820** / $1,440 (low / mid / high). Validation add-ons are $170 / **$340** / $670. The pilot alone is $43 / **$81** / $136. |
| ✅ M2 | Monthly operating cap for ledger plus arena | **$150** (decided, O.3) |
| ✅/⏳ M3 | Standing pre-approval for daily ingestion | ✅ $3/day for ingestion and resolution (D.4). Still open: a monthly ceiling on it, default **$40/month**. |
| ✅/⏳ M4 | Per-job hard caps | ✅ Arena round **$60**, pilot **$100** (decided, O.3). Still default: bootstrap $75, backfill $150. Harness and model-day caps are 1.5× the pilot-measured cost. The bootstrap still needs its own go-ahead after its dry-run. |
| ✅ M5 | Reasoning setting | Decided (C.1): capped low/medium for all items. The exact setting is G8. |

---

## A: Scope · ✅ all decided

A1–A7: defaults accepted (B.4). They're restated in `docs/taxonomy.md` §1. A6 (backfill 2025-01 to
present, about $88) runs as a separate approved step after v0.

## B: Taxonomy · ✅ all decided

B1–B7: defaults accepted, with **B3 and B4 amended** by your narrow void rule (B.4). Taxonomy v1 is in
`docs/taxonomy.md`. My readings of the void rule are G5.

---

## C: Arena

| ID | Question | Default |
|---|---|---|
| ⏳ C1 | Question wording for each event type | readout: P(primary endpoint met at topline); decision: P(approval at this action); AdCom: P(favorable vote) |
| ⏳ C2 | When are forecasts published? | **Commit-reveal.** The hash is published at run time and each event's forecasts at its resolution (see G7). |
| ⏳ C3 | Anchor commitments outside git as well? | Yes, with OpenTimestamps (free). |
| ⏳ C4 | Packs built from structured facts, CT.gov text (public domain), and links only, so they can be published at resolution and re-verified | Yes. The trade-off is that models don't see the sponsor's exact wording. |
| ✅ C5 | Arena roster | Decided (C.8): five flagships plus the leading open-weight model. Mid-tier models on their own model-days. |
| ⏳ C6 | Keep superseded model versions in the arena until they reach n = 100 or are deprecated? | Yes (about +25% arena cost on average across year one) |
| ✅ C7 | Market baseline | Decided (B.2): Kalshi, computed internally, prices never exported until you confirm display rights. Contract matches are confirmed in the queue. |
| ⏳ C8 | Assign horizon buckets by expected or by realized time to resolution? | Expected, consistent with selection. Realized is stored too. |
| ✅ C9 | Temperature can't be set | Decided (A.1): mean of 2 samples, spread published, raw draws stored, seed set where supported. |
| ⏳ C10 | Log-loss clipping | ε = 0.001, with the count of clipped forecasts reported |
| ⛔ C11 | Confidence threshold for the reserved fields | τ = 0.8, plus quote verification. Tuned on the extraction pilot so the queue stays at 30 items or fewer per fortnight. **Ledger v0 uses this default unless you say otherwise.** |
| ✅ C12 | Reasoning setting | = M5 and G8 |
| ⏳ C13 | Base-rate baseline while history is thin | As-of ledger rate with a Jeffreys prior, backing off to a coarser cell when n < 20, with n shown |
| ⏳ C14 | Unit for the power rule | unique resolved events per model_version, using headline forecasts |

---

## D: Harness and validation (⏳ M3)

| ID | Question | Default |
|---|---|---|
| ✅ D1 | LAB-Bench grader | Decided (A.2): the official setup (FutureHouse prompt, parser, scorer, pinned commit) for all headline numbers. inspect_evals' tasks run on the pilot as a cross-check, and the gap goes in the deviations list. |
| ⏳ D2 | Headline metric for LAB-Bench | Accuracy. Precision and coverage are secondary. |
| ✅ D3 | Prompt setup | Decided (A.2): official for headline. Older anchor models are run both ways. |
| ⏳ D4 | GPQA biology subset | Main split, Biology domain, 78 items, matching the preprint |
| ✅ D5 | MMLU-Bio | Decided (C.3): pilot-only, then skipped if saturated (see G6) |
| ⏳ D6 | Saturation ceiling | 100%, unless a published label-error estimate exists for the benchmark |
| ✅ D7 | Expert baselines | Decided (A.3): SeqQA and DbQA raw only, no MMLU-Bio expert line. The others use the preprint's values (GPQA-Bio 66.7, LitQA2 70, CloningScenarios 60, ProtocolQA 79). |
| ⏳ D8 | "Knows vs does" split | **Knows:** GPQA-Bio, LitQA2, DbQA. **Does:** ProtocolQA, SeqQA, CloningScenarios. |
| ✅ D9 | Per-item release and licenses | Decided (A.4) |
| ⏳ D10 | LitQA2 and DbQA without tools | Keep them, with a methods-page caveat that they were designed for retrieval agents (see G1) |
| ✅ D11 | Seeds | Decided (C.2): one seed plus item-level bootstrap. A second seed only for the LAB-Bench headline, top 3. |
| ✅ D12 | LifeSciBench, MedChemBench, GeneBench | Decided (A.5): vendor table only |
| ✅ D13 | Flagship roster | Decided (B.1): Fable 5.1. Opus 5.5 later as mid-tier. |
| ⏳ D14 | Also run GPQA Diamond (198 items) as a validation-only check? | Yes, now about $41 at 1 seed, capped |
| ✅ D15 | Anchor re-runs of still-available preprint models | Decided (A.2): yes, both setups |

---

## E: Standards and independence

| ID | Question | Default |
|---|---|---|
| ✅ E1 | Conflict-of-interest policy | Decided (B.3): your wording, verbatim in `docs/methods.md` §2 (see G7) |
| ⏳ E2 | Disclose on the methods page that pipeline code was written with assistance from Claude (Anthropic, an evaluated provider)? | Yes |
| ⏳ E3 | Which providers to request credits from | All evaluated providers, same email and terms. Timing decided (C.10): before the full launch run. |
| ⏳ E4 | Corrections | A public `label_changes.json` with each release, plus a dated note on the methods page |

---

## F: Infrastructure

| ID | Question | Default |
|---|---|---|
| ⛔ F1 | Where the project lives locally | The folder picker was cancelled. Name a folder, or say "under Documents" and I'll create `~/Documents/techbio-benchmarks`. |
| ⏳ F2 | Where the daily job runs and where state lives | B: GitHub-hosted runners plus a private R2 bucket. Until M4, everything runs locally. |
| ⏳ F3 | How a paid arena run gets approved | A GitHub environment `paid` with you as required reviewer |
| ⏳ F4 | Commit `exports/latest` JSON to git? | Yes for the small JSON. Per-item files and CSVs go to release and HF only. |
| ⏳ F5 | Release cadence | A rolling `latest`, plus a monthly tag, each getting a Zenodo DOI |
| ⏳ F6 | HF dataset name | `<your-org>/techbio-benchmarks` |
| ⏳ F7 | Schema versioning | `v0` is unstable until launch, and `v1` is frozen at M4 |
| ✅ F8 | Install `uv` and `gh` | Done (D.5) |

---

## Data-source facts that shaped the design (no decision needed)

- **EDGAR full-text search** is undocumented, and it silently ignores `items=` and `sics=`. Discovery
  uses it with client-side filtering. The stable backbone is the per-CIK **submissions API**, which
  carries `items` and `sic`.
- **The FDA CRL dataset** exists (`api.fda.gov/transparency/crl.json`), but it's updated
  "infrequently" (last update 2026-08-13). CRLs resolve from the sponsor's 8-K or 6-K on decision
  day, and the FDA letter is attached later as a versioned update (A.6). Letter text never goes into
  an export.
- **Advisory committees** have no API. Meetings come from the **Federal Register API** (FDA notices).
  Votes come from sponsor filings, then from FDA minutes when they're posted.
- **Drugs@FDA** (daily zip, plus openFDA) confirms approvals. It retries on openFDA's frequent 500
  errors.
- **CT.gov v2** needs no auth and publishes no rate limit. We run at 1 req/s per its robots.txt.
