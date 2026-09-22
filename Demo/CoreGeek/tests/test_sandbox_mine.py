"""沙箱白天采矿单回合:墙未齐时不得去采基地旁的高价铜。"""

from agent.brain import decide
from agent.protocol import Pos, distance

from tests.helpers import set_tower_levels
from tests.sandbox.world import WORKER_1, day_mining

COPPER = Pos(34, 11)
STONE = Pos(32, 6)


def test_missing_walls_do_not_collect_nearby_copper():
    payload = day_mining(35)
    set_tower_levels(payload, 2)
    response = decide(payload)
    command = response.get(str(WORKER_1))
    assert command is not None
    if command["action"] == "collect":
        target = command["targetPos"][0]
        assert (target["x"], target["y"]) != (COPPER.x, COPPER.y)
    else:
        assert command["action"] in {"move", "build"}
        if command["action"] == "move":
            start = Pos(33, 11)
            step = Pos(command["targetPos"][0]["x"], command["targetPos"][0]["y"])
            assert distance(step, STONE) < distance(start, STONE)


def test_day_mining_payload_is_daytime():
    payload = day_mining(35)
    assert payload["roundNo"] == 35
    assert payload["robot"]["roles"] == []
    assert payload["teamOur"]["type"] == "defender"
