"""Deterministic follow-up resolution for threads.

A follow-up such as "What about F200?" only makes sense next to the question
before it. ``contextualize`` rewrites it into a standalone question by
swapping the new fund or percentage into the previous question:

    previous:  Can client C001 put 40% into fund F100?
    follow-up: What about F200?
    resolved:  Can client C001 put 40% into fund F200?

The rules are plain pattern substitution, so the same thread always resolves
the same way, and the resolved text is stored on the decision next to what
the advisor typed. Anything that isn't recognisably a follow-up is answered
as written.
"""

from __future__ import annotations

import re


_FUND_RE = re.compile(r"\bF\d{3}\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_FOLLOW_UP_CUE = re.compile(
    r"^\s*(and|but|also|then|so|instead|what about|how about|same for|"
    r"same question for|what if|and if|what about if)\b",
    re.IGNORECASE,
)
# Very short messages are read as follow-ups even without a cue word.
_MAX_BARE_FOLLOW_UP_WORDS = 4
# Replies that ask about the previous answer itself rather than a new topic.
_ABOUT_PREVIOUS_ANSWER = re.compile(
    r"^\s*(and\s+|but\s+)?(why( not)?|how so|explain( that| more| why)?|more details?|"
    r"which sources?|what sources?|sources?|evidence|citations?|show me the sources?)"
    r"\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def _funds(text: str) -> list[str]:
    return [match.upper() for match in _FUND_RE.findall(text)]


def _percents(text: str) -> list[str]:
    return [re.sub(r"\s+", "", match) for match in _PERCENT_RE.findall(text)]


def is_follow_up(question: str) -> bool:
    return bool(_FOLLOW_UP_CUE.match(question)) or (
        len(question.split()) <= _MAX_BARE_FOLLOW_UP_WORDS
    )


def contextualize(question: str, previous: str | None) -> str:
    """Return the standalone question to retrieve and reason with.

    ``previous`` is the resolved question of the thread's last turn (None at
    the start of a thread)."""
    if not previous or not is_follow_up(question):
        return question

    funds, percents = _funds(question), _percents(question)
    if not funds and not percents:
        # "Why?" / "Which sources?" re-asks the previous question (same
        # evidence); a new topic ("What about liquidity?") is answered as
        # written, with the thread's client still in scope.
        return previous if _ABOUT_PREVIOUS_ANSWER.match(question) else question

    resolved = previous
    if funds:
        if not _funds(previous):
            return question  # nothing to substitute into; answer as asked
        resolved = _FUND_RE.sub(funds[0], resolved, count=1)
    if percents:
        if not _percents(previous):
            return question if not funds else resolved
        resolved = _PERCENT_RE.sub(percents[0], resolved, count=1)
    return resolved
