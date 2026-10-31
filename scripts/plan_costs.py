"""Planning cost model for techbio-benchmarks (docs/cost-estimates.md).

List prices checked 2026-10-30. Planning only: every paid job's dry-run recomputes its own estimate
from config/models.yaml, and the harness pilot replaces these numbers with measured ones.

    uv run python scripts/plan_costs.py
"""

from math import ceil, sqrt
from statistics import NormalDist

# $ per 1M tokens (input, output), and the batch multiplier on each path (1.0 = synchronous).
MODELS = {
    #                    in     out   harness  arena
    "gpt-6-astra":      (10.0, 50.0, 0.5, 0.5),
    "claude-fable-5-1": (10.0, 50.0, 0.5, 0.5),
    "gemini-4-argon":   (4.0, 20.0, 1.0, 0.5),  # Dec-1 price. Inspect's Gemini batch can't do thinking.
    "grok-4.7":         (2.0, 6.0, 0.8, 0.8),
    "muse-wonder-1.0":  (4.0, 20.0, 1.0, 1.0),  # Meta has no batch API.
    "glm-5.3":          (1.40, 4.40, 0.5, 0.5),  # via Together
    "claude-opus-5-5":  (4.0, 20.0, 0.5, 0.5),  # mid-tier, enters later (cost-per-point chart)
}
FLAGSHIPS = ["gpt-6-astra", "claude-fable-5-1", "gemini-4-argon", "grok-4.7", "muse-wonder-1.0", "glm-5.3"]
# Second seed and the uncapped delta run are priced on the most expensive models (conservative).
TOP3_ASSUMED = ["gpt-6-astra", "claude-fable-5-1", "gemini-4-argon"]
TOP1_ASSUMED = "claude-fable-5-1"

# benchmark: (items in the launch run, avg input tokens incl. template, LAB-Bench?)
LAUNCH = {
    "LitQA2 (n=100 subsample)": (100, 450, True),
    "DbQA": (520, 450, True),
    "SeqQA": (600, 1000, True),
    "ProtocolQA": (108, 900, True),
    "CloningScenarios": (33, 2700, True),
    "GPQA-Bio (main)": (78, 550, False),
}
PILOT_ONLY = {"MMLU-Bio": (50, 400), "PubMedQA": (50, 600)}  # saturation check, then skipped
PILOT_N = 50
GPQA_DIAMOND = (198, 550)  # validation only, never on the leaderboard
SEQUENTIAL = {"DbQA", "SeqQA"}  # benchmarks with > 200 items
ANCHOR_N = 100  # anchor subset size on model-days, for benchmarks with > 150 items

# Output tokens per item (reasoning + answer). Capped = the documented low/medium setting with a
# 4,096-token reasoning cap where the API has a budget. Uncapped = provider default, no cap.
CAPPED = {"low": 1000, "mid": 2000, "high": 3500}
UNCAPPED = {"low": 5000, "mid": 8000, "high": 15000}

# Arena: per forecast call. 1.5k shared instructions (cached, billed at 10%), ~8k pack, 4.5k out.
ARENA_IN_SHARED, ARENA_IN_PACK, ARENA_OUT = 1500, 8000, 4500
ARENA_SAMPLES = 2


def call_cost(model, tin, tout, path="harness", cached_in=0):
    pin, pout, b_h, b_a = MODELS[model]
    b = b_h if path == "harness" else b_a
    return ((tin - cached_in) * pin + cached_in * pin * 0.1 + tout * pout) / 1e6 * b


def items_cost(model, n, tin, tout_per_item):
    return call_cost(model, n * tin, n * tout_per_item)


# ---- sequential stopping (spec: docs/design.md §5) --------------------------------------------
def checkpoints(n_total, first=150, step=50):
    cps = list(range(first, n_total, step))
    return cps + [n_total]


def stop_n(n_total, p, half_width=0.05):
    """Items needed when true accuracy is p, using the Bonferroni-adjusted Wilson half-width."""
    cps = checkpoints(n_total)
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * len(cps)))
    for n in cps:
        denom = 1 + z * z / n
        hw = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        if hw <= half_width:
            return n
    return n_total


# ---- harness ----------------------------------------------------------------------------------
def pilot(scen):
    tout = CAPPED[scen]
    tot = 0.0
    for m in FLAGSHIPS:
        for n, tin, _ in LAUNCH.values():
            tot += items_cost(m, min(n, PILOT_N), tin, tout)
        for n, tin in PILOT_ONLY.values():
            tot += items_cost(m, n, tin, tout)
    return tot


def launch_items(name, n, p_seq):
    return stop_n(n, p_seq) if (p_seq is not None and name in SEQUENTIAL) else n


def launch(scen, p_seq=None, incremental=True):
    """1 seed, 6 flagships. Pilot items are cache hits when incremental=True."""
    tout = CAPPED[scen]
    per = {}
    for m in FLAGSHIPS:
        c = 0.0
        for name, (n, tin, _) in LAUNCH.items():
            k = launch_items(name, n, p_seq)
            if incremental:
                k -= min(k, PILOT_N)
            c += items_cost(m, k, tin, tout)
        per[m] = c
    return sum(per.values()), per


def second_seed(scen, p_seq=None):
    tout = CAPPED[scen]
    return sum(
        items_cost(m, launch_items(name, n, p_seq), tin, tout)
        for m in TOP3_ASSUMED
        for name, (n, tin, lab) in LAUNCH.items()
        if lab
    )


