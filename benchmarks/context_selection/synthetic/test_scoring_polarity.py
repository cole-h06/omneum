import pytest

from .test_scoring import truth
from .scoring import score_answer, score_answer_legacy


@pytest.mark.parametrize("answer", [
    "Bound idle connections and evict expired entries.",
    "Bounding idle connections and evicting expired entries.",
    "The fix bounds idle connections and evicts expired entries.",
])
def test_regular_inflections_preserve_required_actions(answer):
    assert score_answer(answer, truth(["bound idle connections", "evict expired"])) == "correct"


@pytest.mark.parametrize("negation", [
    "Do not disable connection reuse.", "Never disable connection reuse.",
    "Avoid disabling connection reuse.", "Without disabling connection reuse.",
    "Disabling connection reuse is not necessary.", "Don't disable connection reuse.",
    "There is no need to disable connection reuse.",
])
def test_negated_forbidden_action_is_not_an_affirmative_recommendation(negation):
    answer = "Bound idle connections and evict expired entries. " + negation
    assert score_answer(answer, truth(["bound idle connections", "evict expired"],
                                      ["disable connection reuse"])) == "correct"


@pytest.mark.parametrize("answer", [
    "Disable connection reuse.", "Disabling connection reuse fixes it.",
    "Do not avoid disabling connection reuse.",
    "Not only disable connection reuse but also restart the worker.",
    "Do not restart; disable connection reuse.",
    "Do not restart the worker and disable connection reuse.",
    "Do not disable connection reuse. Actually, disable connection reuse.",
])
def test_affirmative_forbidden_action_still_overrides_required(answer):
    answer = "Bound idle connections and evict expired entries. " + answer
    assert score_answer(answer, truth(["bound idle connections", "evict expired"],
                                      ["disable connection reuse"])) == "incorrect"


@pytest.mark.parametrize("answer", [
    "Do not bound idle connections or evict expired entries.",
    "Never bound idle connections. Evict expired entries.",
    "We cannot establish the fix.",
])
def test_negated_or_missing_required_actions_are_not_correct(answer):
    assert score_answer(answer, truth(["bound idle connections", "evict expired"])) == "unscored"


def test_polarity_applies_to_numeric_answers_and_does_not_leak_across_clauses():
    assert score_answer("Not 9092.", truth(["9092"])) == "unscored"
    assert score_answer("90920", truth(["9092"])) == "unscored"
    assert score_answer("The port is 9092, not 8080.", truth(["9092"], ["8080"])) == "correct"
    assert score_answer("Not 8080; 9092.", truth(["9092"], ["8080"])) == "correct"
    assert score_answer("Not only 8080 but also 9092.", truth(["9092"], ["8080"])) == "incorrect"
    assert score_answer("Not 9092. The port is 9092.", truth(["9092"])) == "unscored"


def test_no_synonym_or_detail_invention_and_legacy_is_available():
    rubric = truth(["bound idle connections", "evict expired"])
    assert score_answer("Limit idle connections and remove expired entries.", rubric) == "unscored"
    assert score_answer("Bound idle pool connections and evict expired entries.", rubric) == "unscored"
    assert score_answer_legacy("Bounding idle connections and evicting expired entries.", rubric) == "unscored"


def test_identifiers_and_methods_do_not_receive_english_inflections():
    assert score_answer("client.exports.creating csv", truth(["client.exports.create", "csv"])) == "unscored"
    assert score_answer("Posting admin/keys/refresh", truth(["POST", "admin/keys/refresh"])) == "unscored"
    assert score_answer("load_tests", truth(["load_test"])) == "unscored"
