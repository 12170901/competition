"""P1 入夜编制:白天最后 5 回合两人回塔,矿工去地图边缘;夜里继续边缘采矿。"""

from agent.brain import decide
from agent.protocol import Pos, distance

from tests.helpers import (
    GATLING,
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

EDGE_COPPER = Pos(7, 2)
VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _validate(response, payload):
    unique = {str(role["id"]) for role in payload["teamOur"]["roles"]}
    assert set(response.keys()) <= unique
    for command in response.values():
        assert command["action"] in VALID_ACTIONS


def test_round_60_still_mines_not_recall(make_payload):
    """回合 60 距入夜还有 10 回合:贴铜矿的建造工仍应 collect,不得提前回塔。"""
    payload = fresh(make_payload(roundNo=60))
    fill_walls(payload)
    place(payload, WORKER_1, 8, 2, backpack=[])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 18, 18, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) == "collect"
    target = response[str(WORKER_1)]["targetPos"][0]
    assert (target["x"], target["y"]) == (EDGE_COPPER.x, EDGE_COPPER.y)


def test_late_day_builder_does_not_collect(make_payload):
    """回合 66:建造工贴着铜矿也不得再 collect,应回防。"""
    payload = fresh(make_payload(roundNo=66))
    drop_walls(payload)
    park_other_worker_building(payload)
    place(payload, WORKER_1, 8, 2, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    action = action_of(response, WORKER_1)
    assert action not in {"collect", "sell", "buy"}, action


def test_late_day_builder_steps_closer_to_tower(make_payload):
    """回合 66:远离基地的建造工必须往最近塔走。"""
    payload = fresh(make_payload(roundNo=66))
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


def test_late_day_miner_also_recalls_to_tower(make_payload):
    """回合 66:矿工也回塔,不再去地图边缘采矿。"""
    payload = fresh(make_payload(roundNo=66))
    fill_walls(payload)
    start = Pos(20, 10)
    place(payload, WORKER_2, start.x, start.y, backpack=[])
    place(payload, WORKER_1, 8, 24, backpack=[])
    place(payload, PIONEER, 8, 25, backpack=["Medicine"])
    tower = nearest_tower(start, payload)
    before = distance(start, tower)
    response = decide(payload)
    _validate(response, payload)
    action = action_of(response, WORKER_2)
    assert action not in {"collect", "sell", "buy"}, action
    assert action == "move"
    step = move_pos(response, WORKER_2)
    assert step is not None
    assert distance(step, tower) < before


def test_late_day_pioneer_without_task_does_not_accept(make_payload):
    """无 phaseTask 时,回防窗口即使贴着任务点也不得 acceptTask,应往塔走。"""
    payload = fresh(make_payload(roundNo=66, phaseTask=""))
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
    payload = fresh(make_payload(roundNo=66, phaseTask="请阅读task_1_alpha.md"))
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
    payload = fresh(make_payload(roundNo=66))
    drop_walls(payload)
    place(payload, WORKER_1, 10, 10, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    assert all(cmd["action"] != "attack" for cmd in response.values())


def test_night_miner_mans_tower_not_edge(make_payload):
    """黑夜矿工即使贴着边缘铜矿也要去操塔,不得 collect。"""
    payload = fresh(make_payload(roundNo=85, phaseTask=""))
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 8, 2, backpack=[], health=220)
    place(payload, PIONEER, 8, 25, backpack=["Medicine"], health=200)
    payload["robot"] = {
        "roles": [
            {
                "id": 30001,
                "pos": {"x": 7, "y": 24},
                "roleType": "smallRobot",
                "health": 40,
                "abnormalState": "",
                "targetTeam": "challenger",
            }
        ]
    }
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_2) != "collect"
    gatling = response.get(str(GATLING))
    assert gatling is not None
    assert gatling["action"] == "attack"
    assert gatling["controllerId"] == str(WORKER_1)
    miner = response.get(str(WORKER_2))
    if miner is not None:
        assert miner["action"] == "move"
