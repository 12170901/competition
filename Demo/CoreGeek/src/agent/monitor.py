"""每回合空闲监视器。

职责:在 decide 生成本回合全部指令后,检测"可控但未获得指令"的角色(空闲),
并为每个空闲角色推断成因,供观测与后续补派优化使用。

当前阶段:仅检测 + 上报,不自动补派(优化留待后续迭代)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocol import distance
from .world import World

_IDLE_REASON_FALLBACK = "决策分支未匹配到可执行目标"


@dataclass(frozen=True, slots=True)
class IdleEntry:
    """一个空闲(本回合未获指令)的可控角色。"""

    unit_id: int
    kind: str
    pos: tuple[int, int]
    reason: str


_LAST_IDLE: tuple[IdleEntry, ...] = ()


def scan_idle(
    turn: World,
    commands: dict[int, dict[str, Any]],
) -> tuple[IdleEntry, ...]:
    """检测当前回合可控但未获指令的角色,并为每个推断成因。

    修正全局 _LAST_IDLE,供 server 响应与日志上报读取。
    操控武器开火时指令挂在武器 ID 上,该英雄不算空闲。
    """
    global _LAST_IDLE
    controllers: set[int] = set()
    for command in commands.values():
        if command.get("action") != "attack":
            continue
        raw = command.get("controllerId")
        if raw is None:
            continue
        try:
            controllers.add(int(raw))
        except (TypeError, ValueError):
            continue
    entries = []
    for unit in turn.controllable():
        if unit.unit_id in commands or unit.unit_id in controllers:
            continue
        if any(distance(unit.pos, tower.pos) <= 1 for tower in turn.weapons()):
            continue
        entries.append(
            IdleEntry(
                unit.unit_id,
                unit.kind,
                (unit.pos.x, unit.pos.y),
                _reason(turn, unit),
            )
        )
    _LAST_IDLE = tuple(entries)
    return _LAST_IDLE


def last_idle() -> tuple[IdleEntry, ...]:
    """返回最近一次 scan_idle 的结果(供 server 响应携带)。"""
    return _LAST_IDLE


def _reason(turn: World, unit) -> str:
    """从本回合决策备注里找一个与空闲角色相关的成因。"""
    unit_notes = [note for note in turn.notes if str(unit.unit_id) in note]
    if unit_notes:
        return unit_notes[-1]
    for tower in turn.weapons():
        if distance(unit.pos, tower.pos) <= 1:
            if tower.cooldown > 0:
                return f"已贴塔 {tower.unit_id}，武器冷却中"
            return f"已贴塔 {tower.unit_id} 待命"
    if turn.phase_task and unit.kind == "pioneer":
        return "沙盒任务执行中，留在任务点"
    return _IDLE_REASON_FALLBACK
