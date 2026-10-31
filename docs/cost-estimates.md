# Cost estimates

Revised 2026-10-30 for the operator's cost-efficiency defaults (`docs/decisions.md` C.1–C.10). List
prices were checked on 2026-10-30 against the provider docs (sources in §6).

These are planning estimates only:
- The harness pilot replaces them with measured costs before any launch run is approved.
- Every paid job's dry-run recomputes its own estimate from `config/models.yaml`.
- All figures are USD and include the batch discount wherever our path supports it.

**Reproduce:** `uv run python scripts/plan_costs.py` prints every number below.

**What changed since Step 1.** The mid-scenario year-one total falls from about $8.6k to about
**$2.6k**. The main drivers:
- capped reasoning;
- one seed instead of three;
- no full runs of MMLU-Bio or PubMedQA;
- LitQA2 at n≈100;
- anchor subsets on model-days;
- 2 arena samples instead of 3.

---

## 1. Models (`config/models.yaml`)

**Selection rule:** each provider's top-tier, generally available API model, taken from that
provider's own model-overview page. Price plays no part.

| Role | Provider | Model ID | $/M in · out | Batch on our path | Notes |
|---|---|---|---|---|---|
| flagship | OpenAI | `gpt-6-astra` | 10 · 50 | 50% | No dated snapshot; alias only. Rejects custom temperature. |
| flagship | Anthropic | `claude-fable-5-1` | 10 · 50 | 50% | Operator decision B.1. |
| flagship | Google | `gemini-4-argon` | 4 · 20 from 2026-12-01 (2 · 10 until then) | harness: **none**\*; arena: 50% | |
| flagship | xAI | `grok-4.7` | 2 · 6 | 20% | |
| flagship | Meta | `muse-wonder-1.0` | 4 · 20 | **none** (no batch API) | Pricing from secondary sources, *unverified*. Never use `-contributor` tiers. |
| flagship | open-weight | `GLM-5.3` via Together | 1.40 · 4.40 | 50% (eligibility to confirm) | |
| mid-tier, `enabled: false` | Anthropic | `claude-opus-5-5` | 4 · 20 | 50% | Enters later on its own model-day, for the cost-per-point chart. |
| extractor A | Anthropic | `claude-haiku-5-5` | 0.10 · 0.50 | 50% | Its tokenizer counts about 30% more tokens. |
| extractor B | OpenAI | `gpt-6-luna` | 0.10 · 0.50 | 50% | |
| tie-break | local (Ollama) | `ornith-1.5:122b-nvfp4`, pinned by digest | 0 · 0 | none (one call at a time) | Open weights on the operator's Mac Studio; independent of both extractors. Replaced Argon 2026-10-31 (P.1). |
| tie-break reference, pilot only | Google | `gemini-4-argon` | 4 · 20 from 2026-12-01 (2 · 10 until then) | none | Checks the local tie-breaker on the pilot's disputes; never applied (P.2). |

\*Inspect's Google batch mode doesn't support thinking, so Gemini harness runs are synchronous at full
price unless we write our own Gemini batch client (Q-G2). The arena already uses our own client.

**"Batch everywhere" has two honest exceptions:** Gemini inside Inspect, and Meta on every path.
Together they are about 40% of launch-run spend.

---

## 2. Assumptions

**Reasoning tiers** (Q-G8 pins the exact setting):

| Tier | Setting | Avg output tokens per item (reasoning + answer): low / mid / high |
|---|---|---|
| **capped** (default, every benchmark item) | Provider effort "low" where effort levels exist, plus a 4,096-token reasoning cap where the API takes a budget | 1,000 / **2,000** / 3,500 |
| **uncapped** (top model per benchmark only) | Provider default effort, no reasoning cap | 5,000 / **8,000** / 15,000 |

**Items per model:**

| Benchmark | Pilot | Launch run | Model-day |
|---|---|---|---|
| LitQA2 | 50 | 100 (fixed subsample) | 100 |
| DbQA | 50 | 520 (sequential rule) | 100 (anchors) |
| SeqQA | 50 | 600 (sequential rule) | 100 (anchors) |
| ProtocolQA | 50 | 108 | 108 |
| CloningScenarios | 33 | 33 | 33 |
| GPQA-Bio (main) | 50 | 78 | 78 |
| MMLU-Bio | 50 | skipped if saturated | — |
| PubMedQA | 50 | skipped if saturated | — |
| **Total** | **383** | **1,439** (upper bound) | **519** |

