from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BAZI_ENGINE_COMMIT = "33b18354d5407727640e545c3aaec0efb4bf5282"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PILLARS_RE = re.compile(r"(?:lunar_python:|四柱：)\s*([甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥])\s+([甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥])\s+([甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥])\s+([甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥])")


@dataclass(frozen=True)
class ProfileInput:
    display_name: str
    gender: str
    calendar_type: str
    birth_year: int
    birth_month: int
    birth_day: int
    birth_hour: int | None
    birth_hour_unknown: bool
    leap_month: bool = False

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ProfileInput":
        return cls(
            display_name=str(row["display_name"]),
            gender=str(row["gender"]),
            calendar_type=str(row["calendar_type"]),
            birth_year=int(row["birth_year"]),
            birth_month=int(row["birth_month"]),
            birth_day=int(row["birth_day"]),
            birth_hour=None if row.get("birth_hour") is None else int(row["birth_hour"]),
            birth_hour_unknown=bool(row["birth_hour_unknown"]),
            leap_month=bool(row.get("leap_month", 0)),
        )


def profile_fingerprint(profile: ProfileInput) -> str:
    payload = json.dumps(profile.__dict__, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _local_vendor_dir() -> Path:
    configured = os.environ.get("BAZI_VENDOR_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "python_modules" / "buqiuren_bazi"


def _ensure_bazi_importable() -> None:
    """Expose the vendored upstream directory in ordinary CPython tests.

    Cloudflare processes `python_modules/buqiuren_bazi.pth` at Worker startup, so
    deployed Workers already have this directory on sys.path. Local pytest does
    not process that project-local .pth file, therefore we add the physical path
    only when it exists.
    """
    vendor = _local_vendor_dir()
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    if importlib.util.find_spec("bazi") is None:
        raise RuntimeError(
            "固定版本 china-testing/bazi 未打包；先运行 `uv run pywrangler sync`，再运行 scripts/vendor_bazi.sh"
        )


def _run_upstream(profile: ProfileInput, hour: int) -> str:
    _ensure_bazi_importable()
    argv = [
        "bazi.py",
        str(profile.birth_year),
        str(profile.birth_month),
        str(profile.birth_day),
        str(hour),
    ]
    if profile.calendar_type == "solar":
        argv.append("-g")
    elif profile.leap_month:
        argv.append("-r")
    if profile.gender == "female":
        argv.append("-n")

    previous_argv = sys.argv[:]
    buffer = io.StringIO()
    try:
        sys.argv = argv
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            # Execute the upstream module itself. We do not copy/reimplement its
            # chart logic; python_modules + .pth makes its original absolute
            # sibling imports (datas/sizi/common/yue/...) resolve unchanged.
            runpy.run_module("bazi", run_name="__main__", alter_sys=False)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f"bazi 排盘失败，退出码 {exc.code}: {buffer.getvalue()[-1000:]}") from exc
    finally:
        sys.argv = previous_argv

    output = ANSI_RE.sub("", buffer.getvalue()).strip()
    if not output:
        raise RuntimeError("bazi 排盘无输出")
    return output


def _pillars(raw: str) -> list[str]:
    match = PILLARS_RE.search(raw)
    return list(match.groups()) if match else []


def build_chart(profile: ProfileInput) -> dict[str, Any]:
    """Run the pinned upstream bazi.py without reimplementing its chart algorithm.

    If birth hour is unknown, evaluate all 12 traditional two-hour branches using
    representative civil hours. The assistant must only treat conclusions shared
    across candidates as hour-invariant and must label hour-sensitive claims.
    """
    base = {
        "engine": "china-testing/bazi",
        "engine_commit": BAZI_ENGINE_COMMIT,
        "profile_fingerprint": profile_fingerprint(profile),
        "calendar_type": profile.calendar_type,
        "gender": profile.gender,
        "birth": {
            "year": profile.birth_year,
            "month": profile.birth_month,
            "day": profile.birth_day,
            "hour": profile.birth_hour,
            "hour_unknown": profile.birth_hour_unknown,
            "leap_month": profile.leap_month,
        },
    }

    if not profile.birth_hour_unknown:
        if profile.birth_hour is None or not 0 <= profile.birth_hour <= 23:
            raise ValueError("已知时辰时，小时必须为 0–23")
        raw = _run_upstream(profile, profile.birth_hour)
        pillars = _pillars(raw)
        if len(pillars) != 4:
            raise RuntimeError("无法从固定版本 bazi 输出中识别四柱；拒绝由模型补算")
        return {
            **base,
            "mode": "four_pillars",
            "pillars": pillars,
            "raw_output": raw,
            "method_note": "四柱及后续关系均直接来自固定版本 china-testing/bazi 的运行输出。",
        }

    candidates: list[dict[str, Any]] = []
    representative_hours = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
    branches = list("子丑寅卯辰巳午未申酉戌亥")
    for branch, hour in zip(branches, representative_hours):
        raw = _run_upstream(profile, hour)
        pillars = _pillars(raw)
        if len(pillars) != 4:
            raise RuntimeError(f"无法识别{branch}时候选四柱；拒绝由模型补算")
        candidates.append(
            {
                "shichen": branch,
                "representative_hour": hour,
                "pillars": pillars,
                "upstream_excerpt": raw[:9000],
            }
        )

    invariant = []
    candidate_pillars = [c["pillars"] for c in candidates]
    for i in range(3):
        values = {p[i] for p in candidate_pillars}
        if len(values) == 1:
            invariant.append(next(iter(values)))

    return {
        **base,
        "mode": "unknown_hour_12_candidates",
        "invariant_first_three_pillars": invariant,
        "candidates": candidates,
        "method_note": (
            "用户未知出生时辰。系统没有伪造时柱，而是用固定版本 china-testing/bazi "
            "分别计算十二时辰候选。仅前三柱与各候选共同支持的判断可视为时辰不敏感；"
            "婚姻、子女、晚运、部分格局/神煞/大运细节若依赖时柱，必须明确标注不确定。"
        ),
    }


def chart_prompt_text(chart: dict[str, Any], max_chars: int = 120_000) -> str:
    text = json.dumps(chart, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[命盘上下文因长度限制截断；不得据截断部分臆造事实]"
