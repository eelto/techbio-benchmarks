# Outcome taxonomy

Version: **v1.1** (operator-confirmed 2026-10-30). v1 (`docs/decisions.md` B.4) accepted the scope
and taxonomy defaults (Q-A1–A7, Q-B1–B7) with the operator's narrower void rule in §4. v1.1 (same
day, decisions T.1–T.5, after the first real CT.gov records) adds the business-stop rule, the
exclusions in §1, and the derived explanation category in §5. Nothing was scored under v1. Items
marked **[flag]** are my reading where the wording leaves a case open. They are listed in §7 for
confirmation, and the code implements them as written here.

After v1, this file grows only from adjudications, and each rule gets a date and an example
`event_id`. Every resolution stores the taxonomy version it was scored under. A change in mapping
re-scores past events under the new version and keeps the old scores.

## 1. Event types and inclusion

| event_type | Included when | date_type |
|---|---|---|
| `readout` | Topline primary-endpoint results of a Phase 2b or Phase 3 trial (including Phase 2/3) sponsored by a US-listed company. A Phase 2 trial counts as "2b" when it is randomized and controlled and either the sponsor calls it 2b, pivotal, or registrational, or it has N ≥ 100. | `fuzzy` if timing is guided ("mid-2027"). `dated` only if the sponsor names an exact date ahead of time. |
| `fda_decision` | FDA action on an NDA or BLA with a known goal date: novel products and new-indication supplements, from CDER and CBER. Generics, biosimilars, labeling-only supplements, and devices don't count. | `dated` (PDUFA or goal date) |
| `adcom` | FDA advisory committee meeting on a specific product. Meetings come from FDA notices in the Federal Register. | `dated` |
| `discontinuation` | The sponsor announces it is stopping development of an asset in an indication ("discontinue", "deprioritize", "no longer pursue", license returned). Ledger only, never selected for the arena (Q-A5). | `fuzzy` |

**Universe** (Q-A1, A2, A4): sponsors listed on Nasdaq, NYSE, or NYSE American, including ADRs and
large-cap pharma; OTC excluded. SIC 2834, 2835, 2836, or 8731, plus a curated add/drop list. Foreign
private issuers are included through 6-K. Ex-US trials of US-listed sponsors are included.

PDUFA goal-date extensions (for example, 3 months for a major amendment) do **not** resolve an event.
They update the expected date and are recorded as slip.

### Attribution: whose event it is (operator 2026-11-01, decision R.1)

One trial is one event, filed under the company that runs it:

| event_type | Filed under |
|---|---|
| `readout` | the trial's lead sponsor on ClinicalTrials.gov |
| `fda_decision`, `adcom` | the holder of the US application |
| `discontinuation` | the company that owns the program |

A partner's or licensee's statement about someone else's trial is not recorded under the partner. If
the company that runs the trial is in the universe, its own filings carry the event. If it is not,
the event is out of scope. The rule changes no mapping, so the scoring version stays v1.1.

A lead sponsor named on ClinicalTrials.gov as a wholly owned subsidiary counts as its parent. For
example, Zentalis's DENALI (NCT05128825) is led by "K-Group, Beta, Inc., a wholly owned subsidiary of
Zentalis Pharmaceuticals" and is filed under Zentalis.

Example: Zai Lab's 2026-08-06 release (`src_01M69MRD539ZP3RD10VQ33M8R2`) gives the expected timing
of topline results from ALKIVIA, argenx's Phase 2/3 trial of efgartigimod in myositis, for which Zai
Lab holds Greater China rights. It is not a Zai Lab event, and argenx's own filings carry it. No
event was created, so the example cites the source.

Each readout is checked against the registry before it reaches the ledger (`ledger/scope.py`, from
2026-11-02). The trial is found by NCT number or, failing that, by acronym; the sponsor's own trial
of that acronym comes first. If another company in the universe leads it and it tests the
statement's asset (named in its interventions or title), the statement is dropped and recorded as a
closed `scope_check` item on `sponsor_id`. Otherwise, including when there is no registry record,
the extractors' reading stands.

### Phase 2: what counts as 2b (operator 2026-11-01, decision R.2)

