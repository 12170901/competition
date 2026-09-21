"""第一夜单回合:15 只小兵刷在基地角落,贴塔英雄必须开火。"""

from agent.brain import decide
from agent.protocol import Pos, distance

from tests.sandbox.world import (
    GATLING,
    PIONEER,
    RAILGUN,
    ROCKET,
    SandboxTurn,
    WORKER_1,
    WORKER_2,
    new_game,
    night1,
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
        if command["action"] == "attack":
            assert isinstance(command.get("controllerId"), str)


def test_night1_decide_two_towers_fire_miner_collects():
    """两人贴塔开火,矿工在边缘铜矿 collect。"""
    turn = SandboxTurn(night1())
    response = turn.decide()
    _validate(response, turn.payload)
    attacks = {
        int(key): cmd for key, cmd in response.items() if cmd["action"] == "attack"
    }
    assert len(attacks) == 2
    assert set(attacks) <= {GATLING, RAILGUN, ROCKET}
    controllers = {cmd["controllerId"] for cmd in attacks.values()}
    assert controllers == {str(WORKER_1), str(PIONEER)}
    miner = response.get(str(WORKER_2))
    assert miner is not None
    assert miner["action"] in {"collect", "move"}


def test_night1_attack_hits_spawned_small_robots():
    """开火落点必须落在本回合刷出的小兵格子上(或同距可达)。"""
    payload = night1()
    robot_cells = {
        (r["pos"]["x"], r["pos"]["y"]) for r in payload["robot"]["roles"]
    }
    response = decide(payload)
    for command in response.values():
        if command["action"] != "attack":
            continue
        for raw in command["targetPos"]:
            target = (raw["x"], raw["y"])
            assert target in robot_cells or any(
                distance(Pos(*target), Pos(*cell)) <= 1 for cell in robot_cells
            )


def test_night1_no_enemy_heroes():
    payload = night1()
    assert payload["teamEnemy"]["roles"] == []


def test_day_one_opening_does_not_attack():
    """开局白天不得 attack,且能给出合法指令。"""
    payload = new_game()
    response = decide(payload)
    _validate(response, payload)
    assert all(cmd["action"] != "attack" for cmd in response.values())
    assert response
