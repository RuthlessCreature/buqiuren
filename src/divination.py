from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

TRIGRAMS = {
    1: ("乾", "天", "☰"),
    2: ("兑", "泽", "☱"),
    3: ("离", "火", "☲"),
    4: ("震", "雷", "☳"),
    5: ("巽", "风", "☴"),
    6: ("坎", "水", "☵"),
    7: ("艮", "山", "☶"),
    8: ("坤", "地", "☷"),
}

HEXAGRAM_NAMES = [
    "乾为天","坤为地","水雷屯","山水蒙","水天需","天水讼","地水师","水地比",
    "风天小畜","天泽履","地天泰","天地否","天火同人","火天大有","地山谦","雷地豫",
    "泽雷随","山风蛊","地泽临","风地观","火雷噬嗑","山火贲","山地剥","地雷复",
    "天雷无妄","山天大畜","山雷颐","泽风大过","坎为水","离为火","泽山咸","雷风恒",
    "天山遁","雷天大壮","火地晋","地火明夷","风火家人","火泽睽","水山蹇","雷水解",
    "山泽损","风雷益","泽天夬","天风姤","泽地萃","地风升","泽水困","水风井",
    "泽火革","火风鼎","震为雷","艮为山","风山渐","雷泽归妹","雷火丰","火山旅",
    "巽为风","兑为泽","风水涣","水泽节","风泽中孚","雷山小过","水火既济","火水未济",
]

# King Wen sequence lookup by upper/lower trigram in binary line representation.
# Values are generated from the canonical 64-name sequence through this explicit table;
# keeping the table here avoids asking the language model to invent a hexagram name.
HEXAGRAM_BY_TRIGRAM = {
    (1,1):1,(8,8):2,(6,4):3,(7,6):4,(6,1):5,(1,6):6,(8,6):7,(6,8):8,
    (5,1):9,(1,2):10,(8,1):11,(1,8):12,(1,3):13,(3,1):14,(8,7):15,(4,8):16,
    (2,4):17,(7,5):18,(8,2):19,(5,8):20,(3,4):21,(7,3):22,(7,8):23,(8,4):24,
    (1,4):25,(7,1):26,(7,4):27,(2,5):28,(6,6):29,(3,3):30,(2,7):31,(4,5):32,
    (1,7):33,(4,1):34,(3,8):35,(8,3):36,(5,3):37,(3,2):38,(6,7):39,(4,6):40,
    (7,2):41,(5,4):42,(2,1):43,(1,5):44,(2,8):45,(8,5):46,(2,6):47,(6,5):48,
    (2,3):49,(3,5):50,(4,4):51,(7,7):52,(5,7):53,(4,2):54,(4,3):55,(3,7):56,
    (5,5):57,(2,2):58,(5,6):59,(6,2):60,(5,2):61,(4,7):62,(6,3):63,(3,6):64,
}


def _one_to_eight(value: int) -> int:
    mod = value % 8
    return 8 if mod == 0 else mod


def _one_to_six(value: int) -> int:
    mod = value % 6
    return 6 if mod == 0 else mod


def meihua_time_hexagram(now: datetime, salt: str = "") -> dict[str, Any]:
    """A deterministic 梅花易数 time-number auxiliary chart.

    Schools differ on exact numbering, lunar/solar conversion and hour-number rules.
    This implementation is intentionally labeled as a time-number auxiliary method,
    never as a replacement for the pinned bazi engine.
    """
    digest = int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8], 16) if salt else 0
    base = now.year + now.month + now.day
    upper_num = _one_to_eight(base)
    lower_num = _one_to_eight(base + now.hour + digest % 8)
    moving_line = _one_to_six(base + now.hour + now.minute + digest % 6)
    upper = TRIGRAMS[upper_num]
    lower = TRIGRAMS[lower_num]
    seq = HEXAGRAM_BY_TRIGRAM.get((upper_num, lower_num))
    return {
        "method": "梅花易数·时间数法（辅助）",
        "timestamp": now.isoformat(),
        "upper": {"name": upper[0], "image": upper[1], "symbol": upper[2], "number": upper_num},
        "lower": {"name": lower[0], "image": lower[1], "symbol": lower[2], "number": lower_num},
        "hexagram_number": seq,
        "hexagram_name": HEXAGRAM_NAMES[seq - 1] if seq else None,
        "moving_line": moving_line,
        "warning": "梅花起卦法门派差异明显。本结果仅作为问事辅助信息，不可覆盖八字原盘事实。",
    }


def method_router(user_text: str) -> dict[str, Any]:
    text = user_text or ""
    result = {
        "bazi": True,
        "meihua": False,
        "zhouyi": False,
        "qimen": False,
        "ziwei": False,
        "reason": [],
    }
    if any(k in text for k in ("什么时候", "能不能", "会不会", "选哪个", "选择", "成不成", "今日", "今天", "近期", "结果")):
        result["meihua"] = True
        result["zhouyi"] = True
        result["reason"].append("问题包含时点、结果或选择型语义")
    if any(k in text for k in ("奇门", "方位", "出行", "谈判", "时间局", "择时")):
        result["qimen"] = True
        result["reason"].append("用户明确涉及奇门/方位/择时")
    if any(k in text for k in ("紫微", "命宫", "夫妻宫", "官禄宫", "迁移宫")):
        result["ziwei"] = True
        result["reason"].append("用户明确涉及紫微斗数宫位")
    return result


def auxiliary_context(user_text: str, now: datetime, seed: str) -> dict[str, Any]:
    route = method_router(user_text)
    ctx: dict[str, Any] = {"route": route}
    if route["meihua"] or route["zhouyi"]:
        ctx["meihua"] = meihua_time_hexagram(now, seed)
    if route["qimen"]:
        ctx["qimen"] = {
            "status": "not_calculated",
            "instruction": "当前版本没有接入经过验证的奇门排盘引擎。不得自行编造九宫、九星、八门、九神、值符值使。可讨论方法论，不能假装已排局。",
        }
    if route["ziwei"]:
        ctx["ziwei"] = {
            "status": "not_calculated",
            "instruction": "当前版本没有接入经过验证的紫微斗数排盘引擎。不得自行编造命宫、主星、四化或宫位落点。",
        }
    return ctx
