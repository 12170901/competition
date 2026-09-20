"""P2 贴塔开火:黑夜人已在塔旁且射程内有怪,必须 attack。"""

from agent.brain import decide

from tests.helpers import (
    GATLING,
    PIONEER,
    RAILGUN,
    ROCKET,
    WORKER_1,
    WORKER_2,
    action_of,
    place,
)

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _robots(*cells):
    roles = []
    for index, (x, y) in enumerate(cells, start=1):
        roles.append(
            {
                "id": 30000 + index,
                "pos": {"x": x, "y": y},
                "roleType": "smallRobot",
                "health": 40,
                "abnormalState": "",
                "targetTeam": "challenger",
            }
        )
    return {"roles": roles}


def _validate(response, payload):
    unique = {str(role["id"]) for role in payload["teamOur"]["roles"]}
    assert set(response.keys()) <= unique
    for command in response.values():
        assert command["action"] in VALID_ACTIONS
        if command["action"] == "attack":
            assert isinstance(command.get("controllerId"), str)


def test_adjacent_hero_fires_gatling(make_payload):
    """工人贴着加特林、射程内有机器人 → attack 挂在塔 ID 上。"""
    payload = make_payload(roundNo=85, phaseTask="")
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 20, 10, backpack=[], health=220)
    place(payload, PIONEER, 20, 12, backpack=["Medicine"], health=200)
    payload["robot"] = _robots((7, 24))
    response = decide(payload)
    _validate(response, payload)
    command = response[str(GATLING)]
    assert command["action"] == "attack"
    assert command["controllerId"] == str(WORKER_1)


def test_attack_key_is_weapon_not_hero(make_payload):
    """开火指令的 key 是武器 ID,英雄自己不再挂 attack。"""
    payload = make_payload(roundNo=85, phaseTask="")
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 20, 10, backpack=[], health=220)
    place(payload, PIONEER, 20, 12, backpack=["Medicine"], health=200)
    payload["robot"] = _robots((7, 24))
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, GATLING) == "attack"
    hero_cmd = response.get(str(WORKER_1))
    if hero_cmd is not None:
        assert hero_cmd["action"] != "attack"


def test_rocket_cooldown_skips_attack(make_payload):
    """火箭冷却中不得 attack。"""
    payload = make_payload(roundNo=85, phaseTask="")
    place(payload, WORKER_1, 8, 26, backpack=[], health=220)
    place(payload, WORKER_2, 20, 10, backpack=[], health=220)
    place(payload, PIONEER, 20, 12, backpack=["Medicine"], health=200)
    place(payload, ROCKET, 9, 25, cooldown=2)
    payload["robot"] = _robots((8, 27))
    response = decide(payload)
    _validate(response, payload)
    rocket_cmd = response.get(str(ROCKET))
    if rocket_cmd is not None:
        assert rocket_cmd["action"] != "attack"


def test_no_robot_no_attack(make_payload):
    """黑夜贴塔但场上无机器人,不得空放 attack。"""
    payload = make_payload(roundNo=85, phaseTask="")
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 11, 25, backpack=[], health=220)
    place(payload, PIONEER, 8, 25, backpack=["Medicine"], health=200)
    payload["robot"] = {"roles": []}
    response = decide(payload)
    _validate(response, payload)
    assert all(cmd["action"] != "attack" for cmd in response.values())


def test_three_heroes_three_towers_all_fire(make_payload):
    """三名英雄分别贴三座塔,射程内有怪 → 三条 attack。"""
    payload = make_payload(roundNo=85, phaseTask="")
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 11, 25, backpack=[], health=220)
    place(payload, PIONEER, 8, 25, backpack=["Medicine"], health=200)
    payload["robot"] = _robots((7, 23))
    response = decide(payload)
    _validate(response, payload)
    attacks = [
        key for key, cmd in response.items() if cmd["action"] == "attack"
    ]
    assert set(attacks) == {str(GATLING), str(RAILGUN), str(ROCKET)}
    controllers = {cmd["controllerId"] for cmd in response.values() if cmd["action"] == "attack"}
    assert controllers == {str(WORKER_1), str(WORKER_2), str(PIONEER)}
