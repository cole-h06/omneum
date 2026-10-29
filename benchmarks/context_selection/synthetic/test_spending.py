from concurrent.futures import ThreadPoolExecutor

import pytest

from .spending import (
    CAP_USD, SpendingLedger, SpendingLimitError, UnpricedProviderError,
    conservative_token_cost, request_fingerprint,
)


def test_cap_is_cumulative_across_providers_and_survives_restart(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    ledger = SpendingLedger(path)
    for provider in ('claude', 'gpt', 'gemini'):
        fingerprint = request_fingerprint(provider, 'model', {'prompt': provider}, {'case': 1})
        ledger.begin(fingerprint=fingerprint, provider=provider, model='model', identity={'case': 1},
                     reserve_usd=10.0)
    assert ledger.reserved_usd() == 30.0
    restored = SpendingLedger(path)
    with pytest.raises(SpendingLimitError, match='exceed'):
        restored.begin(fingerprint='new', provider='claude', model='m', identity={}, reserve_usd=0.01)
    assert restored.reserved_usd() == CAP_USD


def test_completed_response_is_reused_only_for_exact_fingerprint(tmp_path):
    ledger = SpendingLedger(tmp_path / 'ledger.sqlite3')
    fingerprint = request_fingerprint('gpt', 'gpt-6-astra', {'prompt': 'same'}, {'case': 1, 'trial': 1})
    params = dict(fingerprint=fingerprint, provider='gpt', model='gpt-6-astra',
                  identity={'case': 1, 'trial': 1}, reserve_usd=0.1)
    assert ledger.begin(**params) == (None, False)
    ledger.finish(fingerprint, {'text': '{"selected_ids":["a"]}', 'input_tokens': 4})
    restored = SpendingLedger(ledger.path)
    assert restored.begin(**params) == ({'input_tokens': 4, 'text': '{"selected_ids":["a"]}'}, True)
    changed = request_fingerprint('gpt', 'gpt-6-astra', {'prompt': 'different'}, {'case': 1, 'trial': 1})
    assert restored.begin(**{**params, 'fingerprint': changed}) == (None, False)
    assert restored.reserved_usd() == pytest.approx(0.2)


def test_uncertain_request_keeps_reservation_and_blocks_retry(tmp_path):
    ledger = SpendingLedger(tmp_path / 'ledger.sqlite3')
    params = dict(fingerprint='exact', provider='claude', model='claude-sonnet-5-5',
                  identity={'case': 'c', 'trial': 1}, reserve_usd=0.25)
    ledger.begin(**params)
    ledger.mark_uncertain('exact')
    assert ledger.reserved_usd() == 0.25
    with pytest.raises(SpendingLimitError, match='uncertain'):
        ledger.begin(**params)


def test_concurrent_dispatch_reserves_once(tmp_path):
    ledger = SpendingLedger(tmp_path / 'ledger.sqlite3')
    params = dict(fingerprint='shared', provider='gemini', model='gemini-3.8-flash',
                  identity={'case': 'c', 'trial': 1}, reserve_usd=1.0)

    def begin():
        try:
            return ledger.begin(**params)
        except SpendingLimitError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: begin(), range(8)))
    assert outcomes.count((None, False)) == 1
    assert ledger.reserved_usd() == 1.0


def test_unpriced_cohere_fails_closed_and_text_cost_is_conservative():
    with pytest.raises(UnpricedProviderError, match='not published'):
        conservative_token_cost('cohere', 'question', 0)
    assert conservative_token_cost('claude', 'hello', 2048) >= (
        (len('hello'.encode()) + 512) * 2 + 2048 * 10
    ) / 1_000_000
