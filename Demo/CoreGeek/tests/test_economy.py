"""开局经济:先建塔,再采矿升塔,第 30 回合起才砌墙。"""

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
    park_other_worker_building,
    place,
    set_tower_levels,
)

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}

SHOP = Pos(25, 20)
VENDOR = Pos(20, 16)
COPPER_NEAR = Pos(7, 2)
STONE_NEAR = Pos(14, 3)


def _validate(response, payload):
    unique = {str(role["id"]) for role in payload["teamOur"]["roles"]}
    assert set(response.keys()) <= unique
    for command in response.values():
        assert command["action"] in VALID_ACTIONS


def _opening_towers_no_walls(payload, gold: int) -> None:
    drop_walls(payload)
    payload["teamOur"]["goldNum"] = gold
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    place(payload, WORKER_2, 16, 18, backpack=[])


def test_early_day_mines_copper_while_walls_missing(make_payload):
    """回合 20、三塔已齐、墙未建、金币不够升塔:贴铜矿应 collect 铜,不去采石砌墙。"""
    payload = fresh(make_payload(roundNo=20))
    _opening_towers_no_walls(payload, gold=0)
    start = Pos(8, 2)
    place(payload, WORKER_1, start.x, start.y, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    command = response.get(str(WORKER_1))
    assert command is not None
    assert command["action"] == "collect"
    target = command["targetPos"][0]
    assert (target["x"], target["y"]) == (COPPER_NEAR.x, COPPER_NEAR.y)


def test_early_day_does_not_build_wall(make_payload):
    """回合 20、工人紧邻墙位且包里有石头:仍不得建墙,先去经营。"""
    payload = fresh(make_payload(roundNo=20))
    _opening_towers_no_walls(payload, gold=0)
    place(payload, WORKER_1, 12, 21, backpack=["stone", "stone", "stone", "stone"])
    response = decide(payload)
    _validate(response, payload)
    command = response.get(str(WORKER_1))
    assert command is not None
    assert not (
        command["action"] == "build" and command.get("name") == "wall"
    ), command


def test_early_day_buys_weapon_voucher_when_gold_enough(make_payload):
    """回合 20、墙未齐但金币够:已在武器商店旁应买 WeaponUpgradeVoucher1。"""
    payload = fresh(make_payload(roundNo=20))
    _opening_towers_no_walls(payload, gold=120)
    place(payload, WORKER_1, 24, 20, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "buy"
    assert command.get("name") == "WeaponUpgradeVoucher1"


def test_uses_weapon_voucher_on_tower_before_walls(make_payload):
    """背包已有武器升级券且贴着 1 级塔:先 use 升塔,不建墙。"""
    payload = fresh(make_payload(roundNo=20))
    _opening_towers_no_walls(payload, gold=0)
    place(payload, WORKER_1, 8, 24, backpack=["WeaponUpgradeVoucher1"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "use"
    assert command.get("name") == "WeaponUpgradeVoucher1"


def test_after_round_30_level1_towers_still_build_wall(make_payload):
    """第 35 回合塔仍是 1 级、金币不够升塔、工人墙边有石头:必须建墙,否则前两夜守不住。"""
    payload = fresh(make_payload(roundNo=35))
    drop_walls(payload)
    payload["teamOur"]["goldNum"] = 0
    place(payload, WORKER_1, 12, 21, backpack=["stone", "stone", "stone", "stone"])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "build"
    assert command.get("name") == "wall"


def test_after_round_30_upgrade_still_beats_wall(make_payload):
    """第 35 回合即使该砌墙,金币够升塔时仍先买武器升级券。"""
    payload = fresh(make_payload(roundNo=35))
    _opening_towers_no_walls(payload, gold=120)
    place(payload, WORKER_1, 24, 20, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "buy"
    assert command.get("name") == "WeaponUpgradeVoucher1"


def test_after_round_30_missing_walls_walk_to_stone(make_payload):
    """砌墙阶段墙未齐、金币不够升塔:不贴矿的工人应走向石矿。"""
    payload = fresh(make_payload(roundNo=35))
    drop_walls(payload)
    set_tower_levels(payload, 2)
    park_other_worker_building(payload)
    payload["teamOur"]["goldNum"] = 0
    start = Pos(20, 15)
    place(payload, WORKER_1, start.x, start.y, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) == "move"
    step = move_pos(response, WORKER_1)
    assert step is not None
    assert distance(step, STONE_NEAR) < distance(start, STONE_NEAR)


def test_walls_complete_still_buys_upgrade(make_payload):
    """墙已齐、金币够:商店旁仍买武器升级券。"""
    payload = fresh(make_payload(roundNo=20))
    fill_walls(payload)
    payload["teamOur"]["goldNum"] = 120
    place(payload, WORKER_1, 24, 20, backpack=[])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "buy"
    assert command.get("name") == "WeaponUpgradeVoucher1"


def test_day1_copper_in_backpack_goes_to_vendor(make_payload):
    """第一天砌墙阶段:包里有铜、金币不够、人不在墙边时,应去小贩卖掉换升塔金,不能把铜留在包里。"""
    payload = fresh(make_payload(roundNo=35))
    _opening_towers_no_walls(payload, gold=0)
    start = Pos(16, 12)
    place(payload, WORKER_1, start.x, start.y, backpack=["copper", "copper", "copper"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert not (
        command["action"] == "build" and command.get("name") == "wall"
    ), command
    if command["action"] == "sell":
        assert str(command.get("name", "")).lower() == "copper"
        return
    assert command["action"] == "move", command
    step = move_pos(response, WORKER_1)
    assert step is not None
    assert distance(step, VENDOR) < distance(start, VENDOR)


def test_day1_vendor_side_sells_copper(make_payload):
    """第一天金币不够升塔、工人已在小贩旁且包里有铜:直接 sell 铜。"""
    payload = fresh(make_payload(roundNo=35))
    _opening_towers_no_walls(payload, gold=0)
    place(payload, WORKER_1, 20, 15, backpack=["copper", "copper", "copper"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "sell"
    assert str(command.get("name", "")).lower() == "copper"


def test_day2_incomplete_walls_sells_copper_not_more_walls(make_payload):
    """第二天墙只建了一半、塔未满级、包里有铜:先卖铜升塔,不再继续扩墙。"""
    payload = fresh(make_payload(roundNo=135))
    fill_walls(payload, count=3)
    payload["teamOur"]["goldNum"] = 0
    start = Pos(16, 12)
    place(payload, WORKER_1, start.x, start.y, backpack=["copper", "copper", "copper"])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert not (
        command["action"] == "build" and command.get("name") == "wall"
    ), command
    if command["action"] == "sell":
        assert str(command.get("name", "")).lower() == "copper"
        return
    assert command["action"] == "move", command
    step = move_pos(response, WORKER_1)
    assert step is not None
    assert distance(step, VENDOR) < distance(start, VENDOR)


def test_day2_incomplete_walls_gold_enough_buys_upgrade(make_payload):
    """第二天墙未齐但塔未满级、金币够:商店旁买武器升级券,不建墙。"""
    payload = fresh(make_payload(roundNo=135))
    fill_walls(payload, count=3)
    payload["teamOur"]["goldNum"] = 120
    place(payload, WORKER_1, 24, 20, backpack=[])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "buy"
    assert command.get("name") == "WeaponUpgradeVoucher1"


def test_day2_incomplete_walls_empty_pack_mines_copper(make_payload):
    """第二天已有部分墙、塔未满级、空背包贴着铜矿:采铜攒升塔金,不改去采石砌墙。"""
    payload = fresh(make_payload(roundNo=135))
    fill_walls(payload, count=3)
    payload["teamOur"]["goldNum"] = 0
    place(payload, WORKER_1, 8, 2, backpack=[])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "collect"
    target = command["targetPos"][0]
    assert (target["x"], target["y"]) == (COPPER_NEAR.x, COPPER_NEAR.y)


def test_day2_no_walls_still_rebuilds(make_payload):
    """第二天墙被拆光、工人墙边有石头:即使塔未满级也要补墙,否则夜里守不住。"""
    payload = fresh(make_payload(roundNo=135))
    drop_walls(payload)
    payload["teamOur"]["goldNum"] = 0
    place(payload, WORKER_1, 12, 21, backpack=["stone", "stone", "stone", "stone"])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] == "build"
    assert command.get("name") == "wall"


def test_day2_maxed_towers_continue_walls(make_payload):
    """第二天塔已满级 3、墙未齐、工人墙边有石头:继续把墙补齐。"""
    payload = fresh(make_payload(roundNo=135))
    fill_walls(payload, count=3)
    set_tower_levels(payload, 3)
    payload["teamOur"]["goldNum"] = 0
    place(payload, WORKER_1, 12, 21, backpack=["stone", "stone", "stone", "stone"])
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 8, 24, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    command = response[str(WORKER_1)]
    assert command["action"] != "collect", command
    if command["action"] == "build":
        assert command.get("name") == "wall"
    else:
        assert command["action"] == "move", command
