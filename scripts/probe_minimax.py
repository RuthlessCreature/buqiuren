from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from bazi_adapter import ProfileInput, build_chart
from divination import auxiliary_context
from minimax import stream_chat
from prompts import attachment_instruction, build_case_context, build_system_prompt


async def main() -> None:
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        raise SystemExit("MINIMAX_API_KEY missing")

    profile = ProfileInput(
        display_name="E2E",
        gender="male",
        calendar_type="solar",
        birth_year=1991,
        birth_month=12,
        birth_day=29,
        birth_hour=6,
        birth_hour_unknown=False,
        leap_month=False,
    )
    chart = build_chart(profile)
    profile_row = {
        "display_name": "E2E",
        "gender": "male",
        "calendar_type": "solar",
        "birth_year": 1991,
        "birth_month": 12,
        "birth_day": 29,
        "birth_hour": 6,
        "birth_hour_unknown": 0,
        "leap_month": 0,
    }
    question = "请只返回四柱和日主，不要展开。"
    auxiliary = auxiliary_context(question, datetime.now(timezone.utc), "ci-e2e")

    reasoning_parts: list[str] = []
    content_parts: list[str] = []
    final = None
    async for event in stream_chat(
        api_key=api_key,
        base_url="https://api.minimaxi.com/v1",
        model="MiniMax-M3",
        system_prompt=build_system_prompt(),
        case_context=build_case_context(profile_row, chart, auxiliary),
        history=[],
        user_text=question,
        media=[],
        attachment_note=attachment_instruction([]),
        timeout_seconds=180.0,
    ):
        if event.get("type") == "reasoning":
            reasoning_parts.append(event.get("delta") or "")
        elif event.get("type") == "content":
            content_parts.append(event.get("delta") or "")
        elif event.get("type") == "done":
            final = event.get("result")

    reasoning = "".join(reasoning_parts)
    content = "".join(content_parts)
    if final is None:
        raise AssertionError("stream did not produce done event")
    if final.model != "MiniMax-M3":
        raise AssertionError(f"unexpected model: {final.model}")
    if not reasoning.strip() or not final.reasoning or not final.reasoning.strip():
        raise AssertionError("streaming thinking/reasoning missing")
    if not content.strip() or not final.content or not final.content.strip():
        raise AssertionError("streaming assistant content missing")
    if content.strip() != final.content.strip():
        raise AssertionError("streamed content does not match final accumulated content")
    for pillar in ("辛未", "庚子", "癸酉", "乙卯"):
        if pillar not in final.content:
            raise AssertionError(f"expected pillar {pillar} missing from response: {final.content}")

    print("MiniMax streaming live probe PASS")
    print("model:", final.model)
    print("reasoning_events:", len(reasoning_parts))
    print("content_events:", len(content_parts))
    print("reasoning_chars:", len(reasoning))
    print("answer_chars:", len(content))
    print("usage:", final.raw_usage or {})


if __name__ == "__main__":
    asyncio.run(main())
