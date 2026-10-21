"""MiniMax M3.1 Flash request and streaming compatibility tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import minimax


def test_m31_default_and_reasoning_payload():
    assert minimax.DEFAULT_MODEL == "MiniMax-M3.1-Flash"
    data = minimax._payload(model=minimax.DEFAULT_MODEL, messages=[], stream=True)
    assert data["model"] == "MiniMax-M3.1-Flash"
    assert data["reasoning_effort"] == "max"
    assert data["reasoning_split"] is True
    assert "thinking" not in data
    assert data["stream_options"]["include_usage"] is True
    assert data["max_completion_tokens"] >= 16000
    assert 'MINIMAX_MODEL = "MiniMax-M3.1-Flash"' in Path("wrangler.toml.example").read_text()


def test_legacy_m3_compatibility_remains_available():
    data = minimax._payload(model="MiniMax-M3", messages=[], stream=False)
    assert data["thinking"] == {"type": "adaptive"}
    assert data["reasoning_split"] is True
    assert "reasoning_effort" not in data


def test_m31_reasoning_content_stream(monkeypatch):
    chunks = [
        {"model": minimax.DEFAULT_MODEL, "choices": [{"delta": {"reasoning_content": "甲"}}]},
        {"model": minimax.DEFAULT_MODEL, "choices": [{"delta": {"reasoning_content": "甲乙"}}]},
        {"model": minimax.DEFAULT_MODEL, "choices": [{"delta": {"content": "论"}}]},
        {"model": minimax.DEFAULT_MODEL, "choices": [{"delta": {"content": "论命"}}]},
        {"model": minimax.DEFAULT_MODEL, "usage": {"prompt_tokens": 7, "completion_tokens": 11}, "choices": []},
    ]

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            for item in chunks:
                yield "data: " + json.dumps(item)
            yield "data: [DONE]"

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, method, url, headers, json):
            assert method == "POST"
            assert url == "https://api.minimaxi.com/v1/chat/completions"
            assert json["model"] == minimax.DEFAULT_MODEL
            assert json["reasoning_effort"] == "max"
            return FakeStream()

    monkeypatch.setattr(minimax.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    async def collect():
        return [event async for event in minimax.stream_chat(
            api_key="test-key", base_url="https://api.minimaxi.com/v1",
            model=minimax.DEFAULT_MODEL, system_prompt="system",
            case_context="context", history=[], user_text="question",
            media=[], attachment_note="none",
        )]

    events = asyncio.run(collect())
    assert [event["delta"] for event in events if event["type"] == "reasoning"] == ["甲", "乙"]
    assert [event["delta"] for event in events if event["type"] == "content"] == ["论", "命"]
    done = events[-1]["result"]
    assert done.content == "论命"
    assert done.reasoning == "甲乙"
    assert done.model == minimax.DEFAULT_MODEL
    assert done.prompt_tokens == 7
    assert done.completion_tokens == 11
