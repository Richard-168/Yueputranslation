"""Explicit character-error scoring for human-referenced audio experiments.

No automatic script conversion, homophone correction, phrase deduplication or
reference generation is performed here. Callers must record their normalization.
"""

import unicodedata


def normalize(text):
    """Remove punctuation/whitespace, preserving lexical characters and case."""
    return "".join(c for c in unicodedata.normalize("NFC", text) if c.isalnum())


def character_errors(reference, hypothesis):
    """Levenshtein CER, with deletion defined relative to the human reference.

    Multiple equally short alignments can exist. Ties prefer substitution, then
    deletion, then insertion; the overall edit distance is unaffected.
    """
    if not reference:
        raise ValueError("A nonempty human reference is required")
    n, m = len(reference), len(hypothesis)
    costs = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        costs[i][0] = i
    for j in range(m + 1):
        costs[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            costs[i][j] = min(
                costs[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]),
                costs[i - 1][j] + 1,
                costs[i][j - 1] + 1,
            )
    i, j = n, m
    edits = []
    while i or j:
        if i and j and reference[i - 1] == hypothesis[j - 1]:
            i, j = i - 1, j - 1
            continue
        if i and j and costs[i][j] == costs[i - 1][j - 1] + 1:
            edits.append(
                {
                    "kind": "substitution",
                    "reference": reference[i - 1],
                    "hypothesis": hypothesis[j - 1],
                    "reference_index": i - 1,
                }
            )
            i, j = i - 1, j - 1
        elif i and costs[i][j] == costs[i - 1][j] + 1:
            edits.append(
                {
                    "kind": "deletion",
                    "reference": reference[i - 1],
                    "hypothesis": "",
                    "reference_index": i - 1,
                }
            )
            i -= 1
        else:
            edits.append(
                {
                    "kind": "insertion",
                    "reference": "",
                    "hypothesis": hypothesis[j - 1],
                    "reference_index": i,
                }
            )
            j -= 1
    counts = {
        kind: sum(e["kind"] == kind for e in edits)
        for kind in ("substitution", "deletion", "insertion")
    }
    return {
        "reference_characters": n,
        "hypothesis_characters": m,
        "substitutions": counts["substitution"],
        "deletions": counts["deletion"],
        "insertions": counts["insertion"],
        "distance": costs[n][m],
        "cer": costs[n][m] / n,
        "edits": list(reversed(edits)),
    }
