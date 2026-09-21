"""P1 入夜编制:白天最后 15 回合必须往塔走,不得再去采矿/领任务。"""

from agent.brain import decide
from agent.protocol import Pos, distance

from tests.helpers import (
    PIONEER,
    WORKER_1,
    WORKER_2,
    action_of,
    drop_walls,
    fill_walls,
    fresh,
    move_pos,
    nearest_tower,
    park_other_worker_building,
    place,
)

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _validate(response, payload):
    unique = {str(role["id"]) for role in payload["teamOur"]["roles"]}
    assert set(response.keys()) <= unique
    for command in response.values():
        assert command["action"] in VALID_ACTIONS


def test_late_day_worker_does_not_collect(make_payload):
    """回合 60:工人贴着铜矿且背包空,回防窗口不得 collect/sell/buy。"""
    payload = fresh(make_payload(roundNo=60))
    drop_walls(payload)
    park_other_worker_building(payload)
    place(payload, WORKER_1, 8, 2, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    action = action_of(response, WORKER_1)
    assert action not in {"collect", "sell", "buy"}, action


def test_late_day_worker_steps_closer_to_tower(make_payload):
    """回合 60:远离基地的工人必须 move,且相对最近塔变近。"""
    payload = fresh(make_payload(roundNo=60))
    drop_walls(payload)
    park_other_worker_building(payload)
    start = Pos(10, 10)
    place(payload, WORKER_1, start.x, start.y, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    tower = nearest_tower(start, payload)
    before = distance(start, tower)
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) == "move"
    step = move_pos(response, WORKER_1)
    assert step is not None
    assert distance(step, tower) < before, (step, tower, before)


def test_late_day_pioneer_without_task_does_not_accept(make_payload):
    """无 phaseTask 时,回防窗口即使贴着任务点也不得 acceptTask,应往塔走。"""
    payload = fresh(make_payload(roundNo=60, phaseTask=""))
    drop_walls(payload)
    start = Pos(13, 14)
    place(payload, PIONEER, start.x, start.y, backpack=["Medicine"])
    place(payload, WORKER_1, 8, 24, backpack=[])
    tower = nearest_tower(start, payload)
    before = distance(start, tower)
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, PIONEER) != "acceptTask"
    step = move_pos(response, PIONEER)
    assert step is not None
    assert distance(step, tower) < before


def test_late_day_pioneer_with_phase_task_stays(make_payload):
    """已有 phaseTask 时,回防也不得离开任务点周围一格。"""
    payload = fresh(make_payload(roundNo=60, phaseTask="请阅读task_1_alpha.md"))
    task = Pos(14, 14)
    place(payload, PIONEER, 13, 14, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, PIONEER) != "acceptTask"
    step = move_pos(response, PIONEER)
    if step is not None:
        assert distance(step, task) <= 1
        assert step != task


def test_early_day_worker_still_mines_or_builds(make_payload):
    """回合 10 非回防:墙已齐且贴铜矿时允许 collect,禁止全天回塔。"""
    payload = fresh(make_payload(roundNo=10))
    fill_walls(payload)
    place(payload, WORKER_1, 8, 2, backpack=[])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 18, 18, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) == "collect"
    target = response[str(WORKER_1)]["targetPos"][0]
    assert (target["x"], target["y"]) == (7, 2)


def test_recall_does_not_emit_attack_in_day(make_payload):
    """回防仍是白天,整表不得出现 attack。"""
    payload = fresh(make_payload(roundNo=60))
    drop_walls(payload)
    place(payload, WORKER_1, 10, 10, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    assert all(cmd["action"] != "attack" for cmd in response.values())
