from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from lunar_python import Lunar, Solar

CALENDAR_ENGINE = "6tail/lunar-python"
CALENDAR_ENGINE_VERSION = "1.4.8"

RELATIVE_DAYS = {
    "前天": -2,
    "昨天": -1,
    "昨日": -1,
    "今天": 0,
    "今日": 0,
    "明天": 1,
    "明日": 1,
    "后天": 2,
}

LUNAR_YMD_RE = re.compile(
    r"(?:农历|阴历)\s*(?P<year>\d{4})\s*年\s*(?P<leap>闰)?\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]?"
)
SOLAR_YMD_CN_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]?"
)
SOLAR_YMD_SEP_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)"
)
SOLAR_MD_CN_RE = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号](?!\d)"
)
DATE_HINT_RE = re.compile(
    r"今天|今日|昨天|昨日|前天|明天|明日|后天|农历|阴历|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
)


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < used_end and end > used_start for used_start, used_end in occupied)


def _solar_fact(solar: Solar, expression: str, source: str, assumption: str | None = None) -> dict[str, Any]:
    lunar = solar.getLunar()
    item: dict[str, Any] = {
        "expression": expression,
        "source": source,
        "solar_date": solar.toYmd(),
        "lunar_date": lunar.toString(),
        "day_ganzhi": lunar.getDayInGanZhi(),
        "engine": CALENDAR_ENGINE,
        "engine_version": CALENDAR_ENGINE_VERSION,
    }
    if assumption:
        item["assumption"] = assumption
    return item


def _solar_from_date(d: date) -> Solar:
    return Solar.fromYmd(d.year, d.month, d.day)


def _append_unique(items: list[dict[str, Any]], fact: dict[str, Any]) -> None:
    key = (fact.get("solar_date"), fact.get("source"))
    if not any((x.get("solar_date"), x.get("source")) == key for x in items):
        items.append(fact)


def resolve_calendar_context(user_text: str, now: datetime) -> dict[str, Any]:
    """Resolve date words into deterministic calendrical facts before LLM reasoning.

    The language model must never calculate Gregorian/lunar conversion or GanZhi on
    its own. This function only resolves date expressions present in the current
    user turn, so an old historical word such as “今天” is never reinterpreted on a
    later day.
    """
    text = user_text or ""
    current_date = now.date()
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    occupied: list[tuple[int, int]] = []

    # Explicit lunar dates first so the numeric part is not double-read as solar.
    for match in LUNAR_YMD_RE.finditer(text):
        occupied.append(match.span())
        expression = match.group(0)
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        if match.group("leap"):
            month = -month
        try:
            lunar = Lunar.fromYmd(year, month, day)
            _append_unique(items, _solar_fact(lunar.getSolar(), expression, "explicit_lunar"))
        except Exception as exc:
            errors.append({"expression": expression, "error": f"农历日期无法解析：{exc}"})

    for pattern, source in (
        (SOLAR_YMD_CN_RE, "explicit_solar"),
        (SOLAR_YMD_SEP_RE, "explicit_solar"),
    ):
        for match in pattern.finditer(text):
            if _overlaps(match.span(), occupied):
                continue
            occupied.append(match.span())
            expression = match.group(0)
            try:
                solar = Solar.fromYmd(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
                _append_unique(items, _solar_fact(solar, expression, source))
            except Exception as exc:
                errors.append({"expression": expression, "error": f"公历日期无法解析：{exc}"})

    # Month/day without a year is interpreted in the current local calendar year.
    for match in SOLAR_MD_CN_RE.finditer(text):
        if _overlaps(match.span(), occupied):
            continue
        occupied.append(match.span())
        expression = match.group(0)
        try:
            solar = Solar.fromYmd(current_date.year, int(match.group("month")), int(match.group("day")))
            _append_unique(
                items,
                _solar_fact(
                    solar,
                    expression,
                    "explicit_solar_without_year",
                    assumption=f"用户未写年份，按当前时区参考年份 {current_date.year} 解析",
                ),
            )
        except Exception as exc:
            errors.append({"expression": expression, "error": f"日期无法解析：{exc}"})

    for expression, offset in RELATIVE_DAYS.items():
        if expression not in text:
            continue
        target = current_date + timedelta(days=offset)
        _append_unique(items, _solar_fact(_solar_from_date(target), expression, "relative_day"))

    status = "resolved" if items else ("unresolved" if DATE_HINT_RE.search(text) else "not_needed")
    return {
        "status": status,
        "engine": CALENDAR_ENGINE,
        "engine_version": CALENDAR_ENGINE_VERSION,
        "timezone": str(now.tzinfo) if now.tzinfo else "unknown",
        "reference_now": now.isoformat(),
        "reference_date": current_date.isoformat(),
        "dates": items,
        "errors": errors,
        "instruction": (
            "以上日期、公农历转换及日干支均由 6tail/lunar-python 程序计算。"
            "模型只允许基于这些结果做命理推理与解释，禁止自行心算、补算或改写日干支。"
            "若用户问到的日期没有出现在 dates 中，或 status=unresolved，必须说明缺少可计算的明确日期，"
            "不得凭语言模型知识猜一个干支。"
        ),
    }
