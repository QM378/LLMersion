#!/usr/bin/env python3
"""Evaluate the curator's two mechanisms in isolation, without human subjects.

Diagnostic: re-encounter densities over a document folder (uses the reader's
      saved vocabulary when present, or --vocab file, else a synthetic list).
      NOTE this is a *description of your corpus and vocabulary*, not a
      validation of the ranking mechanism: the ranked pick is the maximum of
      the densities, so it exceeds the mean by construction. The mechanism's
      real test is behavioral (does density predict ratings/completion) and
      lives in the longitudinal data, not here.

          python tools/curator_bench.py 20pdf

E-C2  Policy simulation (no inputs; deterministic under --seed):
      a synthetic learner with hidden topic appeal rates delivered items 0-5;
      appeal drifts mid-horizon. Compares uniform choice, pure greedy, and the
      shipped policy (shrunk means + epsilon exploration).

          python tools/curator_bench.py --simulate

Both print LaTeX-ready lines. Simulation results are labeled as simulation;
they characterize the policy, not learners.
"""
from __future__ import annotations

import argparse
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curator import select, signals  # noqa: E402
from server import loaders  # noqa: E402


# ------------------------------------------------------------------ E-C1
def ranking_lift(docs_dir: str, vocab_file: str) -> dict:
    files = sorted(p for p in Path(docs_dir).iterdir()
                   if p.suffix.lower() in loaders.EXTENSIONS)
    texts = {}
    for f in files:
        try:
            d = loaders.load(f, f.name)
            texts[f.name] = " ".join(p["text"] for p in d["paragraphs"]
                                     if p["kind"] == "body")
        except Exception:
            continue

    if vocab_file:
        words = {w.strip().lower() for w in Path(vocab_file).read_text(
            encoding="utf-8").split() if w.strip()}
        source = f"file ({len(words)} words)"
    else:
        words = signals.saved_words()
        source = f"reader vocabulary ({len(words)} words)"
        if not words:
            # synthetic fallback: mid-frequency corpus words stand in for a
            # learner's list; labeled as such in the output
            from collections import Counter
            c = Counter(w.lower() for t in texts.values() for w in t.split()
                        if w.isalpha() and len(w) > 5)
            pool = c.most_common(600)
            words = {w for w, _ in (pool[200:500] if len(pool) > 250 else pool[:300])}
            source = f"synthetic mid-frequency list ({len(words)} words)"

    dens = {n: signals.reencounter_score(t, words) for n, t in texts.items()}
    vals = list(dens.values())
    top = max(vals)
    mean = st.mean(vals)                      # expected density of a random pick
    return {"documents": len(vals), "vocab_source": source,
            "picked_density": top, "random_density": mean,
            "lift": top / mean if mean else float("nan")}


# ------------------------------------------------------------------ E-C2
def simulate(nights: int = 60, per_night: int = 2, topics: int = 8,
             drift_night: int = 30, seeds: int = 200) -> dict:
    """The shipped policy against uniform and pure-greedy baselines, on a
    learner whose appeal for two topics swaps mid-horizon."""

    def run(policy: str, rng: random.Random) -> list[float]:
        appeal = [1.5 + 3.0 * k / (topics - 1) for k in range(topics)]
        ratings: dict[int, list[int]] = {k: [] for k in range(topics)}
        out = []
        for night in range(nights):
            if night == drift_night:               # interests change
                appeal[0], appeal[-1] = appeal[-1], appeal[0]
            for _ in range(per_night):
                if policy == "uniform":
                    k = rng.randrange(topics)
                else:
                    stats = {str(t): (st.mean(r), len(r))
                             for t, r in ratings.items() if r}
                    ranked = sorted(range(topics), reverse=True,
                                    key=lambda t: select.score(str(t), stats))
                    if policy == "ours" and rng.random() < 0.25:
                        k = rng.randrange(topics)   # exploration slot
                    else:
                        k = ranked[0]
                r = max(0, min(5, round(rng.gauss(appeal[k], 0.7))))
                ratings[k].append(r)
                out.append(r)
        return out

    res: dict = {}
    for policy in ("uniform", "greedy", "ours"):
        overall, post = [], []
        for s in range(seeds):
            rng = random.Random(1000 + s)
            r = run(policy, rng)
            overall.append(st.mean(r))
            post.append(st.mean(r[drift_night * per_night:]))
        res[policy] = {"mean": st.mean(overall), "post_drift": st.mean(post)}
    res["config"] = {"nights": nights, "per_night": per_night,
                     "topics": topics, "drift_night": drift_night,
                     "seeds": seeds, "epsilon": 0.25}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="?", help="document folder for the ranking-lift test")
    ap.add_argument("--vocab", default="", help="newline-separated word list; default: reader vocabulary")
    ap.add_argument("--simulate", action="store_true", help="run the policy simulation")
    args = ap.parse_args()
    if not args.docs and not args.simulate:
        ap.error("give a document folder, --simulate, or both")

    print("% ------- curator mechanism results -------")
    if args.docs:
        L = ranking_lift(args.docs, args.vocab)
        print(f"% ranking lift over {L['documents']} documents, vocab: {L['vocab_source']}")
        print(f"Saved-word density: ranked pick / random pick & "
              f"{L['picked_density']:.1f} / {L['random_density']:.1f} per 100 tokens "
              f"({L['lift']:.1f}$\\times$) \\\\")
    if args.simulate:
        S = simulate()
        c = S["config"]
        print(f"% simulation: {c['topics']} topics, {c['nights']} nights x "
              f"{c['per_night']}, drift at {c['drift_night']}, {c['seeds']} seeds")
        print(f"Mean delivered rating: uniform / greedy / shipped policy & "
              f"{S['uniform']['mean']:.2f} / {S['greedy']['mean']:.2f} / "
              f"{S['ours']['mean']:.2f} \\\\")
        print(f"…after mid-horizon interest drift & "
              f"{S['uniform']['post_drift']:.2f} / {S['greedy']['post_drift']:.2f} / "
              f"{S['ours']['post_drift']:.2f} \\\\")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
