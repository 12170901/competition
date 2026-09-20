from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .world import ERROR_TEXT, SUMMON_TEXT, World

LOGGER = logging.getLogger("agent.round")
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LAST_EXTRA: dict[str, str] = {"prompt": "", "executeCmd": ""}


def set_extra(prompt: str, execute_cmd: str) -> None:
    _LAST_EXTRA["prompt"] = prompt or ""
    _LAST_EXTRA["executeCmd"] = execute_cmd or ""


def last_extra() -> dict[str, str]:
    return dict(_LAST_EXTRA)


def write_round_log(
    world: World,
    commands: dict[int, dict[str, Any]],
    prompt: str,
    execute_cmd: str,
) -> None:
    lines = _build_lines(world, commands, prompt, execute_cmd)
    text = "\n".join(lines)
    for line in lines:
        LOGGER.info("%s", line)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / "rounds.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
        snap = LOG_DIR / f"round_{world.round_no:04d}.log"
        snap.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        LOGGER.warning("write log file failed: %s", exc)


def _build_lines(
    world: World,
    commands: dict[int, dict[str, Any]],
    prompt: str,
    execute_cmd: str,
) -> list[str]:
    phase = "白天" if world.is_day else "黑夜"
    station = world.station()
    lines = [
        "=" * 72,
        (
            f"回合 {world.round_no} | 第{world.day_index}天 "
            f"日内第{world.round_in_day}回合 | {phase} | 阵营={world.team_type or '?'}"
        ),
        (
            f"金币={world.gold} 积分={world.score} 基地HP="
            f"{station.health if station else 0} 存活英雄="
            f"{len(world.controllable())} 武器="
            f"{len(world.weapons())} 机器人={len(world.robots)}"
        ),
        "-" * 72,
        "【上回合失败诊断】",
    ]
    failures = [item for item in _last_failures(world)]
    if failures:
        lines.extend(failures)
    else:
        lines.append("  无：上回合角色动作结果均为合法，或尚无上回合数据")
    lines.append("-" * 72)
    lines.append("【本回合决策】")
    if commands:
        for unit_id, command in sorted(commands.items()):
            lines.append(f"  单位 {unit_id}: {json.dumps(command, ensure_ascii=False)}")
    else:
        lines.append("  无角色指令（可能全部阵亡、冷却中、或没有合法目标）")
    idle = [
        unit.unit_id for unit in world.controllable() if unit.unit_id not in commands
    ]
    if idle:
        lines.append(f"  未下达指令的英雄: {idle}（可能已就位操控武器、等待任务、或寻路失败）")
    if prompt:
        lines.append(f"  prompt: {prompt[:300]}")
    else:
        lines.append("  prompt: （空，本回合未调用 LLM）")
    if execute_cmd:
        lines.append(f"  executeCmd: {execute_cmd[:300]}")
    else:
        lines.append("  executeCmd: （空，本回合未向沙盒发命令）")
    if world.notes:
        lines.append("-" * 72)
        lines.append("【决策备注 / 未执行原因】")
        for note in world.notes:
            lines.append(f"  - {note}")
    lines.append("=" * 72)
    return lines


def _last_failures(world: World) -> list[str]:
    lines: list[str] = []
    for unit_id, ok in sorted(world.last_results.items()):
        if ok:
            continue
        role = _role_name(world, unit_id)
        lines.append(
            f"  角色 {unit_id} ({role}) 上回合动作执行失败。"
            " 判题器判定该指令字段完整但未生效：常见原因包括移动碰撞、"
            "攻击越距/锥角非法/冷却中、白天使用 attack、采集/建造/买卖不在周围一格、"
            "金币或背包不足、升级券目标等级不匹配、离开任务点导致任务结束。"
        )
    for error in world.errors:
        lines.append(f"  errors[]: code={error.code} {error.reason()}")
    if world.last_summon:
        lines.append(
            f"  lastSummonTreasureResult={world.last_summon}: "
            f"{SUMMON_TEXT.get(world.last_summon, '未知结果码')}"
        )
    if world.last_cmd_result:
        preview = world.last_cmd_result.replace("\n", " | ")[:400]
        reason = "沙盒命令已返回"
        raw = world.last_cmd_result
        if raw.startswith("[TIMEOUT]"):
            reason = "沙盒命令超时（>15秒），不计入队伍异常次数"
        elif raw.startswith("[JUDGER_ERROR]"):
            reason = "判题器侧异常，不计入队伍异常次数"
        elif "[TRUNCATED]" in raw:
            reason = "沙盒输出超过 64KB 被截断"
        elif raw.startswith("[exitCode:") and not raw.startswith("[exitCode:0]"):
            reason = "沙盒命令退出码非 0，命令本身执行失败"
        lines.append(f"  lastCmdResult: {reason} | {preview}")
    if world.llm_limited():
        lines.append(
            f"  LLM 限制: {ERROR_TEXT[5]}。非任务期间每个游戏日最多 3 次，"
            "任务执行期间不受此限制。"
        )
    return lines


def _role_name(world: World, unit_id: int) -> str:
    for unit in world.ours:
        if unit.unit_id == unit_id:
            return f"{unit.kind} hp={unit.health} pos=({unit.pos.x},{unit.pos.y})"
    return "未知单位"
