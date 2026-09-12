from datetime import datetime, timezone

from bazi_adapter import BAZI_ENGINE_COMMIT, ProfileInput, build_chart
from divination import auxiliary_context, meihua_time_hexagram, method_router
from minimax import _cumulative_delta, build_messages
from prompts import build_system_prompt
from security import hash_password, verify_password


def test_password_round_trip():
    encoded = hash_password("correct-horse-123", "x" * 40)
    assert verify_password("correct-horse-123", encoded, "x" * 40)
    assert not verify_password("wrong-password", encoded, "x" * 40)


def test_upstream_bazi_readme_example():
    # Public fixture from china-testing/bazi README:
    # python bazi.py 1977 8 11 19 -n  (lunar, female)
    p = ProfileInput(
        display_name="fixture",
        gender="female",
        calendar_type="lunar",
        birth_year=1977,
        birth_month=8,
        birth_day=11,
        birth_hour=19,
        birth_hour_unknown=False,
        leap_month=False,
    )
    chart = build_chart(p)
    assert chart["engine_commit"] == BAZI_ENGINE_COMMIT
    assert chart["mode"] == "four_pillars"
    assert chart["pillars"] == ["丁巳", "己酉", "癸未", "壬戌"]


def test_unknown_hour_keeps_twelve_candidates():
    p = ProfileInput(
        display_name="fixture",
        gender="male",
        calendar_type="solar",
        birth_year=2000,
        birth_month=1,
        birth_day=1,
        birth_hour=None,
        birth_hour_unknown=True,
    )
    chart = build_chart(p)
    assert chart["mode"] == "unknown_hour_12_candidates"
    assert len(chart["candidates"]) == 12
    assert [x["shichen"] for x in chart["candidates"]] == list("子丑寅卯辰巳午未申酉戌亥")


def test_multimodal_history_is_rehydrated():
    messages = build_messages(
        "system",
        "case",
        [
            {
                "role": "user",
                "content": "看这张图",
                "attachments": [
                    {"media_kind": "image", "signed_url": "https://example.test/signed.jpg"}
                ],
            },
            {"role": "assistant", "content": "上一轮回答"},
        ],
        "第二张呢？",
        [{"media_kind": "image", "signed_url": "https://example.test/second.jpg"}],
        "two images",
    )
    old_user = messages[2]
    assert old_user["role"] == "user"
    assert any(p.get("type") == "image_url" for p in old_user["content"])
    current = messages[-1]
    assert any(p.get("type") == "image_url" for p in current["content"])


def test_divination_router_does_not_fake_qimen_or_ziwei():
    ctx = auxiliary_context("用奇门和紫微看看这次谈判什么时候成", datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc), "fixture")
    assert ctx["route"]["qimen"] is True
    assert ctx["route"]["ziwei"] is True
    assert ctx["qimen"]["status"] == "not_calculated"
    assert ctx["ziwei"]["status"] == "not_calculated"


def test_meihua_is_deterministic_for_same_input():
    now = datetime(2026, 9, 12, 10, 8, tzinfo=timezone.utc)
    assert meihua_time_hexagram(now, "same") == meihua_time_hexagram(now, "same")
    assert method_router("我今天谈判能不能成")["meihua"] is True


def test_minimax_cumulative_stream_delta():
    full, delta = _cumulative_delta("", "天")
    assert full == "天"
    assert delta == "天"
    full, delta = _cumulative_delta(full, "天地")
    assert full == "天地"
    assert delta == "地"
    full, delta = _cumulative_delta(full, "天地玄黄")
    assert full == "天地玄黄"
    assert delta == "玄黄"


def test_oracle_prompt_is_long_form_but_grounded():
    prompt = build_system_prompt()
    assert "站在山上看江河改道" in prompt
    assert "1500–2800" in prompt
    assert "真正老练的命师不靠胡编显本事" in prompt
    assert "不得写成确定事实" in prompt
    assert "Markdown" in prompt
