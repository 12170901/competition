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
# 只用 ASCII。\w 会把「请阅读task_1_alpha.md」整句当成文件名。
_TASK_FILE_NAME = re.compile(r"([A-Za-z0-9_./-]+\.(?:md|txt|json|py|csv))", re.I)
_ABS_TASK_PATH = re.compile(r"(/tmp/selfEvolutionTask/[^\s|:]+)")
_LOCAL_URL = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?(?:/[^\s'\"<>，。]*)?"
)
_BRACE_KEYS = re.compile(r"\{([^{}]{1,200})\}")


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
    task_body: str = ""
    api_fetched: bool = False
    api_blob: str = ""
    bundle_kind: str = ""
    model_wait: int = 0
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
        _clear_task_detail(memory)
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
        _clear_task_detail(memory)
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


def _clear_task_detail(memory: Memory) -> None:
    memory.task_body = ""
    memory.api_fetched = False
    memory.api_blob = ""
    memory.bundle_kind = ""
    memory.model_wait = 0


def task_prompt(turn: World) -> str:
    names = _extract_task_files(turn.phase_task)
    hint = names[0] if names else "task_*.md"
    body = (MEMORY.task_body or "").strip()
    shown = body[:2500] if body else "（尚未读到题面。按 ASCII 文件名读取，不要用中文做 -name。）"
    raw = turn.last_cmd_result or ""
    if len(raw) > 7000:
        raw = raw[:800] + "\n...\n" + raw[-6200:]
    return (
        "你是比赛内嵌的自进化求解模型。沙盒无外网，时限15秒，只能访问 "
        "/tmp/selfEvolutionTask 和 localhost。"
        f"禁止 find -name 使用中文或「请阅读」整句。列文件用 find /tmp/selfEvolutionTask -name '*.md'，"
        f"再读取 {hint}。"
        "若输出里已有符合题面字段的 JSON，把该 JSON 原样写入 taskAnswer，executeCmd 留空。"
        "文化遗产题按城市筛选后统计 total_count、world_heritage_count、types、oldest_era，"
        "不要提交原始记录列表。"
        "工程修复题（spec.md、./check、ws_）：executeCmd 写一段 python，按 spec 修改文件并再跑 ./check。"
        "检查已通过时，按题面给出 taskAnswer，executeCmd 留空。"
        "不要把目录列表、MISSING、文件路径或题面原文当成 taskAnswer。"
        "只输出一行 JSON："
        '{"executeCmd":"","taskAnswer":""}。'
        f"\n【任务】\n{turn.phase_task}\n【题面】\n{shown}\n【上次命令输出】\n{raw}"
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
    raw = turn.last_cmd_result or ""
    _remember_task_path(memory, raw)
    body = _cmd_body(raw)
    failed = _cmd_failed(raw)
    bundle_answer = ""
    if body and (not failed or "TASK_TEXT" in body or "CHECK_PASS" in body):
        bundle_answer, _kind = _absorb_bundle(body, memory)
    if bundle_answer:
        memory.pending_answer = bundle_answer
        memory.task_step += 1
        memory.model_wait = 0
        return "", bundle_answer
    parsed = parse_llm_json(turn.llm_resp)
    execute = str(parsed.get("executeCmd") or "").strip()
    answer = _accept_model_answer(str(parsed.get("taskAnswer") or "").strip(), memory)
    if answer:
        memory.pending_answer = answer
    if execute:
        execute = _rewrite_sandbox_cmd(execute, memory, turn)
        if not _llm_cmd_useful(execute, memory):
            execute = ""
    ready = "" if failed else _ready_answer(body, memory)
    if not ready and memory.api_blob and memory.task_body:
        ready = _ready_answer(memory.api_blob, memory)
    if answer:
        memory.task_step += 1
        memory.model_wait = 0
        return execute, answer
    if ready:
        memory.pending_answer = ready
        memory.task_step += 1
        memory.model_wait = 0
        return "", ready
    if execute:
        memory.task_step += 1
        memory.model_wait = 0
        return execute, ""
    if (
        memory.pending_answer
        and raw
        and not failed
        and _accept_model_answer(memory.pending_answer, memory)
    ):
        return "", memory.pending_answer
    if memory.bundle_kind == "fix":
        return _wait_for_fix(memory)
    if memory.bundle_kind == "pass" and memory.model_wait < 3:
        memory.model_wait += 1
        memory.task_step += 1
        return "", ""
    if (
        memory.bundle_kind == "api"
        and memory.api_blob
        and not memory.api_blob.startswith("API_FAIL")
        and memory.model_wait < 2
    ):
        memory.model_wait += 1
        memory.task_step += 1
        return "", ""
    command = _fallback_cmd(turn, memory)
    memory.task_step += 1
    return command, ""


def _wait_for_fix(memory: Memory) -> tuple[str, str]:
    """检查失败的材料已经交给内嵌模型。模型没给补丁时，按 spec 做一次替换。"""
    if memory.model_wait >= 1:
        command = _spec_patch_cmd(memory)
        memory.model_wait += 1
        memory.bundle_kind = "patched"
        memory.task_step += 1
        return command, ""
    memory.model_wait += 1
    memory.task_step += 1
    return "", ""


def _fallback_cmd(turn: World, memory: Memory) -> str:
    _remember_task_path(memory, turn.last_cmd_result)
    names = _extract_task_files(turn.phase_task)
    name = names[0] if names else "task_*.md"
    body = _cmd_body(turn.last_cmd_result)
    if _output_ok(turn.last_cmd_result) and body.strip() and _is_task_text(body):
        memory.task_body = body
        follow = _follow_task_text(body, memory)
        if follow:
            return follow
    if memory.task_file and _output_ok(turn.last_cmd_result) and not _looks_like_listing(body):
        if "spec.md" in body or "ws_" in body or "./check" in body:
            return _oneshot_cmd(name if _ascii_task_name(name) else "")
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
        return _oneshot_cmd(_ascii_task_name(name))
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


def _ascii_task_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:md|txt|json|py|csv)", name or "", re.I):
        return name
    return ""


def _find_task_file_cmd(name: str) -> str:
    safe = _ascii_task_name(name) or "*.md"
    if re.search(r"[^\x00-\x7f]", safe):
        safe = "*.md"
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
    if _bad_find(command):
        if memory.task_file:
            return f"cat {memory.task_file}"
        names = _extract_task_files(turn.phase_task)
        return _oneshot_cmd(names[0] if names else "")
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


def _oneshot_cmd(name: str) -> str:
    """一次读题：文化遗产接口直接拉数据，工程题带上 spec 和 ./check。"""
    safe = _ascii_task_name(name)
    script = r'''
import re, subprocess
from pathlib import Path
root = Path("/tmp/selfEvolutionTask")
name = __NAME__
hits = list(root.rglob("*.md")) if root.exists() else []
named = [p for p in hits if name and p.name == name]
tasks = named or [p for p in hits if p.name.startswith("task_")]
if not tasks:
    print("MISSING")
    raise SystemExit(0)
path = tasks[0]
text = path.read_text(encoding="utf-8", errors="replace")
print("TASK_FILE")
print(path)
print("TASK_TEXT")
print(text[:8000])
engineering = any(tok in text for tok in ("./check", "spec.md", "ws_1", "ws_2"))

def fetch(url):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            return resp.read().decode("utf-8", "replace")[:8000]
    except Exception as exc:
        return "FETCH_ERROR %s %s" % (url, type(exc).__name__)

if not engineering:
    urls = []
    for found in re.findall(r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?(?:/[^\s'\"<>，。）)]*)?", text):
        urls.append(found.rstrip(").,;，。"))
    bases = []
    for item in urls:
        matched = re.match(r"(https?://[^/]+)", item)
        if matched and matched.group(1) not in bases:
            bases.append(matched.group(1))
    for rel in re.findall(r"(?:GET|POST|PUT|DELETE)\s+(/[A-Za-z0-9_./?=&%-]+)", text):
        for base in bases:
            urls.append(base + rel)
    seen = []
    for item in urls:
        if item not in seen:
            seen.append(item)
    print("API_JSON")
    if not seen:
        print("API_FAIL no_url")
    else:
        chunks = [fetch(item) for item in seen[:6]]
        if all(chunk.startswith("FETCH_ERROR") or chunk.startswith("API_FAIL") for chunk in chunks):
            print("API_FAIL")
            print("\n".join(chunks)[:4000])
        else:
            print("\n---\n".join(chunks)[:12000])
    raise SystemExit(0)

checks = list(path.parent.rglob("check"))
specs = list(path.parent.rglob("spec.md"))
ws = checks[0].parent if checks else path.parent
print("FILES")
for item in [p for p in ws.rglob("*") if p.is_file()][:40]:
    print(item)
print("SPEC")
if specs:
    print(specs[0].read_text(encoding="utf-8", errors="replace")[:2500])
print("SOURCE")
budget = 3500
for item in [p for p in ws.rglob("*") if p.is_file()]:
    if item.name in {"spec.md", path.name} or item.suffix.lower() not in {".py", ".yml", ".yaml", ".json", ".toml", ".ini", ".txt", ".sh", ".env", ".conf", ".cfg"}:
        continue
    chunk = item.read_text(encoding="utf-8", errors="replace")[:1500]
    if budget <= 0:
        break
    print("--- %s" % item)
    print(chunk)
    budget -= len(chunk)
print("CHECK_OUT")
code = 1
if checks:
    try:
        proc = subprocess.run(["./check"], cwd=str(ws), capture_output=True, text=True, timeout=8)
        print((proc.stdout or "")[-2500:])
        print((proc.stderr or "")[-800:])
        code = proc.returncode
        print("exit", code)
    except Exception as exc:
        print("CHECK_FAIL", type(exc).__name__)
else:
    print("NO_CHECK")
print("CHECK_PASS" if code == 0 else "NEED_FIX")
'''
    script = script.replace("__NAME__", repr(safe))
    return "python3 -c " + json.dumps(script)


def _spec_patch_cmd(memory: Memory) -> str:
    root = memory.task_dir if str(memory.task_dir).startswith(TASK_ROOT) else TASK_ROOT
    script = r'''
import re, subprocess
from pathlib import Path
root = Path(__ROOT__)
specs = list(root.rglob("spec.md")) if root.exists() else []
checks = list(root.rglob("check")) if root.exists() else []
spec = specs[0].read_text(encoding="utf-8", errors="replace") if specs else ""
ws = checks[0].parent if checks else (specs[0].parent if specs else root)
patterns = [
    r"把\s*[`「\"'](.+?)[`」\"']\s*改(?:为|成)\s*[`「\"'](.+?)[`」\"']",
    r"将\s*[`「\"'](.+?)[`」\"']\s*(?:改为|修改为|替换为)\s*[`「\"'](.+?)[`」\"']",
    r"将\s+(\S+)\s+(?:改为|修改为|替换为)\s+(\S+)",
]
pairs = []
for pattern in patterns:
    pairs.extend(re.findall(pattern, spec))
suffixes = {".py", ".yml", ".yaml", ".json", ".toml", ".ini", ".txt", ".sh", ".env", ".conf", ".cfg"}
files = [p for p in ws.rglob("*") if p.is_file() and p.suffix.lower() in suffixes and p.name != "spec.md"]
changed = 0
for src, dst in pairs:
    src, dst = src.strip(), dst.strip().rstrip("。.")
    if not src or src == dst:
        continue
    for item in files:
        try:
            file_text = item.read_text(encoding="utf-8")
        except OSError:
            continue
        if src not in file_text:
            continue
        item.write_text(file_text.replace(src, dst), encoding="utf-8")
        changed += 1
        break
print("PATCHED", changed)
if checks:
    try:
        proc = subprocess.run(["./check"], cwd=str(ws), capture_output=True, text=True, timeout=8)
        print((proc.stdout or "")[-2000:])
        print((proc.stderr or "")[-500:])
        print("exit", proc.returncode)
        print("CHECK_PASS" if proc.returncode == 0 else "NEED_FIX")
    except Exception as exc:
        print("CHECK_FAIL", type(exc).__name__)
        print("NEED_FIX")
else:
    print("NEED_FIX")
'''
    script = script.replace("__ROOT__", repr(root))
    return "python3 -c " + json.dumps(script)


_BUNDLE_MARKERS = (
    "TASK_FILE", "TASK_TEXT", "API_JSON", "SPEC", "SOURCE", "FILES",
    "CHECK_OUT", "NEED_FIX", "CHECK_PASS",
)


def _section(body: str, name: str) -> str:
    collecting = False
    chunk: list[str] = []
    for line in (body or "").splitlines():
        if line.strip() in _BUNDLE_MARKERS:
            if collecting:
                break
            collecting = line.strip() == name
            continue
        if collecting:
            chunk.append(line)
    return "\n".join(chunk).strip()


def _absorb_bundle(body: str, memory: Memory) -> tuple[str, str]:
    text = body or ""
    if not any(marker in text for marker in ("TASK_TEXT", "CHECK_PASS", "NEED_FIX", "API_JSON")):
        return "", ""
    task = _section(text, "TASK_TEXT")
    if task:
        memory.task_body = task
    if "API_JSON" in text:
        memory.api_fetched = True
        memory.bundle_kind = "api"
        api = _section(text, "API_JSON")
        memory.api_blob = api
        answer = ""
        parts = re.split(r"\n---\n", api) if api else []
        for part in parts:
            if part.startswith(("API_FAIL", "FETCH_ERROR")):
                continue
            answer = _ready_answer(part, memory)
            if answer:
                break
        if not answer and api:
            answer = _ready_answer(api, memory)
        return answer, "api"
    if "CHECK_PASS" in text and "NEED_FIX" not in text:
        memory.bundle_kind = "pass"
        explicit = _explicit_answer(memory.task_body) or _explicit_answer(text)
        return explicit, "pass"
    if "NEED_FIX" in text or "SPEC" in text or "CHECK_OUT" in text:
        memory.bundle_kind = "fix"
        return "", "fix"
    return "", "read"


def _explicit_answer(text: str) -> str:
    match = re.search(
        r"(?:答案|提交内容|taskAnswer)\s*[:：为是]\s*[`\"']?([^\n`\"']{1,200})",
        text or "",
    )
    if not match:
        return ""
    token = match.group(1).strip().rstrip("。")
    if token.startswith("{") or _looks_like_answer(token):
        return token
    return ""


def _bad_find(command: str) -> bool:
    if re.search(r"-name\s+(['\"]).*请阅读", command or ""):
        return True
    if re.search(r"want\s*=\s*(['\"]).*请阅读", command or ""):
        return True
    match = re.search(r"-name\s+(['\"])(.+?)\1", command or "")
    return bool(match and re.search(r"[^\x00-\x7f]", match.group(2)))


def _is_search_cmd(command: str) -> bool:
    text = command or ""
    if _bad_find(text):
        return True
    if "urlopen" in text or "write_text" in text:
        return False
    if "rglob" in text and "read_text" not in text:
        return True
    if re.search(r"\bfind\b", text) and "read_text" not in text and "urlopen" not in text:
        return True
    stripped = text.strip()
    return stripped == "ls" or stripped.startswith("ls ")


def _llm_cmd_useful(command: str, memory: Memory) -> bool:
    if not command:
        return False
    if memory.task_body and (
        _is_search_cmd(command) or command.strip().startswith("cat ")
    ):
        return False
    if _is_search_cmd(command) and (memory.task_file or memory.api_blob):
        return False
    return True


def _cmd_failed(raw: str) -> bool:
    if not raw:
        return False
    if "API_FAIL" in raw and "API_JSON" not in raw:
        return True
    lines = raw.splitlines()
    first = lines[0].strip() if lines else ""
    if first.startswith("[TIMEOUT]") or first.startswith("[JUDGER_ERROR]"):
        return True
    body = _cmd_body(raw).strip()
    if body == "MISSING" or body.startswith("MISSING"):
        return True
    if "No such file" in raw:
        return True
    if first.startswith("[exitCode:") and not first.startswith("[exitCode:0]"):
        return True
    return False


def _is_task_text(body: str) -> bool:
    text = (body or "").strip()
    if not text or "TASK_TEXT" in text or "API_JSON" in text:
        return False
    if text.startswith("#") or "请阅读" in text or "自进化任务" in text:
        return True
    return "localhost" in text or "127.0.0.1" in text


def _follow_task_text(body: str, memory: Memory) -> str:
    match = _LOCAL_URL.search(body or "")
    if match and not memory.api_fetched:
        memory.api_fetched = True
        return _api_cmd(match.group(0).rstrip(").,;，。"))
    if any(token in (body or "") for token in ("./check", "spec.md", "ws_")):
        name = memory.task_file.rsplit("/", 1)[-1] if memory.task_file else ""
        return _oneshot_cmd(name)
    return ""


def _api_cmd(url: str) -> str:
    script = (
        "import urllib.request\n"
        f"url={url!r}\n"
        "try:\n"
        "    with urllib.request.urlopen(url, timeout=8) as resp:\n"
        "        print(resp.read().decode('utf-8','replace'))\n"
        "except Exception as exc:\n"
        "    print('API_FAIL', type(exc).__name__)\n"
    )
    return "python3 -c " + json.dumps(script)


def _ready_answer(body: str, memory: Memory) -> str:
    text = (body or "").strip()
    if not text or _looks_like_listing(text) or _is_task_text(text):
        return ""
    if text.startswith(("API_FAIL", "MISSING", "FETCH_ERROR")):
        return ""
    parsed, candidate = _parse_json_answer(text)
    if parsed is None:
        return ""
    keys = _schema_keys(memory.task_body)
    shaped = _shape_answer(memory.task_body, parsed, candidate)
    if keys and _json_has_keys(shaped, keys):
        return shaped
    if keys:
        return _synthesize_heritage(memory.task_body, parsed)
    return ""


def _parse_json_answer(text: str) -> tuple[object | None, str]:
    for candidate in (text, *[line.strip() for line in text.splitlines() if line.strip()][-1:]):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed, candidate
    return None, ""


def _schema_keys(task_body: str) -> list[str]:
    for match in _BRACE_KEYS.finditer(task_body or ""):
        parts = [part.strip() for part in match.group(1).split(",")]
        if parts and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
            return parts
    return []


def _shape_answer(task_body: str, parsed: object, raw: str) -> str:
    if isinstance(parsed, dict):
        keys = _schema_keys(task_body)
        if keys and all(key in parsed for key in keys):
            return json.dumps({key: parsed[key] for key in keys}, ensure_ascii=False)
    if not str(raw).strip().startswith("{"):
        return json.dumps(parsed, ensure_ascii=False)
    return str(raw).strip()


def _json_has_keys(text: str, keys: list[str]) -> bool:
    parsed, _candidate = _parse_json_answer(text)
    return isinstance(parsed, dict) and all(key in parsed for key in keys)


def _accept_model_answer(answer: str, memory: Memory) -> str:
    if not answer or not _looks_like_answer(answer):
        return ""
    keys = _schema_keys(memory.task_body)
    if not keys:
        return answer
    parsed, _candidate = _parse_json_answer(answer)
    if isinstance(parsed, dict) and all(key in parsed for key in keys):
        return json.dumps({key: parsed[key] for key in keys}, ensure_ascii=False)
    return ""


_ERA_ORDER = (
    "史前", "旧石器", "新石器", "夏", "商", "西周", "东周", "春秋", "战国",
    "秦", "西汉", "东汉", "汉", "三国", "西晋", "东晋", "晋", "南北朝",
    "隋", "唐", "五代十国", "五代", "北宋", "南宋", "宋", "辽", "金", "元",
    "明", "清", "明清", "近代", "现代", "当代",
)
_ERA_RANK = {name: index for index, name in enumerate(_ERA_ORDER)}
_CITY_KEYS = ("city", "city_name", "cityName", "城市")
_TYPE_KEYS = ("type", "types", "category", "kind", "heritage_type", "heritageType", "类型")
_ERA_KEYS = ("era", "dynasty", "period", "age", "时代", "年代")
_WORLD_KEYS = (
    "world_heritage", "worldHeritage", "is_world_heritage", "isWorldHeritage",
    "is_world", "unesco",
)
_LIST_KEYS = (
    "data", "records", "items", "result", "results", "list", "rows",
    "heritages", "heritage", "content",
)


def _field(row: dict, names: tuple[str, ...]):
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return None


def _record_rows(parsed: object) -> list[dict]:
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if not isinstance(parsed, dict):
        return []
    for key in _LIST_KEYS:
        value = parsed.get(key)
        if isinstance(value, list) and any(isinstance(row, dict) for row in value):
            return [row for row in value if isinstance(row, dict)]
    for value in parsed.values():
        if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            return list(value)
        if isinstance(value, dict):
            nested = _record_rows(value)
            if nested:
                return nested
    return []


def _city_wanted(task_body: str) -> str:
    text = task_body or ""
    skipped = {"全部", "所有", "本市", "全市"}
    match = re.search(r"查询([\u4e00-\u9fff]{2,8})市", text)
    if match and match.group(1) not in skipped:
        return match.group(1)
    for item in re.findall(r"([\u4e00-\u9fff]{2,3})市", text):
        if item not in skipped:
            return item
    match = re.search(r"(北京|南京|上海|西安|洛阳|杭州|苏州|成都|广州|重庆|开封)", text)
    return match.group(1) if match else ""


def _era_rank(value: object) -> int:
    text = str(value or "").strip()
    if text in _ERA_RANK:
        return _ERA_RANK[text]
    for name, rank in _ERA_RANK.items():
        if name and name in text:
            return rank
    return 10_000


def _is_world(row: dict) -> bool:
    value = _field(row, _WORLD_KEYS)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip()
    if text.lower() in {"1", "true", "yes", "y", "是", "世界遗产", "世界文化遗产"}:
        return True
    if "世界" in text and "非" not in text:
        return True
    level = str(_field(row, ("level", "grade", "heritage_level", "级别")) or "")
    return "世界" in level


def _synthesize_heritage(task_body: str, parsed: object) -> str:
    keys = _schema_keys(task_body)
    if not keys:
        return ""
    rows = _record_rows(parsed)
    if not rows and isinstance(parsed, dict) and (
        _field(parsed, _TYPE_KEYS) or _field(parsed, _ERA_KEYS)
    ):
        rows = [parsed]
    if not rows:
        return ""
    wanted = _city_wanted(task_body)
    if wanted:
        picked = [row for row in rows if wanted in str(_field(row, _CITY_KEYS) or "")]
        if picked:
            rows = picked
    cities = [str(_field(row, _CITY_KEYS) or "") for row in rows]
    cities = [city for city in cities if city]
    if wanted:
        city = wanted
    elif cities:
        city = max(set(cities), key=cities.count)
    elif isinstance(parsed, dict):
        city = str(_field(parsed, _CITY_KEYS) or "")
    else:
        city = ""
    types: list[str] = []
    for row in rows:
        raw_type = _field(row, _TYPE_KEYS)
        values = raw_type if isinstance(raw_type, list) else [raw_type]
        for value in values:
            label = str(value or "").strip()
            if label and label not in types:
                types.append(label)
    ranked = [(_era_rank(_field(row, _ERA_KEYS)), str(_field(row, _ERA_KEYS) or "").strip()) for row in rows]
    known = [(rank, era) for rank, era in ranked if era and rank < 10_000]
    if known:
        oldest = min(known)[1]
    else:
        years = []
        for row in rows:
            year = _field(row, ("year", "build_year", "built_year", "date"))
            found = re.search(r"-?\d{3,4}", str(year or ""))
            if found:
                years.append(int(found.group(0)))
        oldest = str(min(years)) if years else ""
        if not oldest:
            named = [era for _rank, era in ranked if era]
            oldest = named[0] if named else ""
    payload = {
        "city": city,
        "total_count": len(rows),
        "world_heritage_count": sum(1 for row in rows if _is_world(row)),
        "types": types,
        "oldest_era": oldest,
    }
    if not all(key in payload for key in keys):
        return ""
    return json.dumps({key: payload[key] for key in keys}, ensure_ascii=False)


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