"Controlled" means the trial has a comparator arm: placebo, sham, an active drug, standard of care,
or no treatment. Randomizing patients between doses or schedules of one drug is not a control. A
single-arm or dose-comparison Phase 2 is out of scope even when the sponsor calls it registrational
or pivotal. The reason is that "met" for such a trial needs a success threshold sponsors rarely
publish, so most would end in the review queue. If such a trial leads to a filing, the FDA decision
is still in scope as an `fda_decision` event.

Each Phase 2 readout is checked against the registry before it reaches the ledger
(`ledger/scope.py`):

- **Dropped:** the registry shows Phase 1/2, no randomization, or fewer than 100 patients for a
  trial that is not called 2b, pivotal, or registrational. The drop is recorded as a closed
  `scope_check` item.
- **Sent to the operator:** the trial passes those checks but the registry does not confirm a
  control. A placebo, sham, or no-treatment arm, or a comparison in the title, confirms one. The registry cannot rule a control out, because
  sponsors often label an active-comparator arm "experimental". A plain "Phase 2" with no registry
  record is also sent.
- **Kept on the extractors' reading:** a "2b" with no registry record.

Examples:

- Zentalis's 2026-05-05 release (`src_01M69MYHB9G51QSZ36V6NZP674`) gives the year-end readout timing
  for DENALI Part 2. DENALI is registration-intended, but it randomizes patients between two doses of
  azenosertib and has no control arm, so it is out. No event was created.
- Agios's tebapivat studies (`src_01M69KQN51K0HMQFBC5MNKZJ1A`) are out too. The LR-MDS study
  (NCT05490446) is not randomized, and the sickle cell study (NCT06924970) enrolls 59 patients and is
  not called 2b. Both events were removed on the next run.

### Not events: exclusions (v1.1, operator 2026-10-30)

A registry record that never had a chance to read out is not an event. It is recorded in
`exclusions` with its reason and exported in `exclusions.csv`. Any open event that turns out to
belong to that trial is closed with status `excluded` (a `deterministic` label records why).

| Case | Rule | Example |
|---|---|---|
| Withdrawn before enrollment (CT.gov `WITHDRAWN`, or `TERMINATED`/`SUSPENDED` with an actual enrollment of 0) | not an event; `withdrawn_before_enrollment` | NCT05951205 (Vertex, Phase 3 exa-cel, withdrawn, 0 enrolled: "Modification to the clinical development plan") |
| Withdrawn citing another trial's data | not an event; `withdrawn_citing_other_trial`, linked to the cited trial (and through it to that trial's event) | NCT06598631 (Lilly, Phase 2 volenrelaxin in CKD, withdrawn, 0 enrolled, citing "a related heart failure study that demonstrated no benefit"; the cited trial is NCT05592275, LY3540378 in HFpEF, terminated after an interim) |

A record that names the cited trial's NCT number is linked by the parser. One that describes it only
in words goes to the review queue (`exclusion_link`), and the operator picks the trial; "cites no
trial" reclassifies it as withdrawn before enrollment. A withdrawn record shows 0 enrolled, so its
planned size is unknown: a withdrawn randomized Phase 2 is treated as in scope for this check (it can
only become an exclusion, never an event).

## 2. Result categories (fixed) and definitions

### Readouts

| Category | Definition |
|---|---|
| `met` | The pre-specified primary endpoint reached statistical significance, or the pre-specified success criterion for non-inferiority or single-arm designs. With co-primary endpoints, all of them. With multiple doses under pre-specified multiplicity control, at least one dose intended for registration. |
| `missed` | The primary endpoint did not meet its success criterion. |
| `mixed` | At least one but not all of the elements the sponsor pre-specified as primary succeeded. That covers co-primary endpoints, two pivotal trials reported together, or two primary analysis populations. It does *not* cover "met primary, missed secondaries", which is `met`. |
| `stopped` | The trial ended before the planned topline. A subtype is recorded: `efficacy`, `futility`, `safety`, `business` (financing, strategic, acquisition), `operational` (enrollment, supply, site problems). |

### FDA decisions

| Category | Definition |
|---|---|
| `approved` | Any approval: full or accelerated, a narrower label, or approval with a REMS or boxed warning. |
| `CRL` | A Complete Response Letter was issued. |
| `withdrawn` | The sponsor withdrew the application after acceptance and before action. |

