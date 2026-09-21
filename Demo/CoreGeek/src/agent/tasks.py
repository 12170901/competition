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
TASK_ROOT = "/tmp/selfEvolutionTask"
_TASK_FILE_NAME = re.compile(r"([\w.-]+\.(?:md|txt|json|py|csv))", re.I)
_ABS_TASK_PATH = re.compile(r"(/tmp/selfEvolutionTask/[^\s|:]+)")


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
    task_file: str = ""
    task_dir: str = ""
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
        memory.task_file = ""
        memory.task_dir = ""
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
        memory.task_file = ""
        memory.task_dir = ""
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
    names = ", ".join(_extract_task_files(turn.phase_task)) or "任务原文中的文件名"
    return (
        "你在沙盒中做自进化任务。沙盒无外网，可执行 shell / python，时限15秒。"
        "任务附件在 /tmp/selfEvolutionTask 下，必须用绝对路径读取，禁止 cat 相对路径。"
        f"先 find /tmp/selfEvolutionTask -name '{names}' ，再 cat 找到的绝对路径。"
        "不要把目录列表、MISSING、文件路径本身当成 taskAnswer。"
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
    _remember_task_path(memory, turn.last_cmd_result)
    parsed = parse_llm_json(turn.llm_resp)
    execute = str(parsed.get("executeCmd") or "").strip()
    answer = str(parsed.get("taskAnswer") or "").strip()
    if answer and _looks_like_answer(answer):
        memory.pending_answer = answer
    elif answer:
        answer = ""
    if execute:
        execute = _rewrite_sandbox_cmd(execute, memory, turn)
    if execute or answer:
        memory.task_step += 1
        return execute, answer
    if memory.pending_answer and turn.last_cmd_result and _looks_like_answer(
        memory.pending_answer
    ):
        return "", memory.pending_answer
    command = _fallback_cmd(turn, memory)
    memory.task_step += 1
    return command, ""


def _fallback_cmd(turn: World, memory: Memory) -> str:
    _remember_task_path(memory, turn.last_cmd_result)
    names = _extract_task_files(turn.phase_task)
    name = names[0] if names else "task_*.md"
    body = _cmd_body(turn.last_cmd_result)
    if memory.task_file and _output_ok(turn.last_cmd_result) and not _looks_like_listing(body):
        if "spec.md" in body or "ws_" in body:
            return _explore_workspace_cmd(memory.task_dir)
        if memory.task_dir and memory.task_step >= 2:
            return _explore_workspace_cmd(memory.task_dir)
    if memory.task_file and (
        memory.task_step == 0 or _looks_like_listing(body) or "No such file" in body
        or "MISSING" in body
    ):
        return f"cat {memory.task_file}"
    if memory.task_file:
        return f"cat {memory.task_file}"
    if memory.task_step == 0:
        return _find_task_file_cmd(name)
    if names:
        return _find_task_file_cmd(names[0])
    return (
        "python3 -c "
        + json.dumps(
            "from pathlib import Path\n"
            "root=Path('/tmp/selfEvolutionTask')\n"
            "print('\\n'.join(str(p) for p in list(root.rglob('task_*'))[:40]) "
            "if root.exists() else 'MISSING')\n"
        )
    )


def _extract_task_files(text: str) -> list[str]:
    names: list[str] = []
    for match in _TASK_FILE_NAME.finditer(text or ""):
        base = match.group(1).split("/")[-1]
        if base.lower() in {"spec.md", "readme.md", "phase_task.txt"}:
            continue
        if base not in names:
            names.append(base)
    preferred = [name for name in names if name.lower().startswith("task_")]
    return preferred or names


def _remember_task_path(memory: Memory, raw: str | None) -> None:
    if not raw:
        return
    for match in _ABS_TASK_PATH.finditer(raw):
        path = match.group(1).rstrip("。,;|\"'")
        if "/tmp/selfEvolutionTask/" not in path:
            continue
        if path.endswith((".md", ".txt", ".json", ".py", ".csv")):
            memory.task_file = path
            slash = path.rfind("/")
            memory.task_dir = path[:slash] if slash > 0 else TASK_ROOT
            return


def _find_task_file_cmd(name: str) -> str:
    safe = name.replace("'", "").replace('"', "")
    script = (
        "from pathlib import Path\n"
        "root=Path('/tmp/selfEvolutionTask')\n"
        f"want={safe!r}\n"
        "hits=[]\n"
        "if root.exists():\n"
        "    if '*' in want:\n"
        "        hits=[str(p) for p in root.rglob('task_*')][:40]\n"
        "    else:\n"
        "        hits=[str(p) for p in root.rglob(want)][:20]\n"
        "print('\\n'.join(hits) if hits else 'MISSING')\n"
    )
    return "python3 -c " + json.dumps(script)


def _explore_workspace_cmd(task_dir: str) -> str:
    root = task_dir if task_dir.startswith(TASK_ROOT) else TASK_ROOT
    return (
        f"ls -la {root}; ls -la {root}/ws_* 2>/dev/null; "
        f"find {root} -name spec.md -o -name README.md 2>/dev/null | head -20"
    )


def _rewrite_sandbox_cmd(command: str, memory: Memory, turn: World) -> str:
    stripped = command.strip()
    match = re.match(
        r"cat\s+(['\"]?)([\w./-]+\.(?:md|txt|json|py|csv))\1\s*$",
        stripped,
        re.I,
    )
    if not match:
        return command
    target = match.group(2)
    if target.startswith(TASK_ROOT):
        return f"cat {target}"
    base = target.split("/")[-1]
    if memory.task_file and memory.task_file.endswith(base):
        return f"cat {memory.task_file}"
    return _find_task_file_cmd(base)


def _output_ok(raw: str) -> bool:
    if not raw:
        return False
    first = raw.splitlines()[0].strip()
    return first.startswith("[exitCode:0]") or (
        not first.startswith("[exitCode:") and "No such file" not in raw
    )


def _looks_like_listing(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return True
    if "FILE " in body or "No such file" in body or body.startswith("MISSING"):
        return True
    if body.startswith("saved "):
        return True
    if body.startswith(TASK_ROOT) and len(body.splitlines()) <= 8:
        return True
    return False


def _looks_like_answer(text: str) -> bool:
    body = _cmd_body(text).strip() if "\n" in (text or "") else (text or "").strip()
    if not body or _looks_like_listing(body):
        return False
    if body.startswith("#") or "自进化任务" in body or "请阅读" in body:
        return False
    if body.startswith(TASK_ROOT) or body.startswith("/tmp/"):
        return False
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return False
    last = lines[-1]
    if len(last) > 400:
        return False
    return True


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
