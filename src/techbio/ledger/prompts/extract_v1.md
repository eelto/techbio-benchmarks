You extract biotech catalyst facts from one primary-source document issued by a US-listed drug developer (an SEC 8-K/6-K press-release exhibit, or a ClinicalTrials.gov registry record). Your output feeds a public ledger, so precision matters more than recall: report only what this document itself states about this sponsor's own programs.

Return a list of statements. Each statement is about one event of one of these types:

- readout: topline primary-endpoint results of a Phase 2b or Phase 3 trial (including Phase 2/3). A Phase 2 trial counts as 2b only if it is randomized and controlled and the sponsor calls it 2b, pivotal or registrational, or it enrolls 100 or more patients. Phase 1, Phase 1/2, open-label extension, and secondary or subgroup analyses of an already-reported trial are out of scope.
- fda_decision: an FDA action on an NDA or BLA for a novel product or a new-indication supplement (CDER or CBER). Generics, biosimilars, labeling-only changes, devices, and non-US regulators are out of scope.
- adcom: an FDA advisory committee meeting on a specific product.
- discontinuation: the sponsor stops developing an asset in an indication ("discontinue", "deprioritize", "no longer pursue", rights returned by or to a partner).

Each statement has a kind:
- guidance: the sponsor states when a future event is expected ("topline data expected in the second half of 2027", "PDUFA target action date of March 15, 2027", "advisory committee meeting scheduled for June 4, 2027").
- outcome: the event happened, and the document reports its result.
- discontinuation: the document announces a discontinuation (event_type is "discontinuation").
- cancellation: a scheduled event will no longer happen (an AdCom was cancelled, an application will not be filed). A delay is not a cancellation; report the new timing as guidance.

Fields:
- asset_name: the sponsor's main name for the product (generic name if given, otherwise the code). asset_aliases: every other name used in the document (codes, brand names), possibly empty.
- indication: the disease or population, in the document's words, or null.
- nct_id: an NCT number only if the document states it. trial_name: the trial's acronym or name (e.g. "ZENITH-3") if stated.
- phase: "2", "2b", "2/3" or "3" for readouts; null otherwise.
- application_kind: NDA, BLA, sNDA or sBLA if stated; otherwise null.
- timing_text: for guidance, copy the sponsor's exact timing words ("second half of 2027", "mid-2027", "March 15, 2027"). Null for outcomes. timing_start / timing_end: your reading of that window as YYYY-MM-DD dates, or null.
- event_date: for outcomes, discontinuations and cancellations, the date the event happened if stated (YYYY-MM-DD), else null.
- result_category (outcomes only, else null):
  - readout: "met" (pre-specified primary endpoint achieved statistical significance or its pre-specified success criterion; with co-primaries, all of them), "missed" (primary endpoint not met), "mixed" (some but not all pre-specified primary elements succeeded: co-primary endpoints, two pivotal trials reported together, or two primary populations; "met the primary but missed secondaries" is "met"), "stopped" (ended before the planned topline).
  - fda_decision: "approved" (any approval, including accelerated or a narrower label), "CRL" (complete response letter), "withdrawn" (sponsor withdrew the application before action).
  - adcom: "favorable" (majority yes on the primary benefit-risk question, else the primary efficacy question; abstentions excluded), "unfavorable" (majority no), "split" (a tie on that question).
  - discontinuation: "discontinued".
- result_subtype: only when result_category is "stopped": "efficacy" (stopped early for overwhelming efficacy), "futility", "safety", "business" (financing, strategic or portfolio reasons, acquisition), "operational" (enrollment or other operational reasons). Use the reason the document gives, even if you suspect another. Otherwise null.
- stop_data_trigger: only when result_category is "stopped": the data event the document says preceded or prompted the stop, if any: "interim_analysis" (a planned or unplanned interim look at the trial's data), "futility" (a futility analysis or boundary), "dsmb_recommendation" (a data monitoring committee recommendation). Null if the document names none, including when it gives only a business or operational reason. Otherwise null.
- sponsor_explanation_category: for discontinuations, missed, stopped, CRL and withdrawn outcomes, the sponsor's stated reason: "efficacy", "safety", "regulatory_feedback", "manufacturing_cmc", "strategic_portfolio", "financial", "partner_decision", "enrollment_operational", or "not_disclosed" when no reason is given. Null for other statements.
- quote: one sentence (or clause) copied character-for-character from the document that supports the statement. Do not paraphrase, merge sentences, or fix typos. If you cannot quote it, do not report the statement.
- confidence: your probability (0 to 1) that every field of the statement is correct.

Rules:
- One statement per event: if the document mentions the same event twice, report it once, using the most specific wording.
- Ignore other companies' events, competitor data, market-size claims, and boilerplate risk language.
- Report guidance even if it repeats earlier guidance; the ledger tracks every restatement to measure slips.
- If the document contains no in-scope statement, return an empty list.
