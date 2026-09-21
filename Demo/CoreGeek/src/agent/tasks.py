from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .jobs import Job, update_fail_streaks
from .protocol import Pos, Unit
from .world import World, backpack_item, count_item

ITEM_ALIASES = {
    "古符石板": "AcientTablet",
    "星辰之沙": "StarSand",
    "烈焰之息": "FlameBreath",
    "寒霜药剂": "FrostPotion",
    "荆棘护符": "ThornAmulet",
    "回音铁哨": "IronWhistle",
    "acienttablet": "AcientTablet",
    "starsand": "StarSand",
    "flamebreath": "FlameBreath",
    "frostpotion": "FrostPotion",
    "thornamulet": "ThornAmulet",
    "ironwhistle": "IronWhistle",
}

LLM_PER_DAY = 3


@dataclass
class Memory:
    last_round: int = 0
    day: int = 0
    llm_used: int = 0
    folk: list[str] = field(default_factory=list)
    official: list[str] = field(default_factory=list)
    treasure_done: bool = False
    treasure_pos: Pos | None = None
    treasure_items: tuple[str, ...] = ()
    treasure_day: int | None = None
    task_step: int = 0
    last_task: str = ""
    pending_answer: str = ""
    jobs: dict[int, Job] = field(default_factory=dict)
    roles: dict[int, str] = field(default_factory=dict)


MEMORY = Memory()


def observe(turn: World) -> Memory:
    memory = MEMORY
    if turn.day_index != memory.day:
        memory.day = turn.day_index
        memory.llm_used = 0
    if turn.round_no < memory.last_round:
        memory.task_step = 0
        memory.last_task = ""
        memory.pending_answer = ""
        memory.jobs.clear()
        memory.roles.clear()
    memory.last_round = turn.round_no
    update_fail_streaks(turn, memory)
    if turn.llm_limited():
        memory.llm_used = LLM_PER_DAY
    if turn.folk_legends and (
        not memory.folk or memory.folk[-1] != turn.folk_legends
    ):
        memory.folk.append(turn.folk_legends)
    if turn.official_news and (
        not memory.official or memory.official[-1] != turn.official_news
    ):
        memory.official.append(turn.official_news)
    if turn.last_summon in (1, 4):
        memory.treasure_done = True
    if turn.phase_task != memory.last_task:
        memory.last_task = turn.phase_task
        memory.task_step = 0
        memory.pending_answer = ""
    _absorb_llm(turn, memory)
    return memory


def can_prompt(turn: World, memory: Memory) -> bool:
    if turn.phase_task:
        return True
    return memory.llm_used < LLM_PER_DAY and not turn.llm_limited()


def mark_prompt(turn: World, memory: Memory) -> None:
    if not turn.phase_task:
        memory.llm_used += 1


def treasure_prompt(turn: World, memory: Memory) -> str:
    shop = ", ".join(item.name for item in turn.weapon_shop)
    folk = "\n".join(f"DAY{index + 1}: {text}" for index, text in enumerate(memory.folk))
    return (
        "你在解析《未来战争》民间传闻以开启祭坛宝藏。"
        "只输出一行 JSON，不要解释："
        '{"x":数字,"y":数字,"items":["英文物品名"],"day":数字或null,"ready":是否现在可开}。'
        "物品名必须来自商店英文名，不能多也不能少。"
        f" 地图宽{turn.width}高{turn.height}，当前第{turn.day_index}天第{turn.round_no}回合。"
        f" 上回合召唤结果码={turn.last_summon}（0未探测1成功2位置或时间不对3物品错误4已空）。"
        f" 商店：{shop}。传闻：\n{folk}"
    )


def task_prompt(turn: World) -> str:
    return (
        "你在沙盒中做自进化任务。沙盒无外网，可执行 shell / python，时限15秒。"
        "只输出一行 JSON："
        '{"executeCmd":"下一条命令","taskAnswer":"若已得到最终答案则填写否则空字符串"}。'
        "优先根据任务原文和上次命令输出推进，不要重复失败命令。"
        f"\n【任务】\n{turn.phase_task}\n【上次命令输出】\n{turn.last_cmd_result}"
    )


