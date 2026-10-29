"""Persistent, fail-closed spending reservations for hosted benchmark selectors."""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


CAP_USD = 30.0
RATES_PER_MILLION = {
    "claude": (2.0, 10.0),
    "gpt": (10.0, 50.0),
    "gemini": (0.75, 3.75),
}


class SpendingLimitError(RuntimeError):
    pass


class UnpricedProviderError(SpendingLimitError):
    pass


def request_fingerprint(provider, model, request, identity):
    encoded = json.dumps(
        {"provider": provider, "model": model, "request": request, "identity": identity},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def conservative_token_cost(provider, input_text, output_limit):
    """Bound text input by UTF-8 bytes plus framing and reserve the full output cap."""
    if provider == "cohere":
        raise UnpricedProviderError(
            "Cohere direct API rate for rerank-v4.0-pro is not published; dispatch blocked"
        )
    if provider not in RATES_PER_MILLION:
        raise UnpricedProviderError(f"No verified pricing configured for {provider!r}")
    input_rate, output_rate = RATES_PER_MILLION[provider]
    input_bound = len(input_text.encode("utf-8")) + 512
    return (input_bound * input_rate + output_limit * output_rate) / 1_000_000


def measured_token_cost(provider, response):
    if provider == "cohere":
        return None
    rates = RATES_PER_MILLION.get(provider)
    if rates is None:
        return None
    input_tokens = response.get("input_tokens")
    output_tokens = response.get("output_tokens")
    if provider == "gemini":
        usage = response.get("response_diagnostics", {}).get("usage_metadata", {})
        prompt_tokens = usage.get("prompt_token_count")
        total_tokens = usage.get("total_token_count")
        if type(prompt_tokens) is int and type(total_tokens) is int and total_tokens >= prompt_tokens:
            output_tokens = total_tokens - prompt_tokens
    if type(input_tokens) is not int or type(output_tokens) is not int:
        return None
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


class SpendingLedger:
    """One SQLite transaction reserves each exact request before dispatch."""

    def __init__(self, path, cap_usd=CAP_USD):
        if cap_usd != CAP_USD:
            raise ValueError(f"The benchmark cap is fixed at ${CAP_USD:.2f}")
        self.path = Path(path)
        self.cap_usd = cap_usd
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                fingerprint TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
                identity_json TEXT NOT NULL, reserved_usd REAL NOT NULL,
                status TEXT NOT NULL, response_json TEXT, actual_cost_usd REAL,
                updated_at REAL NOT NULL
            )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def reserved_usd(self):
        with closing(self._connect()) as db:
            return db.execute("SELECT COALESCE(SUM(reserved_usd),0) FROM requests").fetchone()[0]

    def begin(self, *, fingerprint, provider, model, identity, reserve_usd):
        if reserve_usd is None or reserve_usd < 0:
            raise UnpricedProviderError(f"No reliable spending estimate for {provider!r}")
        identity_json = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,response_json FROM requests WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if row:
                status, response = row
                db.commit()
                if status == "completed":
                    return json.loads(response), True
                raise SpendingLimitError(
                    f"Request {fingerprint[:12]} is {status}; automatic redispatch is blocked"
                )
            current = db.execute("SELECT COALESCE(SUM(reserved_usd),0) FROM requests").fetchone()[0]
            if current + reserve_usd > self.cap_usd + 1e-12:
                db.rollback()
                raise SpendingLimitError(
                    f"Reservation ${reserve_usd:.6f} would exceed ${self.cap_usd:.2f} "
                    f"cap (currently reserved ${current:.6f})"
                )
            db.execute("""INSERT INTO requests
                (fingerprint,provider,model,identity_json,reserved_usd,status,updated_at)
                VALUES (?,?,?,?,?,'dispatched',?)""",
                (fingerprint, provider, model, identity_json, reserve_usd, time.time()))
            db.commit()
        return None, False

    def finish(self, fingerprint, response, actual_cost_usd=None):
        serialized = json.dumps(response, sort_keys=True, separators=(",", ":"))
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE requests SET status='completed', response_json=?,
                actual_cost_usd=?, updated_at=? WHERE fingerprint=? AND status='dispatched'""",
                (serialized, actual_cost_usd, time.time(), fingerprint)).rowcount
            if changed != 1:
                db.rollback()
                raise SpendingLimitError("Cannot complete a request without its live reservation")
            db.commit()

    def mark_uncertain(self, fingerprint):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE requests SET status='uncertain',updated_at=? "
                                 "WHERE fingerprint=? AND status='dispatched'",
                                 (time.time(), fingerprint)).rowcount
            if changed != 1:
                db.rollback()
                raise SpendingLimitError("Cannot mark a request uncertain without its reservation")
            db.commit()

    async def dispatch_async(self, *, fingerprint, provider, model, identity,
                             reserve_usd, call):
        cached, reused = self.begin(fingerprint=fingerprint, provider=provider, model=model,
                                    identity=identity, reserve_usd=reserve_usd)
        if reused:
            return cached, True
        try:
            response = await call()
        except BaseException:
            self.mark_uncertain(fingerprint)
            raise
        self.finish(fingerprint, response, measured_token_cost(provider, response))
        return response, False

    def dispatch(self, *, fingerprint, provider, model, identity, reserve_usd, call):
        cached, reused = self.begin(fingerprint=fingerprint, provider=provider, model=model,
                                    identity=identity, reserve_usd=reserve_usd)
        if reused:
            return cached, True
        try:
            response = call()
        except BaseException:
            self.mark_uncertain(fingerprint)
            raise
        self.finish(fingerprint, response, measured_token_cost(provider, response))
        return response, False
