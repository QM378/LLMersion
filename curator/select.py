"""Topic selection: the agent's (small) policy.

Each configured topic gets a score: the mean of the learner's 0-5 ratings on
material from that topic, shrunk toward a neutral prior of 3.0 so that one bad
document does not kill a topic. Most nights pick the best-scoring topics; with
probability epsilon a slot goes to a *discovered* topic instead -- something
harvested from the related-articles of material the learner rated >= 4. That is
the entire exploration/exploitation story, and it is intentionally this simple:
the point is a curriculum that drifts toward what the learner engages with,
not a black box.
"""
from __future__ import annotations

import random

from . import store

PRIOR_MEAN = 3.0
PRIOR_WEIGHT = 2.0


def score(topic: str, stats: dict[str, tuple[float, int]]) -> float:
    mean, n = stats.get(topic, (PRIOR_MEAN, 0))
    return (mean * n + PRIOR_MEAN * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT)


def pick(topics: list[str], n: int, epsilon: float, rng: random.Random | None = None) -> list[str]:
    rng = rng or random.Random()
    stats = store.topic_stats()
    ranked = sorted(topics, key=lambda t: score(t, stats), reverse=True)
    chosen: list[str] = []
    pool = store.discovered_topics()
    for i in range(n):
        if pool and rng.random() < epsilon:
            chosen.append(rng.choice(pool))
        else:
            chosen.append(ranked[i % len(ranked)])
    return chosen
