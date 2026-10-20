"""OpenAI adapter contract with a synthetic SDK, never network or real keys."""

from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.services.private_summaries import Credential, openai_provider


@pytest.mark.parametrize(
    "content,finish,valid",
    [
        ('{"topic":"uv"}', "stop", True),
        ('{"topic":"uv","topic":"cd"}', "stop", False),
        ('{"topic":"uv"}', "length", False),
    ],
)
def test_openai_adapter_byo_schema_and_no_retry(monkeypatch, content, finish, valid):
    import openai
    from app.services import crypto, outbound_guard

    calls = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs == dict(
                api_key="synthetic-tenant-key", timeout=20, max_retries=0
            )
            self.chat = SimpleNamespace(completions=self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=finish, message=SimpleNamespace(content=content)
                    )
                ]
            )

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setattr(outbound_guard, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(
        crypto,
        "decrypt_secret",
        lambda value: (
            "synthetic-tenant-key" if value == "synthetic-ciphertext" else None
        ),
    )
    credential = Credential(uuid4(), uuid4(), "gpt-5.6-luna", "synthetic-ciphertext")
    if valid:
        assert openai_provider(credential=credential, topics=("uv",)) == {"topic": "uv"}
    else:
        with pytest.raises(ValueError):
            openai_provider(credential=credential, topics=("uv",))
    assert len(calls) == 1
    assert calls[0]["max_completion_tokens"] == 512
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert calls[0]["response_format"]["json_schema"]["schema"]["properties"]["topic"][
        "enum"
    ] == ["uv"]


def test_global_gate_blocks_sdk(monkeypatch):
    from app.services import outbound_guard

    monkeypatch.setattr(outbound_guard, "external_sends_allowed", lambda: False)
    with pytest.raises(ValueError, match="external_gate_closed"):
        openai_provider(
            credential=Credential(uuid4(), uuid4(), "gpt-5.6-luna", "synthetic"),
            topics=("uv",),
        )
