"""The question budget is counted in LLM calls, and a rejected request charges nothing."""
import pytest
from fastapi import HTTPException

from citewise.app import CALLS_CHARGED, RateLimiter


def test_deep_questions_cost_more_of_the_global_budget():
    lim = RateLimiter()
    rules = lambda mode: [(("g",), 5, 86400, "global", CALLS_CHARGED[mode]), (("ip",), 100, 86400, "ip")]  # noqa: E731
    lim.take(rules("deep"))          # 3 of 5
    lim.take(rules("fast"))          # 4 of 5
    with pytest.raises(HTTPException):
        lim.take(rules("deep"))      # would need 3 more: refused
    lim.take(rules("fast"))          # 5 of 5: still fits


def test_rejected_request_charges_nothing():
    lim = RateLimiter()
    lim.take([(("ip",), 1, 60, "ip")])                       # per-visitor limit now used up
    with pytest.raises(HTTPException):
        lim.take([(("g",), 10, 86400, "global", 3), (("ip",), 1, 60, "ip")])
    assert len(lim.windows[("g",)]) == 0                       # the global budget wasn't touched
