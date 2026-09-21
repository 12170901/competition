"""跨回合粘性任务(Job)。

HTTP 每回合无状态重入,进程级 MEMORY 记住每个角色正在做的事,
避免 if 链每回合重选目标导致中途改去商店/另一座矿。
"""

from __future__ import annotations

from dataclasses import dataclass
from .protocol import Pos

KIND_MINE = "mine"
KIND_WALL = "wall"
KIND_TOWER = "tower"
KIND_SHOP = "shop"
KIND_SELL = "sell"
KIND_RECALL = "recall"
KIND_ACCEPT = "accept_task"
KIND_PHASE = "phase_task"
KIND_TREASURE = "treasure"
KIND_MAN_TOWER = "man_tower"

ROLE_BUILDER = "builder"
ROLE_MINER = "miner"
ROLE_PIONEER = "pioneer"

FAIL_LIMIT = 3
SELL_THRESHOLD = 8


@dataclass
class Job:
    kind: str
    target: Pos | None = None
    name: str = ""
    started: int = 0
    fail_streak: int = 0
    tower_id: int = 0


def assign_roles(turn, memory) -> None:
    """工号较小的工人砌墙建塔,其余专职采矿;孤身工人两头都扛。"""
    alive = {unit.unit_id for unit in turn.controllable()}
    for unit_id in list(memory.roles):
        if unit_id not in alive:
            memory.roles.pop(unit_id, None)
            memory.jobs.pop(unit_id, None)
    workers = list(turn.workers())
    if len(workers) == 1:
        memory.roles[workers[0].unit_id] = ROLE_BUILDER
    elif len(workers) >= 2:
        memory.roles[workers[0].unit_id] = ROLE_BUILDER
        for worker in workers[1:]:
            memory.roles[worker.unit_id] = ROLE_MINER
    pioneer = turn.pioneer()
    if pioneer is not None:
        memory.roles[pioneer.unit_id] = ROLE_PIONEER


def is_builder(memory, unit_id: int) -> bool:
    return memory.roles.get(unit_id) != ROLE_MINER


def update_fail_streaks(turn, memory) -> None:
    """上回合失败累加;连续失败则丢掉 Job,允许重选。"""
    for unit_id, job in list(memory.jobs.items()):
        ok = turn.last_ok(unit_id)
        if ok is False:
            job.fail_streak += 1
        elif ok is True:
            job.fail_streak = 0
        if job.fail_streak >= FAIL_LIMIT:
            memory.jobs.pop(unit_id, None)


def claimed_targets(memory, except_id: int) -> set[Pos]:
    taken: set[Pos] = set()
    for unit_id, job in memory.jobs.items():
        if unit_id == except_id or job.target is None:
            continue
        taken.add(job.target)
    return taken


def set_job(memory, unit_id: int, job: Job) -> Job:
    memory.jobs[unit_id] = job
    return job


def clear_job(memory, unit_id: int) -> None:
    memory.jobs.pop(unit_id, None)


def get_job(memory, unit_id: int) -> Job | None:
    return memory.jobs.get(unit_id)