**CRL resolution:** a CRL resolves from the sponsor's 8-K, 6-K, or press release on decision day,
which is a primary source. When FDA later publishes the letter (openFDA CRL dataset), it is attached
as a new label version on the event: a versioned update that never changes the outcome or its
original timestamp. The letter's deficiencies are recorded as a separate label next to the sponsor's
stated reason (§5).

### Advisory committee votes

| Category | Definition |
|---|---|
| `favorable` | A majority voted "yes" on the deciding question: the committee's primary benefit-risk question, or the primary efficacy question if there is no benefit-risk question. Abstentions are excluded from the count. |
| `unfavorable` | A majority voted "no" on the deciding question. |
| `split` | A tie on the deciding question. |

**Fixed rule.** A readout that missed its primary endpoint but later led to approval is `missed` at
the readout event and `approved` at the decision event. The two are separate events and are never
linked for scoring.

## 3. Mapping outcomes to binary for scoring

| Outcome | Scored as |
|---|---|
| met | 1 |
| missed | 0 |
| mixed | 0 (conservative: "success" means the primary succeeded cleanly) |
| stopped / efficacy | 1 |
| stopped / futility | 0 |
| stopped / safety | 0 |
| stopped / business (financing, strategic, acquisition), no data trigger documented | **void** (v1.1) |
| stopped / business, with a documented data trigger (interim analysis, futility analysis, DSMB recommendation) | 0, scored as `missed` (v1.1) |
| stopped / operational (enrollment, supply, sites) | **void** (operator-confirmed 2026-10-30) |
| approved | 1 |
| CRL | 0 |
| withdrawn | 0, unless the sponsor's stated reason is `financial` or `strategic_portfolio`, then **void** [flag] |
| favorable | 1 |
| unfavorable | 0 |
| split | 0 (no majority "yes" on the deciding question) [flag] |

## 4. Void rule (operator-confirmed, narrow and public)

> An event is voided only if it is cancelled or the trial is stopped for reasons unrelated to its
> outcome (financing, strategic, acquisition). Anything resolved by data is scored.

How the code applies it:

| Case | Result |
|---|---|
| Event cancelled: AdCom cancelled, or a decision event whose application never reaches action for a reason unrelated to its data | **void** |
| Trial stopped for a business reason (financing, strategic, acquisition) after enrollment, with no data trigger documented | **void** for endpoint scoring (v1.1). Example: NCT04396236 (Lilly, Phase 3 lasmiditan in pediatric migraine, 847 enrolled, "strategic business decision"). |
| The same, but the primary source documents a data trigger (interim analysis, futility analysis, DSMB recommendation) | **scored 0 as `missed`** (v1.1). The trigger is the reserved field `stop_data_trigger`. |
| Trial stopped for an operational reason (enrollment, supply, sites) | **void** (confirmed 2026-10-30). Example: NCT05074420 (Lilly, Phase 3 baricitinib in pediatric COVID-19, 6 enrolled, "inability to enroll participants"). |
| Application withdrawn for a financial or strategic reason | **void** [flag] |
| AdCom held but no vote taken (discussion-only meeting) | **void** [flag] |
| Trial stopped and the sponsor gives no reason (`not_disclosed`) | **never void.** Scored by its subtype. If no subtype can be assigned from a primary source, it goes to the human queue and the operator assigns one. [flag] |
| Any other outcome that data resolved | scored per §3 |

- Every voided event appears in the exports with `void_reason` (one of the cases above, plus the
  primary source).
- Void is decided by the reason the primary source states, at the time of resolution. A void is a
  label like any other: versioned, sourced, and confirmed by the operator.
- **Separately**, a *forecast* is void under the commitment rule when its event resolved before the
  round's commitment timestamp. That is a forecast-level void, counted and reported, and it doesn't
  change the event's outcome.

## 5. Sponsor-explanation category

This is a reserved field, so it is human-adjudicated on disagreement. It applies to discontinuations,
`missed`, `stopped`, `CRL`, and `withdrawn`:

`efficacy` · `safety` · `regulatory_feedback` · `manufacturing_cmc` · `strategic_portfolio` ·
`financial` · `partner_decision` · `enrollment_operational` · `not_disclosed`

