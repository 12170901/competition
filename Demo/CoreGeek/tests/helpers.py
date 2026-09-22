"""P1–P3 场景构造帮手。不改生产代码。"""

from __future__ import annotations

from typing import Any

from agent.brain import _wall_order
from agent.protocol import Pos
from agent.world import World

TOWER_KINDS = ("gatling", "railgun", "rocket")
WORKER_1 = 10010
WORKER_2 = 10012
PIONEER = 10011
GATLING = 10020
RAILGUN = 10030
ROCKET = 10040


def role_by_id(payload: dict[str, Any], unit_id: int) -> dict[str, Any]:
    for role in payload["teamOur"]["roles"]:
        if role["id"] == unit_id:
            return role
    raise KeyError(unit_id)


def fresh(payload: dict[str, Any]) -> dict[str, Any]:
    """清掉样例里的上回合失败标记,避免 collect 被 last_ok=false 跳过。"""
    payload["lastRoundRoleActionResults"] = {}
    payload["errors"] = []
    return payload


def place(
    payload: dict[str, Any],
    unit_id: int,
    x: int,
    y: int,
    backpack: list[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    role = role_by_id(payload, unit_id)
    role["pos"] = {"x": x, "y": y}
    if backpack is not None:
        role["backpack"] = list(backpack)
    for key, value in fields.items():
        role[key] = value
    return role


def set_tower_levels(payload: dict[str, Any], level: int) -> None:
    for role in payload["teamOur"]["roles"]:
        if role.get("roleType") in TOWER_KINDS:
            role["level"] = int(level)


def drop_walls(payload: dict[str, Any]) -> None:
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"] if role.get("roleType") != "wall"
    ]


def fill_walls(payload: dict[str, Any]) -> None:
    drop_walls(payload)
    order = _wall_order(World.load(payload))
    for index, cell in enumerate(order):
        payload["teamOur"]["roles"].append(
            {
                "id": 40000 + index,
                "pos": {"x": cell.x, "y": cell.y},
                "roleType": "wall",
                "health": 1000,
                "level": 1,
                "attackPower": 0,
                "attackRange": 0,
                "backpack": [],
            }
        )


def tower_cells(payload: dict[str, Any]) -> list[Pos]:
    return [
        Pos(role["pos"]["x"], role["pos"]["y"])
        for role in payload["teamOur"]["roles"]
        if role.get("roleType") in TOWER_KINDS
    ]


def nearest_tower(pos: Pos, payload: dict[str, Any]) -> Pos:
    cells = tower_cells(payload)
    return min(
        cells,
        key=lambda cell: (max(abs(pos.x - cell.x), abs(pos.y - cell.y)), cell.x, cell.y),
    )


def action_of(response: dict[str, Any], unit_id: int) -> str | None:
    command = response.get(str(unit_id))
    if not command:
        return None
    return command.get("action")


def move_pos(response: dict[str, Any], unit_id: int) -> Pos | None:
    command = response.get(str(unit_id))
    if not command or command.get("action") != "move":
        return None
    raw = command["targetPos"][0]
    return Pos(int(raw["x"]), int(raw["y"]))


def park_other_worker_building(payload: dict[str, Any]) -> None:
    """让 10012 带着石头站在墙位旁,避免和第二名工人抢路。"""
    place(payload, WORKER_2, 12, 21, backpack=["stone", "stone", "stone", "stone"])
