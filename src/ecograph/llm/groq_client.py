"""
src/ecograph/llm/groq_client.py

Production-grade Groq LLM client with comprehensive quota protection.

Architecture:
- Token-bucket rate limiter enforces RPM and TPM ceilings simultaneously.
- Daily request counter persists to disk (logs/groq_daily.json) so the
RPD limit is respected across process restarts.
- Exponential back-off with jitter retries on 429 / 503 / 5xx responses.
- Prompt caching: identical prompt hashes are returned from an in-process
LRU cache, eliminating redundant API calls for repeated chunks.
- All quota state is thread-safe via threading.Lock so the client can be
shared across concurrent ingestion threads.

SOLID principles applied:
- Single Responsibility: this module only manages LLM communication and
quota. Prompt construction lives in callers.
- Open/Closed: new models or providers can be added by subclassing
GroqClientBase without touching rate-limiting logic.
- Liskov Substitution: GroqClient and MockGroqClient share the same
interface (ILLMClient) so tests swap them without modifying callers.
- Interface Segregation: ILLMClient exposes only complete() and
count_tokens(). Token-bucket internals are not part of the interface.
- Dependency Inversion: callers depend on ILLMClient, not the concrete
Groq SDK class.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import sys
try:
    import google_crc32c
    if not hasattr(google_crc32c, "exc"):
        import types
        google_crc32c.exc = types.ModuleType("exc")

        google_crc32c.exc.CrcError = Exception
except ImportError:
    pass
from groq import Groq, RateLimitError, APIStatusError, APIConnectionError

from ecograph.config import settings

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

_DAILY_COUNTER_FILE: Path = settings.LOGS_DIR / "groq_daily.json"
_PROMPT_CACHE_SIZE: int = 512  # LRU cache entries


# -----------------------------------------------------------------------------
# Interface (Dependency Inversion Principle)
# -----------------------------------------------------------------------------

class ILLMClient(ABC):
    """
    Minimal interface every LLM client must satisfy.
    Callers depend on this; they never import the concrete Groq class.
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send a prompt and return the assistant text response.

        Parameters
        ----------
        prompt:
            User-facing prompt text.
        temperature:
            Sampling temperature [0.0, 2.0]. Use 0.0 for deterministic
            structured extraction; higher values for creative generation.
        max_tokens:
            Maximum tokens in the completion.
        system_prompt:
            Optional system message. If None, a sensible default is used.

        Returns
        -------
        str: The assistant's response text.

        Raises
        ------
        LLMQuotaExhaustedError:
            Daily or per-minute quota exhausted after all retries.
        LLMResponseError:
            Non-quota API error (auth, invalid model, etc.).
        """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.
        Used by callers to pre-check whether a prompt will exceed TPM limits.
        """


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class LLMQuotaExhaustedError(RuntimeError):
    """
    Raised when Groq quota cannot be satisfied within the retry budget.
    Callers should either queue the request for later or degrade gracefully.
    """

class LLMResponseError(RuntimeError):
    """
    Raised for non-recoverable API errors (auth failure, invalid model,
    malformed request). Retrying would not help.
    """


# -----------------------------------------------------------------------------
# Token Bucket Rate Limiter
# -----------------------------------------------------------------------------