**Derived category (v1.1): `strategic_stop_after_enrollment`.** Every trial stopped for a business
reason gets this category in its resolution, whether it is void or scored as missed, together with
the enrolled-patient count (CT.gov actual enrollment, `enrolled_at_stop`). All such stops are after
enrollment, because trials withdrawn before enrollment are not events (§1). The extractors never
assign it: they record the sponsor's stated reason (kept as `stated_explanation_category`), and the
ledger derives the category. The refresh summary reports the count, how many were void and how many
were scored, the total patients enrolled, and how many have no linked registry count. The operator's
rationale: a "strategic" stop after hundreds of patients is often a data decision described as a
business one, and the pattern is a finding in itself.

For CRLs, the category records the sponsor's stated reason. If FDA has published the letter, the
CRL's own deficiencies are a separate label. The two often disagree, and that disagreement is
informative.

## 6. Who confirms outcomes

The operator confirms every outcome that is scored in the arena (Q-B7), including voids. It's one
keystroke when both extractors agree. No model alone decides a score that ranks models.

## 7. Flags for the operator

These are my readings of the void rule. The code implements them as written above until you say
otherwise.

1. ~~Operational stops → void.~~ **Confirmed by the operator, 2026-10-30.**
2. ~~A business stop that discloses topline data.~~ **Decided 2026-10-30 (v1.1):** void unless a data
   trigger is documented, then scored as missed; always logged as `strategic_stop_after_enrollment`.
3. **Withdrawals.** Withdrawn for a financial or strategic reason → void. Otherwise 0, because
   withdrawal before action usually signals an expected CRL.
4. **`split` can no longer be void.** With one deciding question (B5), a split is a tie on it, which
   means no majority "yes", so it scores 0.
5. **AdCom held without a vote → void.** FDA increasingly holds discussion-only meetings. No vote
   means no outcome in the fixed taxonomy.
6. **A stop with no stated reason is never void.** The rule needs a stated non-outcome reason to
   void. If the subtype can't be assigned, you assign it in review. My recommendation is to treat
   unexplained stops as 0.
7. **New (v1.1): a trial stopped after enrollment citing another trial's results.** For example,
   "terminated following the negative results of the sister study". It is an event (it enrolled), but
   its own data didn't decide the stop. My reading: void, and link it to the cited trial, as for the
   withdrawn case. Until you decide, the extractors and review assign it a subtype as usual.
8. **New (v1.1): a business stop after a *positive* interim.** T.1 scores a documented data trigger
   as missed. If the sponsor reports the interim as a success (for example, an acquirer stops a trial
   that was working), my reading is that the stop subtype is `efficacy` (scored 1), not business, so
   the missed rule doesn't apply. The extraction prompt says to use the reason the document gives.
9. **New (v1.1): suspended trials.** CT.gov `SUSPENDED` (often a clinical hold) is currently treated
   like a stop, so a hold could resolve a readout as stopped/safety (0) even though the trial may
   resume. My recommendation: a suspension does not resolve the event; it is recorded and the event
   stays open until the trial is terminated or the readout happens.

## 8. Adjudication log

Entries look like: `2026-11-20 · evt_01J… · mixed vs missed · rule: … · reviewer`. Rules decided
before the first events existed cite the registry record; the event ID is added when it is created.

- `2026-10-30 · NCT04396236 (event ID on ingestion) · business stop after enrollment · rule T.1: void unless a data trigger is documented, then missed; category strategic_stop_after_enrollment with enrolled count (847) · operator`
- `2026-10-30 · NCT05951205 · withdrawn, 0 enrolled · rule T.2: not an event, exclusion withdrawn_before_enrollment · operator`
- `2026-10-30 · NCT06598631 · withdrawn citing another trial (NCT05592275) · rule T.3: not an event, exclusion linked to the cited trial · operator`
- `2026-10-30 · NCT05074420 · stopped for failure to enroll (6 enrolled) · rule T.4: void, operational (confirmed) · operator`
- `2026-11-01 · src_01M69MRD539ZP3RD10VQ33M8R2 (no event) · a partner's mention of its licensor's trial (Zai Lab on argenx's ALKIVIA) · rule R.1: filed under the trial's lead sponsor, never the partner · operator`
- `2026-11-01 · src_01M69MYHB9G51QSZ36V6NZP674 (no event) · registration-intended single-drug Phase 2 with no control arm (Zentalis's DENALI, NCT05128825) · rule R.2: not 2b, out of scope; the FDA decision on any filing stays in scope · operator`