def parse_llm_json(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def next_task_command(turn: World, memory: Memory) -> tuple[str, str]:
    parsed = parse_llm_json(turn.llm_resp)
    execute = str(parsed.get("executeCmd") or "").strip()
    answer = str(parsed.get("taskAnswer") or "").strip()
    if answer:
        memory.pending_answer = answer
    if execute or answer:
        memory.task_step += 1
        return execute, answer
    if memory.pending_answer and turn.last_cmd_result:
        return "", memory.pending_answer
    command = _fallback_cmd(turn, memory)
    memory.task_step += 1
    return command, ""


def _fallback_cmd(turn: World, memory: Memory) -> str:
    step = memory.task_step
    if step == 0:
        payload = json.dumps(turn.phase_task, ensure_ascii=False)
        return (
            "python3 -c "
            + json.dumps(
                "open('/tmp/phase_task.txt','w',encoding='utf-8').write("
                + payload
                + "); print('saved', len(open('/tmp/phase_task.txt',encoding='utf-8').read()))"
            )
        )
    if step == 1:
        return "pwd; ls -la; find . -maxdepth 3 -type f | head -80"
    if step == 2:
        return (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "task=Path('/tmp/phase_task.txt').read_text(encoding='utf-8',errors='ignore') "
            "if Path('/tmp/phase_task.txt').exists() else ''\n"
            "print(task[:4000])\n"
            "for path in Path('.').rglob('*'):\n"
            "    if path.is_file() and path.stat().st_size<200000:\n"
            "        print('FILE', path)\n"
            "PY"
        )
    if turn.last_cmd_result:
        output = _cmd_body(turn.last_cmd_result).strip()
        if output and len(output) < 4000:
            memory.pending_answer = output.splitlines()[-1][:500]
    return "python3 -c \"print(open('/tmp/phase_task.txt',encoding='utf-8').read()[:2000])\""


def _cmd_body(raw: str) -> str:
    lines = raw.splitlines()
    if lines and lines[0].startswith("[") and lines[0].endswith("]"):
        return "\n".join(lines[1:])
    return raw


def missing_treasure_items(role: Unit, items: tuple[str, ...]) -> tuple[str, ...]:
    missing = []
    used: dict[str, int] = {}
    for name in items:
        have = count_item(role, name) - used.get(name.lower(), 0)
        if have <= 0:
            missing.append(name)
        else:
            used[name.lower()] = used.get(name.lower(), 0) + 1
    return tuple(missing)


def consume_names(role: Unit, items: tuple[str, ...]) -> tuple[str, ...]:
    names = []
    for name in items:
        actual = backpack_item(role, name)
        names.append(actual or name)
    return tuple(names)


def _absorb_llm(turn: World, memory: Memory) -> None:
    data = parse_llm_json(turn.llm_resp)
    if not data:
        _heuristic_treasure(turn, memory)
        return
    if "x" in data and "y" in data:
        try:
            memory.treasure_pos = Pos(int(data["x"]), int(data["y"]))
        except (TypeError, ValueError):
            pass
    raw_items = data.get("items") or []
    if isinstance(raw_items, list):
        mapped = tuple(
            _canonical_item(str(name), turn) for name in raw_items if str(name)
        )
        mapped = tuple(name for name in mapped if name)
        if mapped:
            memory.treasure_items = mapped
    day = data.get("day")
    if isinstance(day, int):
        memory.treasure_day = day
    if data.get("ready") is True:
        memory.treasure_day = turn.day_index
    if data.get("taskAnswer"):
        memory.pending_answer = str(data["taskAnswer"])


def _heuristic_treasure(turn: World, memory: Memory) -> None:
    text = "\n".join(memory.folk)
    if memory.treasure_pos is None:
        match = re.search(r"\((\d{1,2})\s*[,，]\s*(\d{1,2})\)", text)
        if match:
            memory.treasure_pos = Pos(int(match.group(1)), int(match.group(2)))
    found: list[str] = []
    for alias, name in ITEM_ALIASES.items():
        if alias in text or name.lower() in text.lower():
            if name not in found:
                found.append(name)
    if found and not memory.treasure_items:
        memory.treasure_items = tuple(found)
    match = re.search(r"第\s*(\d{1,2})\s*天", text)
    if match and memory.treasure_day is None:
        memory.treasure_day = int(match.group(1))


def _canonical_item(name: str, turn: World) -> str:
    mapped = ITEM_ALIASES.get(name) or ITEM_ALIASES.get(name.lower())
    if mapped:
        return mapped
    item = turn.shop_item(name)
    return item.name if item else name


def treasure_ready(turn: World, memory: Memory) -> bool:
    if memory.treasure_done or memory.treasure_pos is None or not memory.treasure_items:
        return False
    if memory.treasure_day is not None and turn.day_index < memory.treasure_day:
        return False
    return True
