import pickle

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from fridge.errors import AgentFailure, classify_failure


@pytest.mark.parametrize("status,code", [
    (400, "model_config"), (401, "model_auth"), (402, "model_balance"),
    (403, "model_auth"), (404, "model_config"), (422, "model_config"),
    (429, "model_rate_limit"), (500, "model_unavailable"), (503, "model_unavailable"),
])
def test_wrapped_provider_status_uses_only_allowlisted_messages(status, code):
    response = httpx.Response(status, request=httpx.Request("POST", "https://private.invalid"))
    provider = APIStatusError("secret-token-from-provider", response=response,
                              body={"private": "secret-token-from-provider"})
    wrapper = RuntimeError("another-private-message")
    wrapper.__cause__ = provider
    failure = classify_failure(wrapper)
    assert failure.code == code
    assert "private" not in str(failure)
    assert "secret" not in repr(failure)
    assert failure.args == (code,)
    assert pickle.loads(pickle.dumps(failure)).code == code


@pytest.mark.parametrize("timeout,code", [(True, "model_timeout"), (False, "model_connection")])
def test_timeout_and_connection_are_distinct_even_through_context(timeout, code):
    req = httpx.Request("POST", "https://private.invalid")
    provider = APITimeoutError(request=req) if timeout else APIConnectionError(request=req)
    wrapper = RuntimeError("private-provider-error")
    wrapper.__context__ = provider
    assert classify_failure(wrapper).code == code


def test_unknown_errors_and_untrusted_worker_codes_are_not_echoed():
    error = RuntimeError("token=secret-value")
    error.__context__ = error
    assert classify_failure(error).code == "unknown"
    for code in ["token=secret-value", {"secret": "value"}]:
        failure = AgentFailure(code)
        assert failure.code == "unknown"
        assert "secret" not in str(failure)


def test_worker_diagnostics_allow_only_bounded_fixed_counters():
    failure = AgentFailure("menu_incomplete", diagnostics={
        "steps": 6, "drafts": 2, "pairs": 1, "rejected": 3, "evaluated": 0,
        "token": "secret-value", "ingredients": ["private-input"],
    })
    assert classify_failure(failure).diagnostics == {
        "steps": 6, "drafts": 2, "pairs": 1, "rejected": 3, "evaluated": 0,
    }
    assert AgentFailure(diagnostics={"steps": True, "pairs": -1, "drafts": 200}).diagnostics == {}
    assert "secret" not in repr(failure)
