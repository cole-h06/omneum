import re
from functools import lru_cache


ANSWER_GRADER_VERSION = "lexical-polarity-v2"


def normalize(text):
    return " ".join(
        re.sub(r"[^\w\s]", " ", text.lower()).split()
    )


def score_answer_legacy(answer, truth):
    """Frozen v1 substring rubric, retained for historical artifact audits."""
    normalized = normalize(answer)

    required = [
        normalize(value)
        for value in truth.scoring.required
    ]
    forbidden = [
        normalize(value)
        for value in truth.scoring.forbidden
    ]

    if any(
        value and value in normalized
        for value in forbidden
    ):
        return "incorrect"

    if all(
        value and value in normalized
        for value in required
    ):
        return "correct"

    return "unscored"


@lru_cache(maxsize=4096)
def _forms(word):
    """Conservative regular English inflections; identifiers/numbers stay exact.

    This is surface morphology, not synonym matching or semantic entailment.
    Generate from the rubric token, rather than stemming arbitrary answer words.
    """
    if not word.isalpha() or len(word) < 4:
        return frozenset((word,))
    forms = {word, word + "s", word + "es", word + "ed", word + "ing"}
    if word.endswith("e"):
        forms.update((word + "d", word[:-1] + "ing"))
    if word.endswith("y") and word[-2] not in "aeiou":
        forms.update((word[:-1] + "ies", word[:-1] + "ied"))
    # Plural rubric nouns (e.g. connections) may also appear singular.
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        forms.add(word[:-1])
    return frozenset(forms)


def _clauses(text):
    text = text.casefold().replace("’", "'")
    text = re.sub(r"\b(can|do|does|did|should|would|could|must|is|are|was|were|has|have)n['’]t\b",
                  r"\1 not", text)
    text = re.sub(r"\bwon't\b", "will not", text)
    text = re.sub(r"\b(can't|cannot)\b", "can not", text)
    # Preserve decimal separators and dotted APIs inside a clause. A dot
    # followed by whitespace/end, or other punctuation, ends negation scope.
    return [normalize(c).split() for c in re.split(r"\.(?=\s|$)|[!?;:\n]+", text)]


def _negated(tokens, start, end):
    """Recognize local predicate negation, never an arbitrary sentence window.

    Unknown syntax remains unmatched/strict. 'Not only' is additive. Coordinating
    clauses and punctuation prevent a preceding negation leaking to a new action.
    """
    prefix = tokens[max(0, start - 6):start]
    for i in range(len(prefix) - 1, -1, -1):
        if prefix[i] in {"but", "and", "or", "however"}:
            prefix = prefix[i + 1:]
            break
    modifiers = {"ever", "simply", "just", "to"}
    while prefix and prefix[-1] in modifiers:
        prefix.pop()
    negators = {"not", "never", "without", "avoid", "avoids", "avoiding"}
    if prefix and prefix[-1] in negators:
        # Do not turn double negation ('do not avoid disabling') into an
        # exemption for an otherwise forbidden recommendation.
        return sum(t in negators for t in prefix) % 2 == 1
    if prefix[-3:] == ["no", "need", "to"] or prefix[-2:] == ["no", "need"]:
        return True
    suffix = tokens[end:end + 5]
    return (len(suffix) >= 3 and suffix[0] in {"is", "are", "was", "were"}
            and suffix[1] == "not" and suffix[2] in {"needed", "necessary", "recommended", "required"})


def _polarities(clauses, phrase):
    words = normalize(phrase).split()
    if not words:
        return set()
    raw_words = re.findall(r"\w+", phrase)
    code_phrase = bool(re.search(r"[_/]|[A-Za-z]\.[A-Za-z]", phrase))
    variants = [(_forms(word) if raw.islower() and not code_phrase else frozenset((word,)))
                for word, raw in zip(words, raw_words, strict=True)]
    found = set()
    for tokens in clauses:
        for start in range(len(tokens) - len(words) + 1):
            end = start + len(words)
            if all(token in forms for token, forms in zip(tokens[start:end], variants)):
                found.add(not _negated(tokens, start, end))
    return found


def score_answer(answer, truth):
    """Versioned token/inflection rubric with local negation handling.

    Applies identically to all arms. Missing or negated required assertions stay
    unscored; any affirmative forbidden assertion overrides required assertions.
    This deliberately remains a limited lexical grader, not a semantic judge.
    """
    clauses = _clauses(answer)
    if any(True in _polarities(clauses, phrase) for phrase in truth.scoring.forbidden):
        return "incorrect"
    if all(_polarities(clauses, phrase) == {True} for phrase in truth.scoring.required):
        return "correct"
    return "unscored"


def score_selection(selected, truth):
    selected = set(selected)
    expected = set(truth.supporting_sources)

    true_positive = len(selected & expected)
    false_positive = len(selected - expected)
    false_negative = len(expected - selected)

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
    }