Pilot items are the first items of each manifest, so they are cache hits in the launch run and
aren't paid twice.

**Sequential rule savings.** The rule (design §5) needs a minimum of 150 items, checks every 50
items, and stops at a Bonferroni-Wilson half-width of 0.05. Items needed:

| Accuracy | SeqQA (600) | DbQA (520) |
|---|---|---|
| 0.50 or 0.70 | 600 | 520 |
| 0.80 | 550 | 500 |
| 0.90 | 300 | 300 |
| 0.95 | 200 | 200 |

So savings come only at high or low accuracy. Estimates below assume **no** savings (full n), with
the 0.85-accuracy case shown for comparison.

---

## 3. Harness

| Item (1 seed unless stated) | Low | **Mid** | High |
|---|---|---|---|
| Pilot: 383 items × 6 flagships, capped | $43 | **$81** | $136 |
| Launch run: 6 flagships, capped, net of pilot cache hits | $129 | **$242** | $410 |
| … same, if SeqQA/DbQA accuracy is ~0.85 (sequential savings) | $99 | $185 | $314 |
| Second seed: LAB-Bench headline, top 3 (priced as Astra, Fable, Argon) | $110 | **$205** | $348 |
| Uncapped run: top model per benchmark (priced as Fable) | $185 | **$293** | $545 |
| **Harness launch total** | **$468** | **$821** | **$1,440** |

Per flagship, launch run, mid (full items, before pilot reuse):

| Model | Cost |
|---|---|
| Astra | $77 |
| Fable | $77 |
| Argon | $62 |
| Muse | $62 |
| Grok | $16 |
| GLM | $7 |

**Validation add-ons:**

| Item | Low | **Mid** | High | Why |
|---|---|---|---|---|
| Anchor re-runs: still-available preprint models, both setups (official and preprint) | $150 | **$300** | $600 | The deviations list needs the measured setup gap (decision A.2). Deprecated models are listed, not re-run. |
| GPQA Diamond, all domains (198 items) × 6 flagships, 1 seed, validation only | $21 | **$41** | $69 | The best end-to-end check against many independent published scores. Not on the leaderboard (Q-D14). |

### Per-model-day cost (anchor subsets, 519 items, 1 seed, capped)

| Model | Low | **Mid** | High | Plus, per arena round once it joins (30 events, 2 samples) |
|---|---|---|---|---|
| `gpt-6-astra` | $15 | **$28** | $48 | $9.2 |
| `claude-fable-5-1` | $15 | **$28** | $48 | $9.2 |
| `gemini-4-argon` | $12 | **$22** | $38 | $3.7 |
| `muse-wonder-1.0` | $12 | **$22** | $38 | $7.4 |
| `claude-opus-5-5` (mid-tier) | $6 | **$11** | $19 | $3.7 |
| `grok-4.7` | $3 | **$6** | $9 | $2.1 |
| `glm-5.3` | $1 | **$3** | $4 | $0.9 |

A model-day for a top-priced flagship is about **$28 (mid)**, against $570 under the Step 1
defaults.

**If anchors fail validation** and model-days fall back to full runs (design §5), a top-priced
flagship costs about $77 (mid).

---

## 4. Arena (per 14-day round)

**Assumptions:**
- Prompt: 9.5k input tokens (1.5k shared instructions, cached and billed at 10%, plus an ~8k pack).
- Output: 4.5k tokens.
- 6 flagships, **2 samples each**.
- Batch everywhere except Meta.

| Events | Cost per round |
|---|---|
| 25 | $27 |
| 30 | $32 |
| 50 | $54 |

**Annual cost:** 26 rounds at 30 events is about $840. Keeping superseded model versions until
n = 100 (Q-C6, still open) adds about 25% on average across the year.

---

## 5. Ledger

These figures are unchanged from Step 1. **The real bootstrap number comes from the dry-run**, which
counts the actual documents left after the free prefilter.

