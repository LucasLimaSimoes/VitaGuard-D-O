from vitaguard_do.extraction.provider import (
    _is_fatal_configuration_error,
    _is_transient_error,
    _retry_after_seconds,
)


def test_high_demand_503_is_transient():
    exc = RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand")
    assert _is_transient_error(exc)


def test_rate_limit_is_transient():
    exc = RuntimeError("429 RESOURCE_EXHAUSTED: rate limit")
    assert _is_transient_error(exc)


def test_free_tier_quota_message_is_transient_not_fatal():
    exc = RuntimeError(
        "You exceeded your current quota, please check your plan and billing details. "
        "Quota exceeded for metric free_tier_requests, limit: 5. Please retry in 13.951991657s."
    )
    assert _is_transient_error(exc)
    assert not _is_fatal_configuration_error(exc)


def test_retry_after_seconds_is_parsed():
    exc = RuntimeError("Please retry in 13.951991657s.")
    assert abs(_retry_after_seconds(exc) - 13.951991657) < 1e-9


def test_invalid_key_is_fatal():
    exc = RuntimeError("API key not valid")
    assert _is_fatal_configuration_error(exc)
