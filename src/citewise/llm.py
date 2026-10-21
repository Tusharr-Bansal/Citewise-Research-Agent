"""The only module that talks to the LLM provider (docs/decisions/0002).

Responsibilities:
- Retry with exponential backoff + jitter on rate limits (429) and overload (5xx).
- Cache responses on disk keyed by (model, prompt, settings), so re-running an
  eval never re-spends quota and gives identical results.
- Log every call (tokens, latency, cache hit, served model version) to a JSONL
  file, which is where cost-per-question numbers come from.
- Throttle to stay under the free tier's requests-per-minute limit.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types

from . import config

MODEL = os.environ.get("CITEWISE_LLM_MODEL", "gemini-3.5-flash-lite")
CACHE_DB = config.REPO_ROOT / ".cache" / "llm_cache.sqlite"
CALL_LOG = config.REPO_ROOT / ".cache" / "llm_calls.jsonl"
MIN_INTERVAL_S = float(os.environ.get("CITEWISE_LLM_MIN_INTERVAL_S", "4.0"))  # ~15 requests/min
MAX_ATTEMPTS = 6
RETRYABLE = {429, 500, 502, 503, 504}


class DailyQuotaExhausted(RuntimeError):
    """The free tier's requests-per-day quota is used up. Retrying is pointless until it resets."""


def is_daily_quota(e: Exception) -> bool:
    # A per-minute 429 clears in seconds; a per-day 429 names a "PerDay" quota id and lasts hours.
    return getattr(e, "code", None) == 429 and "PerDay" in str(e)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cached: bool
    model_version: str

    def json(self) -> Any:
        return json.loads(self.text)


class LLM:
    def __init__(self, model: str = MODEL, max_attempts: int = MAX_ATTEMPTS):
        self.model = model
        self.max_attempts = max_attempts
        self._client: genai.Client | None = None
        self._last_call = 0.0
        self._lock = threading.Lock()
        CACHE_DB.parent.mkdir(exist_ok=True)
        self._db = sqlite3.connect(CACHE_DB, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)"
        )

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
            self._client = genai.Client(api_key=key)
        return self._client

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        json_schema: dict | None = None,
        purpose: str = "unspecified",
        use_cache: bool = True,
    ) -> LLMResponse:
        settings = {"system": system, "temperature": temperature, "schema": json_schema}
        key = hashlib.sha256(
            json.dumps([self.model, prompt, settings], sort_keys=True).encode()
        ).hexdigest()

        if use_cache:
            row = self._db.execute("SELECT response FROM cache WHERE key = ?", (key,)).fetchone()
            if row:
                r = LLMResponse(**{**json.loads(row[0]), "cached": True, "latency_s": 0.0})
                self._log(purpose, r)
                return r

        cfg = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
            response_mime_type="application/json" if json_schema else None,
            response_json_schema=json_schema,
        )
        resp, latency = self._call_with_retry(prompt, cfg)
        usage = resp.usage_metadata
        r = LLMResponse(
            text=resp.text or "",
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
            if usage
            else 0,
            latency_s=latency,
            cached=False,
            model_version=resp.model_version or self.model,
        )
        if r.text:
            stored = {k: v for k, v in r.__dict__.items() if k not in ("cached", "latency_s")}
            self._db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(stored)))
            self._db.commit()
        self._log(purpose, r)
        return r

    def _call_with_retry(self, prompt: str, cfg: types.GenerateContentConfig):
        for attempt in range(1, self.max_attempts + 1):
            with self._lock:  # throttle: space calls out across threads
                wait = self._last_call + MIN_INTERVAL_S - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.monotonic()
            t0 = time.perf_counter()
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                return resp, time.perf_counter() - t0
            except errors.APIError as e:
                if is_daily_quota(e):
                    raise DailyQuotaExhausted(f"{self.model}: daily free-tier quota used up") from e
                if e.code not in RETRYABLE or attempt == self.max_attempts:
                    raise
                # exponential backoff with full jitter: 2, 4, 8, ... seconds, capped
                delay = random.uniform(0, min(60, 2**attempt))
                print(f"[llm] {e.code} on attempt {attempt}; retrying in {delay:.1f}s")
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _log(self, purpose: str, r: LLMResponse) -> None:
        with open(CALL_LOG, "a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "purpose": purpose,
                        "model": r.model_version,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "latency_s": round(r.latency_s, 3),
                        "cached": r.cached,
                    }
                )
                + "\n"
            )