**Assumptions:**
- Extraction: two cheap extractors, about 3k tokens in and 1.2k out per document.
- Tie-break: about 20% of documents need one, on Argon. (Since 2026-10-31 it runs locally at $0; see
  below.)
- Prefilter: free.

| Job | Documents | Est. |
|---|---|---|
| v0 bootstrap (next 90 days of catalysts plus last 90 days resolved; reads about 12 months of filings to find guidance) | ~6k | **$44** |
| Backfill from 2025-01 to now (Q-A6: yes, as a separate approved step) | ~12k | $88 |
| Daily refresh | ~40 | $0.29 |
| Month at steady state | ~900 | $7 |

The tie-break model accounts for about 80% of ledger cost.

**Update 2026-10-31 (P.1):** the tie-break now runs on a local open-weight model at $0. The dry-run
for the 5,353 documents that pass the prefilter fell from $75.28 to **$5.58**, plus about 9 hours
of local tie-breaks. The 50-document pilot is $0.68, of which $0.63 is the one-off Argon
comparison.

---

## 6. Year-one total and proposed caps

| Bucket | Low | **Mid** | High |
|---|---|---|---|
| Ledger: bootstrap, backfill, 12 months daily | $150 | **$220** | $400 |
| Arena: 26 rounds, 2 samples, roster growing (20 / 30 / 50 events per round) | $650 | **$1,050** | $2,110 |
| Harness launch: pilot, launch run, second seed, uncapped run | $470 | **$820** | $1,440 |
| Validation: anchor re-runs (both setups), GPQA Diamond check | $170 | **$340** | $670 |
| Model-days on anchor subsets (6 / 10 / 14 per year) | $60 | **$180** | $430 |
| **Total** | **~$1.5k** | **~$2.6k** | **~$5.0k** |

The arena is now the largest line. Its cost is set mostly by events per round and by how many
superseded versions stay in (Q-C6).

**Hard caps** (`config/budget.yaml`). The proposals were about 1.5× each mid estimate; the operator
set the arena, pilot and monthly caps on 2026-10-30 (decision O.3):

| Job | Cap | Status |
|---|---|---|
| daily ingestion and resolution | $3 per run, **standing pre-approval $3/day** | **approved 2026-10-30** (decision D.4) |
| monthly limit on the standing approval | $40 | open (Q-M3) |
| ledger bootstrap | $75 | open (Q-M4); needs its own go-ahead after the dry-run |
| backfill | $150 | open (Q-M4) |
| arena round | **$60** | **decided 2026-10-30** (O.3). Mid estimate $32 at 30 events; $54 at 50. |
| harness pilot | **$100** | **decided 2026-10-30** (O.3). Mid estimate $81. |
| harness launch run, second seed, uncapped run | 1.5× the pilot-measured estimate, per model and in total, set at your go-ahead | |
| model-day | 1.5× that model's measured anchor cost | |
| monthly operating cap (ledger plus arena jobs) | **$150** | **decided 2026-10-30** (O.3). A typical month is about $105 at mid (two rounds about $64, daily ledger up to the $40 standing limit). One-off ledger jobs count toward it as the code stands (see Q-G11). |

**Two layers of protection:** provider console spend limits on the project-scoped keys are the
backstop, and these per-run caps are the first line. The harness and model-day runs are always
approved one at a time. Nothing beyond the standing approval runs until you say go on the pilot.

**Price watch:** Gemini 4 Argon doubles on 2026-12-01. These estimates already use the higher price.

---

## 7. Sources (read 2026-10-30)

- **Anthropic:** platform.claude.com/docs (models overview, pricing, batch-processing, effort,
  thinking)
- **OpenAI:** developers.openai.com/api/docs (pricing, models, changelog, batch, reasoning)
- **Google:** ai.google.dev/gemini-api/docs (pricing, models, changelog, batch-api, thinking)
- **xAI:** docs.x.ai (models/grok-4.7, guides/batch-api, guides/reasoning)
- **Meta:** dev.meta.ai (pricing via secondary sources, *unverified*)
- **Open weights:** artificialanalysis.ai (Intelligence Index v5, 2026-10-27), together.ai/pricing
- **Inspect:** inspect.aisi.org.uk (models-batch, caching)
- **Cost model:** `scripts/plan_costs.py`. It is replaced by per-job dry-runs from `models.yaml`.