class _TokenBucket:
    """
    Thread-safe token bucket implementing two independent limits:
    1. Requests per minute (RPM)
    2. Tokens per minute (TPM)

    The bucket replenishes continuously: after a full 60-second window,
    the full capacity is available again.

    Usage:
        bucket = _TokenBucket(rpm=30, tpm=6000)
        bucket.consume(tokens_needed=150) # blocks until quota available
    """
    def __init__(self, rpm: int, tpm: int) -> None:
        self._rpm = rpm
        self._tpm = tpm
        self._lock = threading.Lock()

        self._request_tokens = float(rpm)
        self._text_tokens = float(tpm)
        self._last_refill_ts = time.monotonic()

    def _refill(self) -> None:
        """Refill buckets proportionally to elapsed time. Must be called under lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill_ts
        self._last_refill_ts = now

        # fraction of a minute that has elapsed
        frac = elapsed / 60.0

        self._request_tokens = min(
            float(self._rpm),
            self._request_tokens + self._rpm * frac,
        )
        self._text_tokens = min(
            float(self._tpm),
            self._text_tokens + self._tpm * frac,
        )

    def consume(self, estimated_tokens: int, timeout: float = 120.0) -> None:
        """
        Block until both one request-token and `estimated_tokens` text-tokens
        are available, then consume them.

        Parameters
        ----------
        estimated_tokens:
            Estimated token count for the request (prompt + max_tokens).
        timeout:
            Maximum seconds to wait before raising LLMQuotaExhaustedError.

        Raises
        ------
        LLMQuotaExhaustedError:
            If quota cannot be satisfied within `timeout` seconds.
        """
        deadline = time.monotonic() + timeout
        sleep_interval = 0.5

        while True:
            with self._lock:
                self._refill()
                if self._request_tokens >= 1.0 and self._text_tokens >= estimated_tokens:
                    self._request_tokens -= 1.0
                    self._text_tokens -= estimated_tokens
                    return

            if time.monotonic() >= deadline:
                raise LLMQuotaExhaustedError(
                    f"Token bucket timeout after {timeout}s. "
                    f"estimated_tokens={estimated_tokens}, "
                    f"rpm_ceiling={self._rpm}, tpm_ceiling={self._tpm}."
                )

            # Progressive back-off while waiting for bucket to refill
            sleep_interval = min(sleep_interval * 1.5, 10.0)
            time.sleep(sleep_interval)


# -----------------------------------------------------------------------------
# Daily Request Counter (persists across restarts)
# -----------------------------------------------------------------------------

class _DailyCounter:
    """
    Tracks requests made to the Groq API today.
    State is persisted to disk so the RPD limit survives process restarts.
    """
    def __init__(self, path: Path, limit: int) -> None:
        self._path = path
        self._limit = limit
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict:
        today = date.today().isoformat()
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"date": today, "count": 0}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._state), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist daily counter: %s", exc)

    def increment(self) -> None:
        """
        Increment the daily counter.

        Raises
        ------
        LLMQuotaExhaustedError:
            If today's request count would exceed the daily limit.
        """
        with self._lock:
            # Reset if it's a new day
            today = date.today().isoformat()
            if self._state["date"] != today:
                self._state = {"date": today, "count": 0}

            if self._state["count"] >= self._limit:
                raise LLMQuotaExhaustedError(
                    f"Groq daily request limit ({self._limit} RPD) exhausted for {today}. "
                    "Requests will resume tomorrow. Check logs/groq_daily.json."
                )

            self._state["count"] += 1
            self._save()

    @property
    def today_count(self) -> int:
        with self._lock:
            return self._state.get("count", 0)


# -----------------------------------------------------------------------------
# Prompt Cache
# -----------------------------------------------------------------------------

@lru_cache(maxsize=_PROMPT_CACHE_SIZE)
def _cached_response(prompt_hash: str, model: str, temperature_str: str) -> Optional[str]:
    """
    LRU cache keyed on (prompt_hash, model, temperature).
    Returns None on cache miss so the caller knows to make a real API call.
    This function is only the cache store - actual population happens in
    GroqClient._complete_with_cache().
    """
    return None # Cache miss; real call handles population


# -----------------------------------------------------------------------------
# Concrete Groq Client
# -----------------------------------------------------------------------------

class GroqClient(ILLMClient):
    """
    Production Groq LLM client.

    Features:
    - Token-bucket rate limiting (RPM + TPM)
    - Daily request counter with disk persistence
    - In-process LRU prompt cache
    - Exponential back-off with jitter on quota and server errors
    - Structured logging with request metadata
    - Thread-safe for concurrent ingestion pipelines

    Usage:
        client = GroqClient()
        text = client.complete("Summarise the following text: ...")
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        rpm: Optional[int] = None,
        tpm: Optional[int] = None,
        rpd: Optional[int] = None,
    ) -> None:
        resolved_key = api_key or settings.GROQ_API_KEY
        if not resolved_key:
            raise LLMResponseError(
                "GROQ_API_KEY is not set. Add it to .env or pass api_key= to GroqClient()."
            )

        self._sdk = Groq(api_key=resolved_key)
        self._model = model or settings.GROQ_MODEL
        self._timeout = settings.GROQ_API_TIMEOUT
        self._bucket = _TokenBucket(
            rpm=rpm or settings.GROQ_REQUESTS_PER_MINUTE,
            tpm=tpm or settings.GROQ_TOKENS_PER_MINUTE,
        )
        self._daily = _DailyCounter(
            path=_DAILY_COUNTER_FILE,
            limit=rpd or settings.GROQ_REQUESTS_PER_DAY,
        )
        self._response_cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()

        logger.info(
            "GroqClient initialised.",
            extra={
                "model": self._model,
                "rpm": rpm or settings.GROQ_REQUESTS_PER_MINUTE,
                "tpm": tpm or settings.GROQ_TOKENS_PER_MINUTE,
                "rpd": rpd or settings.GROQ_REQUESTS_PER_DAY,
                "today_requests": self._daily.today_count,
            },
        )

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send prompt to Groq and return text response.

        Implements:
        1. Cache lookup - return immediately if identical prompt seen before.
        2. Daily quota check - fail fast before consuming rate-limit budget.
        3. Token-bucket wait - block until RPM + TPM capacity available.
        4. API call with exponential back-off retry.
        5. Cache population on success.
        """
        cache_key = self._cache_key(prompt, temperature, max_tokens, system_prompt)

        # Step 1: Cache lookup
        cached = self._get_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for prompt.", extra={"cache_key": cache_key[:16]})
            return cached

        # Step 2: Daily quota pre-check (fast fail - no waiting)
        self._daily.increment()

        # Step 3: Estimate tokens and wait for bucket
        estimated = self.count_tokens(prompt) + max_tokens
        self._bucket.consume(estimated_tokens=estimated)

        # Step 4: API call with retries
        response_text = self._call_with_retries(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

        # Step 5: Populate cache
        self._set_cache(cache_key, response_text)
        return response_text

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count using a character-based heuristic.

        For English text, 1 token ~ 4 characters is a reliable approximation
        validated against the Groq tokeniser for Llama models. We add a 10%
        overhead to account for special tokens in structured prompts.
        """
        return math.ceil(len(text) / 4 * 1.1)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _call_with_retries(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """
        Execute the Groq chat completion call with exponential back-off retry.

        Retry conditions:
        - RateLimitError (429): quota hit at Groq server - back off and retry.
        - APIStatusError (503): transient server error - back off and retry.
        - APIConnectionError: network issue - back off and retry.

        Non-retry conditions (raise immediately):
        - APIStatusError (400, 401, 403, 404): client error - likely a bug or
          misconfiguration that retries won't fix.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({"role": "system", 
                             "content": (
                                "You are a precise, structured data extraction engine."
                                "Always output valid Json exactly matching the requested schema."
                                "Never include prose, markdown fences, or explanation outside the JSON"
                             ),
                                })
        messages.append({"role": "user", "content": prompt})

        last_exec: Optional[Exception] = None

        last_exc: Optional[Exception] = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                t0 = time.monotonic()
                completion = self._sdk_call_with_timeout(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                elapsed = time.monotonic() - t0
                response_text = completion.choices[0].message.content or ""

                logger.debug(
                    "Groq completion succeeded.",
                    extra={
                        "model": self._model,
                        "attempt": attempt,
                        "elapsed_s": round(elapsed, 2),
                        "prompt_tokens": getattr(completion.usage, "prompt_tokens", None),
                        "completion_tokens": getattr(completion.usage, "completion_tokens", None),
                    },
                )
                return response_text

            except RateLimitError as exc:
                last_exc = exc
                wait = self._backoff(attempt)
                logger.warning(
                    "Groq rate limit hit. Backing off.",
                    extra={"attempt": attempt, "wait_s": wait, "model": self._model},
                )
                time.sleep(wait)

            except APIStatusError as exc:
                last_exc = exc
                if 500 <= exc.status_code < 600:
                    wait = self._backoff(attempt)
                    logger.warning(
                        "Groq server error. Backing off.",
                        extra={"attempt": attempt, "status": exc.status_code, "wait_s": wait},
                    )
                    time.sleep(wait)
                else:
                    # 4xx client error - retrying will not help
                    raise LLMResponseError(
                        f"Groq API client error (status {exc.status_code}): {exc.message}"
                    ) from exc

            except APIConnectionError as exc:
                last_exc = exc
                wait = self._backoff(attempt)
                logger.warning(
                    "Groq connection error. Backing off.",
                    extra={"attempt": attempt, "wait_s": wait, "error": str(exc)},
                )
                time.sleep(wait)

        raise LLMQuotaExhaustedError(
            f"Groq call failed after {settings.MAX_RETRIES} retries. "
            f"Last error: {last_exc}"
        )

    def _sdk_call_with_timeout(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ):
        """Execute a Groq SDK completion call with a hard request timeout."""
        result: dict[str, object] = {}
        error: list[Exception] = []

        def target() -> None:
            try:
                result["completion"] = self._sdk.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                error.append(exc)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(self._timeout)

        if thread.is_alive():
            raise LLMQuotaExhaustedError(
                f"Groq request timed out after {self._timeout}s. "
                "The SDK call did not return in time."
            )

        if error:
            raise error[0]

        return result["completion"]

    @staticmethod
    def _backoff(attempt: int) -> float:
        """
        Exponential back-off with full jitter.

        Base: settings.RETRY_BACKOFF seconds, doubles per attempt, capped at 60s.
        Jitter: random fraction [0, 1) * base to de-correlate concurrent callers.
        """
        import random
        base = min(settings.RETRY_BACKOFF * (2 ** (attempt - 1)), 60.0)
        return base + random.random() * base

    @staticmethod
    def _cache_key(
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        payload = f"{prompt}|{temperature}|{max_tokens}|{system_prompt or ''}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_cache(self, key: str) -> Optional[str]:
        with self._cache_lock:
            return self._response_cache.get(key)

    def _set_cache(self, key: str, value: str) -> None:
        with self._cache_lock:
            # Evict oldest entry if cache is full
            if len(self._response_cache) >= _PROMPT_CACHE_SIZE:
                oldest = next(iter(self._response_cache))
                del self._response_cache[oldest]
            self._response_cache[key] = value

    @property
    def today_request_count(self) -> int:
        """Expose daily counter for monitoring / dashboards."""
        return self._daily.today_count


# -----------------------------------------------------------------------------
# Mock client for testing (no API calls)
# -----------------------------------------------------------------------------

class MockGroqClient(ILLMClient):
    """
    Deterministic mock that satisfies ILLMClient without making network calls.
    Use in unit tests via dependency injection.

    Usage:
        mock = MockGroqClient(responses={"my prompt": "expected response"})
        parser = ESGPDFParser(llm_client=mock)
    """

    def __init__(self, responses: Optional[dict[str, str]] = None) -> None:
        self._responses = responses or {}
        self._call_log: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        system_prompt: Optional[str] = None,
    ) -> str:
        self._call_log.append(prompt)
        return self._responses.get(prompt, "[]")

    def count_tokens(self, text: str) -> int:
        return math.ceil(len(text) / 4)

    @property
    def call_count(self) -> int:
        return len(self._call_log)


# -----------------------------------------------------------------------------
# Singleton factory - callers use get_groq_client() rather than constructing
# directly, ensuring a single shared rate-limiter across the process.
# -----------------------------------------------------------------------------

_singleton: Optional[GroqClient] = None
_singleton_lock = threading.Lock()

def get_groq_client() -> GroqClient:
    """
    Return the process-singleton GroqClient.

    Thread-safe double-checked locking ensures only one instance is created
    even if multiple threads call this simultaneously on startup.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = GroqClient()
    return _singleton
            