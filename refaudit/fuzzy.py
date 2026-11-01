"""partial_ratio for the claim check: rapidfuzz's where it is installed, else a pure-Python version.

In the browser (Pyodide) rapidfuzz is not available. The fallback finds where the shorter string lines up with
the longer one by voting on shared k-grams (seed and extend), then scores only the best-voted windows with
`compare.lcs_ratio`, which gives the same floats as rapidfuzz's ratio. On the strings the claim check compares (a
quote against a page, a title against a first page) it agrees with rapidfuzz above the thresholds that matter
(85-95); far below them it may report a lower score, which changes no decision.
"""

from __future__ import annotations

from collections import Counter

from .compare import lcs_ratio

WINDOWS = 24  # best-voted alignments scored per call
SLACK = 3     # characters tried on either side of each alignment


def _partial_ratio(s1: str, s2: str) -> float:
    short, long = (s1, s2) if len(s1) <= len(s2) else (s2, s1)
    m, n = len(short), len(long)
    if not m:
        return 0.0
    if short in long:
        return 100.0
    if n <= m:
        return lcs_ratio(short, long)
    if n * m <= 60_000:  # small enough to try every alignment, as rapidfuzz does
        return max(lcs_ratio(short, long[i:i + m]) for i in range(n - m + 1))
    k = 3 if m < 24 else 5 if m < 80 else 7
    votes: Counter = Counter()
    for i in range(0, m - k + 1, 1 if m < 200 else 2):
        gram, start = short[i:i + k], long.find(short[i:i + k])
        hits = 0
        while start != -1 and hits < 400:  # a very common k-gram adds little evidence
            votes[start - i] += 1
            hits += 1
            start = long.find(gram, start + 1)
    best = 0.0
    tried = set()
    for diagonal, _ in votes.most_common(WINDOWS):
        for start in range(diagonal - SLACK, diagonal + SLACK + 1):
            start = min(max(start, 0), n - m)
            if start not in tried:
                tried.add(start)
                best = max(best, lcs_ratio(short, long[start:start + m]))
                if best == 100.0:
                    return best
    return best


try:
    from rapidfuzz.fuzz import partial_ratio
except ImportError:  # in the browser (Pyodide)
    partial_ratio = _partial_ratio