def uncapped_delta(scen, p_seq=None):
    tout = UNCAPPED[scen]
    return sum(
        items_cost(TOP1_ASSUMED, launch_items(name, n, p_seq), tin, tout)
        for name, (n, tin, _) in LAUNCH.items()
    )


def gpqa_diamond(scen):
    n, tin = GPQA_DIAMOND
    return sum(items_cost(m, n, tin, CAPPED[scen]) for m in FLAGSHIPS)


def model_day_items():
    return {
        name: (ANCHOR_N if n > 150 else n, tin) for name, (n, tin, _) in LAUNCH.items()
    }


def model_day(model, scen):
    return sum(items_cost(model, k, tin, CAPPED[scen]) for k, tin in model_day_items().values())


# ---- arena ------------------------------------------------------------------------------------
def arena_round(events, models=FLAGSHIPS, samples=ARENA_SAMPLES):
    tin = ARENA_IN_SHARED + ARENA_IN_PACK
    return sum(
        call_cost(m, events * tin, events * ARENA_OUT, "arena", cached_in=events * ARENA_IN_SHARED)
        for m in models
    ) * samples


def arena_per_model_round(model, events, samples=ARENA_SAMPLES):
    return arena_round(events, [model], samples)


# ---- ledger (unchanged from Step 1; the real bootstrap number comes from the dry-run) ----------
def extract(docs, tin=3000, tout=1200, tiebreak_frac=0.2):
    cheap = 2 * docs * (tin * 0.10 + tout * 0.50) / 1e6 * 0.5 * 1.3  # +30% Haiku tokenizer slack
    tb = docs * tiebreak_frac * (tin * 4.0 + 2500 * 20.0) / 1e6 * 0.5
    return cheap + tb


# ---- year one ---------------------------------------------------------------------------------
YEAR = {  # low, mid, high
    "events_per_round": (20, 30, 50),
    "roster_growth": (1.15, 1.25, 1.5),  # average model-versions vs launch six (superseded kept, Q-C6)
    "model_days": (6, 10, 14),  # flagship releases + mid-tier entries per year
    "anchor_reruns": (150, 300, 600),  # preprint models in both setups (D15)
    "ledger": (150, 220, 400),
}


def year_one(scen, idx):
    harness = pilot(scen) + launch(scen)[0] + second_seed(scen) + uncapped_delta(scen)
    validation = gpqa_diamond(scen) + YEAR["anchor_reruns"][idx]
    arena = arena_round(YEAR["events_per_round"][idx]) * 26 * YEAR["roster_growth"][idx]
    mday_avg = sum(model_day(m, scen) for m in FLAGSHIPS) / len(FLAGSHIPS)
    mdays = mday_avg * YEAR["model_days"][idx]
    rows = {
        "Ledger: bootstrap, backfill, 12 months daily": YEAR["ledger"][idx],
        "Arena: 26 rounds, 2 samples, growing roster": arena,
        "Harness launch: pilot, launch run, 2nd seed, uncapped delta": harness,
        "Validation: anchor re-runs, GPQA Diamond check": validation,
        "Model-days on anchor subsets": mdays,
    }
    return rows, sum(rows.values())


def main():
    print("Launch items per model:", sum(n for n, _, _ in LAUNCH.values()))
    print("Pilot items per model:", sum(min(n, PILOT_N) for n, _, _ in LAUNCH.values()) + 100)
    print("Model-day items per model:", sum(k for k, _ in model_day_items().values()))

    print("\nSequential stopping (min 150, every 50, Bonferroni-Wilson half-width <= 0.05):")
    for p in (0.5, 0.7, 0.8, 0.9, 0.95):
        print(f"  accuracy {p:.2f}: SeqQA n={stop_n(600, p)}  DbQA n={stop_n(520, p)}")

    print("\nHarness (capped reasoning, 1 seed)")
    for s in CAPPED:
        lt, _ = launch(s)
        lt85, _ = launch(s, p_seq=0.85)
        print(
            f"  {s:4}: pilot ${pilot(s):5.0f} | launch ${lt:5.0f} (if seq. acc 0.85: ${lt85:5.0f})"
            f" | 2nd seed top-3 ${second_seed(s):5.0f} | uncapped delta ${uncapped_delta(s):5.0f}"
            f" | GPQA Diamond ${gpqa_diamond(s):4.0f}"
        )
    _, per = launch("mid", incremental=False)
    print("  per model, launch run, mid (full, not net of pilot): "
          + ", ".join(f"{k} ${v:.0f}" for k, v in per.items()))

    print("\nModel-day (anchor subsets, capped reasoning)")
    for m in FLAGSHIPS + ["claude-opus-5-5"]:
        lo, mid, hi = (model_day(m, s) for s in CAPPED)
        print(f"  {m:17}: ${lo:5.1f} / ${mid:5.1f} / ${hi:5.1f}   arena +${arena_per_model_round(m, 30):4.1f}/round (30 ev)")

    print("\nArena round (2 samples x 6 flagships)")
    for ev in (25, 30, 50):
        print(f"  {ev} events: ${arena_round(ev):5.1f}")

    print("\nLedger extraction")
    for label, docs in (("bootstrap v0 (~6k docs)", 6000), ("backfill (~12k docs)", 12000),
                        ("daily (~40 docs)", 40), ("month (~900 docs)", 900)):
        print(f"  {label:26}: ${extract(docs):7.2f}")

    print("\nYear one")
    for idx, s in enumerate(CAPPED):
        rows, tot = year_one(s, idx)
        print(f"  {s}: total ${tot:,.0f}")
        for k, v in rows.items():
            print(f"     {k:62} ${v:,.0f}")


if __name__ == "__main__":
    main()
