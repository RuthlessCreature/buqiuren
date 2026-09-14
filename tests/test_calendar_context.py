from datetime import datetime, timedelta, timezone

from calendar_context import CALENDAR_ENGINE, resolve_calendar_context
from divination import auxiliary_context


def _now_1986_05_29():
    return datetime(1986, 5, 29, 10, 30, tzinfo=timezone(timedelta(hours=8)))


def test_relative_today_uses_lunar_python_day_ganzhi():
    ctx = resolve_calendar_context("今天这个癸酉日对我有什么影响？", _now_1986_05_29())
    assert ctx["status"] == "resolved"
    assert ctx["engine"] == CALENDAR_ENGINE
    today = next(x for x in ctx["dates"] if x["expression"] == "今天")
    assert today["solar_date"] == "1986-05-29"
    # 6tail/lunar-python README public fixture: 1986-05-29 is 癸酉日.
    assert today["day_ganzhi"] == "癸酉"
    assert "year_ganzhi" not in today
    assert "month_ganzhi" not in today


def test_explicit_solar_date_is_calculated_not_guessed():
    ctx = resolve_calendar_context("看一下1986-05-29这一天", _now_1986_05_29())
    assert ctx["status"] == "resolved"
    fact = ctx["dates"][0]
    assert fact["solar_date"] == "1986-05-29"
    assert fact["day_ganzhi"] == "癸酉"


def test_explicit_lunar_date_converts_before_reasoning():
    ctx = resolve_calendar_context("农历1986年4月21日是什么日子", _now_1986_05_29())
    assert ctx["status"] == "resolved"
    fact = ctx["dates"][0]
    assert fact["source"] == "explicit_lunar"
    assert fact["solar_date"] == "1986-05-29"
    assert fact["day_ganzhi"] == "癸酉"


def test_month_day_without_year_uses_current_local_year():
    now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    ctx = resolve_calendar_context("9月14日适不适合签约", now)
    fact = ctx["dates"][0]
    assert fact["solar_date"] == "2026-09-14"
    assert "2026" in fact["assumption"]


def test_invalid_date_is_unresolved_and_model_must_not_fill_it():
    ctx = resolve_calendar_context("看看2026年2月31日的日柱", _now_1986_05_29())
    assert ctx["status"] == "unresolved"
    assert ctx["dates"] == []
    assert ctx["errors"]
    assert "不得凭语言模型知识猜一个干支" in ctx["instruction"]


def test_no_date_does_not_inject_fake_day():
    ctx = resolve_calendar_context("帮我看事业大运", _now_1986_05_29())
    assert ctx["status"] == "not_needed"
    assert ctx["dates"] == []


def test_auxiliary_context_always_carries_calendar_guard():
    ctx = auxiliary_context("昨天发生的事怎么看", _now_1986_05_29(), "fixture")
    assert ctx["calendar"]["status"] == "resolved"
    yesterday = next(x for x in ctx["calendar"]["dates"] if x["expression"] == "昨天")
    assert yesterday["solar_date"] == "1986-05-28"
