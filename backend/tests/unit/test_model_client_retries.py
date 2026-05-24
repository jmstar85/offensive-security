"""Unit tests for ModelClient retry behavior (plan v3.2.1 §1.2)."""
from unittest.mock import MagicMock

import anthropic
import pytest

from app.orchestrator.model_client import ModelClient, ModelUnreachable


class _FakeUsage:
    def __init__(self, ti=0, to=0):
        self.input_tokens = ti
        self.output_tokens = to


class _FakeContent:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text="ok", ti=10, to=5):
        self.content = [_FakeContent(text)]
        self.usage = _FakeUsage(ti, to)


def _make_client_with_create(create_side_effect):
    client = ModelClient(api_key="dummy")
    client._client = MagicMock()
    client._client.messages = MagicMock()
    client._client.messages.create = MagicMock(side_effect=create_side_effect)
    client._backoff = [0.0, 0.0, 0.0]
    return client


@pytest.mark.asyncio
async def test_send_succeeds_first_try():
    client = _make_client_with_create([_FakeMessage("hello", 12, 8)])
    res = await client.send(model_id="claude-sonnet-4-6", messages=[{"role": "user", "content": "x"}], system="s")
    assert res.text == "hello"
    assert res.tokens_in == 12
    assert res.tokens_out == 8
    assert client._client.messages.create.call_count == 1


def _make_5xx() -> anthropic.APIStatusError:
    return anthropic.APIStatusError(
        message="server error",
        response=MagicMock(status_code=503),
        body={"error": {"type": "overloaded_error"}},
    )


@pytest.mark.asyncio
async def test_send_retries_on_5xx_then_succeeds():
    client = _make_client_with_create([_make_5xx(), _FakeMessage("recovered")])
    res = await client.send(model_id="claude-sonnet-4-6", messages=[{"role": "user", "content": "x"}], system="s")
    assert res.text == "recovered"
    assert client._client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_send_raises_model_unreachable_after_max_attempts():
    client = _make_client_with_create([_make_5xx(), _make_5xx(), _make_5xx()])
    with pytest.raises(ModelUnreachable):
        await client.send(
            model_id="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "x"}],
            system="s",
        )
    assert client._client.messages.create.call_count == 3


@pytest.mark.asyncio
async def test_send_does_not_retry_on_4xx():
    err = anthropic.APIStatusError(
        message="bad request",
        response=MagicMock(status_code=400),
        body={"error": {"type": "invalid_request_error"}},
    )
    client = _make_client_with_create([err])
    with pytest.raises(anthropic.APIStatusError):
        await client.send(
            model_id="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "x"}],
            system="s",
        )
    assert client._client.messages.create.call_count == 1
