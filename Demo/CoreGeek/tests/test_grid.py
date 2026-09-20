"""agent.grid 单元测试:A* 单步寻路。"""

from agent.grid import next_step
from agent.protocol import Pos, Turn, Unit


def _world_payload(**overrides):
    payload = {
        "roundNo": 1,
        "mapInfo": {
            "width": 12,
            "height": 12,
            "zones": [
                # 中间一列石头墙,测试绕行
                {"neutralType": "stone", "pos": {"x": 6, "y": 2}},
                {"neutralType": "stone", "pos": {"x": 6, "y": 3}},
                {"neutralType": "stone", "pos": {"x": 6, "y": 4}},
                {"neutralType": "stone", "pos": {"x": 6, "y": 5}},
                {"neutralType": "stone", "pos": {"x": 6, "y": 6}},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "goldNum": 0,
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 2, "y": 10},
                    "roleType": "worker",
                    "health": 220,
                    "backPackCapability": 100,
                    "backpack": [],
                }
            ],
        },
        "robot": {"roles": []},
    }
    payload.update(overrides)
    return payload


def _turn(payload=None):
    return Turn.load(payload if payload is not None else _world_payload())


def _worker(turn):
    return next(unit for unit in turn.ours if unit.kind == "worker")


def test_next_step_returns_adjacent_cell_on_straight_line():
    """场景:无阻挡时沿直线向目标前进一步,返回与 start 相邻的格。"""
    turn = _turn()
    worker = _worker(turn)  # (2,10)
    step = next_step(turn, worker, Pos(2, 4))
    assert step is not None
    assert step != worker.pos
    assert abs(step.x - worker.pos.x) <= 1 and abs(step.y - worker.pos.y) <= 1


def test_next_step_approaches_goal_each_step():
    """场景:连续单步寻路逐步逼近目标且最终可达。"""
    turn, worker = _turn(), _worker(_turn())
    goal = Pos(10, 1)
    for _ in range(50):
        step = next_step(turn, worker, goal)
        assert step is not None
        worker = Unit(
            unit_id=worker.unit_id, pos=step, kind=worker.kind,
            health=worker.health, level=worker.level,
            cooldown=worker.cooldown, attack_range=worker.attack_range,
            capacity=worker.capacity, backpack=worker.backpack,
        )
        if step == goal:
            break
    assert worker.pos == goal


def test_next_step_blocks_through_stone_wall_and_detours():
    """场景:石头墙为不可通行,寻路绕行而非穿墙。"""
    turn, worker = _turn(), _worker(_turn())
    goal = Pos(8, 4)
    for _ in range(200):
        step = next_step(turn, worker, goal)
        if step is None:
            break
        worker = Unit(
            unit_id=worker.unit_id, pos=step, kind=worker.kind,
            health=worker.health, level=worker.level,
            cooldown=worker.cooldown, attack_range=worker.attack_range,
            capacity=worker.capacity, backpack=worker.backpack,
        )
        if step == goal:
            break
    assert worker.pos == goal
    # 路径上不应踩到石头墙
    assert worker.pos != Pos(6, 4)


def test_next_step_avoids_bot_and_own_footprint():
    """场景:机器人坐标与基地占地视为障碍。"""
    payload = _world_payload()
    payload["robot"] = {"roles": [
        {"id": 30001, "pos": {"x": 3, "y": 10}, "roleType": "smallRobot",
         "health": 40, "abnormalState": ""},
    ]}
    payload["teamOur"]["roles"].append(
        {"id": 10013, "pos": {"x": 4, "y": 10}, "roleType": "station",
         "health": 1500, "level": 1}
    )
    turn = _turn(payload)
    worker = _worker(turn)  # (2,10)
    step = next_step(turn, worker, Pos(6, 10))
    assert step is not None
    assert step not in (Pos(3, 10),)  # 不走向机器人
    footprint = set(turn.footprint(turn.station()))
    assert step not in footprint  # 不踏入基地占地


def test_next_step_out_of_bounds_goal_still_navigates():
    """场景:目标在开阔地图边界 1 格内,仍可返回步进。"""
    turn, worker = _turn(), _worker(_turn())
    step = next_step(turn, worker, Pos(11, 11))
    assert step is not None
    assert not turn.land(worker.pos) is False  # 起点合法
    assert max(abs(step.x - worker.pos.x), abs(step.y - worker.pos.y)) == 1
