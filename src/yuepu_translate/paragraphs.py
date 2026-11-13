"""Text revisions independent of audio windows, inference, and GUI rows."""

from dataclasses import dataclass


def units(text):
    positions = [i for i, char in enumerate(text) if char.isalnum()]
    return "".join(text[i] for i in positions), positions


def accept_punctuation(original, candidate):
    """Punctuation review must never silently rewrite names, digits or words."""
    result = candidate.strip()
    if not result or units(result)[0] != units(original)[0]:
        result = original.strip()
    if result and result[-1] not in "。！？.!?":
        result = result.rstrip("，,；;：:") + "。"
    return result


def overlap_cut(before, incoming):
    """Locate adjacent checkpoint context, allowing small ASR corrections.

    Return a cut in the previous text: incoming context replaces that suffix,
    rather than preserving a known provisional spelling error. No global dedup.
    """
    left, positions = units(before)
    right, _ = units(incoming)
    maximum = min(len(left), len(right), 96)
    # Exact context wins: a longer approximate alignment with leading
    # deletions would swallow valid words immediately BEFORE the overlap.
    for count in range(maximum, 1, -1):
        if left.endswith(right[:count]):
            return positions[len(left) - count]
    # Substitute only within equal-length context, without guessing deleted
    # words at the boundary of the audio window.
    for count in range(maximum, 5, -1):
        changes = sum(a != b for a, b in zip(left[-count:], right[:count]))
        if changes <= min(2, count // 5):
            return positions[len(left) - count]
    return len(before)


def preserve_prefix(frozen, candidate):
    if not frozen:
        return candidate
    prefix, _ = units(frozen)
    current, positions = units(candidate)
    if current.startswith(prefix):
        cut = positions[len(prefix) - 1] + 1
    else:
        # Frozen text is authoritative. Locate its last stable anchor instead
        # of allowing a later ASR revision to rewrite it or shift the tail.
        anchor = prefix[-10:]
        begin = max(0, len(prefix) - len(anchor) - 6)
        end = min(len(current), len(prefix) + 6)
        found = current.find(anchor, begin, end)
        if found >= 0:
            cut = positions[found + len(anchor) - 1] + 1
        else:
            cut = positions[min(len(prefix), len(positions)) - 1] + 1 if positions else 0
    return frozen + candidate[cut:].lstrip(" ，。！？、；：,.!?;:\n")


@dataclass(frozen=True)
class Revision:
    source: str
    frozen_delta: str
    tail: str
    final: bool


class ParagraphRevision:
    """A paragraph replaces its draft; stable old text and final rows freeze.

    Freeze an agreed prefix after 2 s, keeping at least 8 characters revisable.
    Audio checkpoints do not create new rows.
    This is textual agreement, not a claim of manually verified correctness.
    """

    def __init__(self):
        self.frozen = self.source = self.previous = self.anchor = ""
        self.origin = None
        self.closed = False
        self.version = -1

    def update(self, text, origin, version, age_seconds, final=False):
        if self.closed or version <= self.version:
            return None
        if self.origin is None:
            self.origin = origin
        elif origin != self.origin:
            self.anchor = self.source[: overlap_cut(self.source, text)]
            self.origin = origin
        candidate = preserve_prefix(self.frozen, self.anchor + text)
        current, positions = units(candidate)
        previous, _ = units(self.previous)
        stable = 0
        for left, right in zip(previous, current):
            if left != right:
                break
            stable += 1
        old_length = len(self.frozen)
        cut = old_length
        if final:
            cut = len(candidate)
        elif age_seconds >= 2 and len(current) > 14:
            count = min(stable, len(current) - 8)
            if count > 0:
                proposed = positions[count - 1] + 1
                # Promote complete clauses, not arbitrary character counts:
                # cutting a word can make the MT model invent its missing half.
                boundary = max(candidate.rfind(c, old_length, proposed) for c in "。！？；，.!?;")
                if boundary >= old_length + 6:
                    proposed = boundary + 1
                    if len(units(candidate[old_length:proposed])[0]) >= 6:
                        cut = max(cut, proposed)
        delta = candidate[old_length:cut]
        self.frozen = candidate[:cut]
        self.source = self.previous = candidate
        self.version = version
        self.closed = final
        return Revision(candidate, delta, candidate[cut:], final)
