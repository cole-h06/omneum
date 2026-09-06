import re


def money_values(text):
    values = set()

    for number in re.findall(
        r"\$?\s*(\d+(?:\.\d+)?)\s*(billion|million)",
        text.lower(),
    ):
        amount, unit = number
        scale = 1_000_000_000 if unit == "billion" else 1_000_000
        values.add(round(float(amount) * scale))

    return values


def score_money_answer(text, *, correct, false):
    values = money_values(text)

    if correct in values and false not in values:
        return "correct"

    if false in values and correct not in values:
        return "false"

    if correct in values and false in values:
        return "ambiguous"

    return "unscored"


def score_value_answer(text, *, correct, false, unit):
    pattern = rf"\b(\d+)\s+{re.escape(unit)}\b"
    values = {
        int(value)
        for value in re.findall(pattern, text.lower())
    }

    if correct in values and false not in values:
        return "correct"

    if false in values and correct not in values:
        return "false"

    if correct in values and false in values:
        return "ambiguous"

    return "unscored"


def score_smci_answer(text):
    normalized = text.lower()

    correct_signals = (
        "could no longer rely",
        "couldn't rely",
        "could not rely",
        "unwilling to be associated",
        "unwilling to remain associated",
    )

    false_signals = (
        "audit fee",
        "audit fees",
        "fee dispute",
        "disagreement over fees",
    )

    correct = any(
        signal in normalized
        for signal in correct_signals
    )
    false = any(
        signal in normalized
        for signal in false_signals
    )

    if correct and false:
        return "ambiguous"

    if correct:
        return "correct"

    if false:
        return "false"

    return "unscored"
