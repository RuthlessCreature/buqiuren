from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from bazi_adapter import ProfileInput, build_chart
from divination import auxiliary_context
from minimax import chat
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
    result = await chat(
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
    )

    if result.model != "MiniMax-M3":
        raise AssertionError(f"unexpected model: {result.model}")
    if not result.reasoning or not result.reasoning.strip():
        raise AssertionError("thinking/reasoning missing")
    if not result.content or not result.content.strip():
        raise AssertionError("assistant content missing")
    for pillar in ("辛未", "庚子", "癸酉", "乙卯"):
        if pillar not in result.content:
            raise AssertionError(f"expected pillar {pillar} missing from response: {result.content}")

    print("MiniMax live probe PASS")
    print("model:", result.model)
    print("reasoning_chars:", len(result.reasoning))
    print("answer_chars:", len(result.content))
    print("usage:", result.raw_usage or {})


if __name__ == "__main__":
    asyncio.run(main())
