"""The retry policy must tell a per-minute rate limit (retry) from a per-day quota (give up now)."""
from citewise.llm import is_daily_quota


class FakeAPIError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def test_daily_quota_detected():
    # quotaId copied from a real 429 the evaluation hit on 2026-10-22
    e = FakeAPIError(429, "429 RESOURCE_EXHAUSTED ... 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'")
    assert is_daily_quota(e)


def test_per_minute_limit_is_not_daily():
    e = FakeAPIError(429, "429 RESOURCE_EXHAUSTED ... 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'")
    assert not is_daily_quota(e)


def test_server_error_is_not_daily():
    assert not is_daily_quota(FakeAPIError(503, "UNAVAILABLE PerDay"))
