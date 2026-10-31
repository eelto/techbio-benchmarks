# Outcome taxonomy

Version: **v1** (operator-confirmed 2026-10-30, `docs/decisions.md` B.4). The scope and taxonomy
defaults (Q-A1–A7, Q-B1–B7) were accepted, with the operator's narrower void rule in §4. Items marked
**[flag]** are my reading of that rule where the wording leaves a case open. They are listed in §7
for confirmation, and the code implements them as written here.

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
| stopped / business (financing, strategic, acquisition) | **void** |
| stopped / operational (enrollment, supply, sites) | **void** [flag] |
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
| Trial stopped for a business reason (financing, strategic, acquisition) | **void** |
| Trial stopped for an operational reason (enrollment, supply, sites) | **void** [flag] |
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

For CRLs, the category records the sponsor's stated reason. If FDA has published the letter, the
CRL's own deficiencies are a separate label. The two often disagree, and that disagreement is
informative.

## 6. Who confirms outcomes

The operator confirms every outcome that is scored in the arena (Q-B7), including voids. It's one
keystroke when both extractors agree. No model alone decides a score that ranks models.

## 7. Flags for the operator

These are my readings of the void rule. The code implements them as written above until you say
otherwise.

1. **Operational stops → void.** "Unrelated to its outcome" seems to cover slow enrollment, drug
   supply, and site closures. But slow enrollment is sometimes a soft signal about the drug.
   Alternative: score them 0.
2. **A business stop that discloses topline data.** Under the rule as written it is void. But "anything
   resolved by data is scored" suggests scoring it on the data (met or missed) when the primary
   endpoint was reported. My recommendation: score on the data when primary-endpoint results are
   disclosed, and void only when there are none.
3. **Withdrawals.** Withdrawn for a financial or strategic reason → void. Otherwise 0, because
   withdrawal before action usually signals an expected CRL.
4. **`split` can no longer be void.** With one deciding question (B5), a split is a tie on it, which
   means no majority "yes", so it scores 0.
5. **AdCom held without a vote → void.** FDA increasingly holds discussion-only meetings. No vote
   means no outcome in the fixed taxonomy.
6. **A stop with no stated reason is never void.** The rule needs a stated non-outcome reason to
   void. If the subtype can't be assigned, you assign it in review. My recommendation is to treat
   unexplained stops as 0.

## 8. Adjudication log

_Empty. Entries look like: `2026-11-20 · evt_01J… · mixed vs missed · rule: … · reviewer`._
