"""跨回合任务连续:采矿不换目标、失败重试、工种锁矿、开拓者冷却等待、夜间人塔配对粘住。"""

import agent.tasks as tasks_mod
from agent.brain import _neighbours, _tower_sites, decide
from agent.jobs import KIND_ACCEPT, KIND_MINE, KIND_MAN_TOWER
from agent.protocol import Pos, distance, station_footprint
from agent.world import World

from tests.helpers import (
    GATLING,
    PIONEER,
    WORKER_1,
    WORKER_2,
    action_of,
    fill_walls,
    fresh,
    move_pos,
    place,
)

COPPER_NEAR = Pos(7, 2)
COPPER_FAR = Pos(22, 26)
SHOP = Pos(25, 20)
TASK_1 = Pos(14, 14)

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _validate(response, payload):
    unique = {str(role["id"]) for role in payload["teamOur"]["roles"]}
    assert set(response.keys()) <= unique
    for command in response.values():
        assert command["action"] in VALID_ACTIONS


def _park_economy(payload):
    fill_walls(payload)
    place(payload, WORKER_2, 16, 18, backpack=[])
    place(payload, PIONEER, 18, 18, backpack=["Medicine"])


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


def test_miner_keeps_copper_when_gold_unlocks_shop(make_payload):
    """先因金币不够开始采铜,下一回合金够买券也不得改去商店。"""
    payload = fresh(make_payload(roundNo=10))
    payload["teamOur"]["goldNum"] = 20
    _park_economy(payload)
    start = Pos(16, 8)
    place(payload, WORKER_1, start.x, start.y, backpack=[])
    first = decide(payload)
    _validate(first, payload)
    assert action_of(first, WORKER_1) == "move"
    step1 = move_pos(first, WORKER_1)
    assert step1 is not None
    assert distance(step1, COPPER_NEAR) < distance(start, COPPER_NEAR)
    job = tasks_mod.MEMORY.jobs.get(WORKER_1)
    assert job is not None
    assert job.kind == KIND_MINE
    assert job.target == COPPER_NEAR

    place(payload, WORKER_1, step1.x, step1.y, backpack=[])
    payload["roundNo"] = 11
    payload["teamOur"]["goldNum"] = 200
    second = decide(payload)
    _validate(second, payload)
    stuck = tasks_mod.MEMORY.jobs.get(WORKER_1)
    assert stuck is not None
    assert stuck.kind == KIND_MINE
    assert stuck.target == COPPER_NEAR
    assert action_of(second, WORKER_1) != "buy"
    step2 = move_pos(second, WORKER_1)
    if step2 is not None:
        assert distance(step2, COPPER_NEAR) < distance(step1, COPPER_NEAR)
        assert distance(step2, SHOP) >= distance(step1, SHOP)


def test_failed_collect_retries_same_adjacent_mine(make_payload):
    """贴着铜矿但上回合 collect 失败:重试这座矿,不得改走远处另一座。"""
    payload = fresh(make_payload(roundNo=10))
    _park_economy(payload)
    place(payload, WORKER_1, 8, 2, backpack=[])
    payload["lastRoundRoleActionResults"] = {str(WORKER_1): False}
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) == "collect"
    target = response[str(WORKER_1)]["targetPos"][0]
    assert (target["x"], target["y"]) == (COPPER_NEAR.x, COPPER_NEAR.y)


def test_workers_lock_distinct_mine_targets(make_payload):
    """墙已齐、两人同时采矿:Job 目标不得是同一座矿。"""
    payload = fresh(make_payload(roundNo=10))
    fill_walls(payload)
    place(payload, WORKER_1, 15, 12, backpack=[])
    place(payload, WORKER_2, 16, 12, backpack=[])
    place(payload, PIONEER, 18, 18, backpack=["Medicine"])
    response = decide(payload)
    _validate(response, payload)
    job1 = tasks_mod.MEMORY.jobs.get(WORKER_1)
    job2 = tasks_mod.MEMORY.jobs.get(WORKER_2)
    assert job1 is not None and job2 is not None
    assert job1.kind == KIND_MINE
    assert job2.kind == KIND_MINE
    assert job1.target != job2.target


def test_pioneer_waits_on_task_cooldown_not_shop(make_payload):
    """任务点冷却中即使金够买券,开拓者仍停在任务点旁,不得去商店。"""
    payload = fresh(make_payload(roundNo=10, phaseTask=""))
    payload["teamOur"]["goldNum"] = 200
    payload["teamOur"]["playerTasks"] = [
        {
            "taskType": "自进化类1",
            "taskPosition": {"x": 14, "y": 14},
            "coldDownRounds": 12,
            "scoreReward": 50,
            "goldReward": 30,
            "isValid": False,
        },
        {
            "taskType": "自进化类2",
            "taskPosition": {"x": 17, "y": 17},
            "coldDownRounds": 12,
            "scoreReward": 50,
            "goldReward": 30,
            "isValid": False,
        },
    ]
    fill_walls(payload)
    place(payload, PIONEER, 13, 14, backpack=["Medicine"])
    place(payload, WORKER_1, 8, 24, backpack=[])
    place(payload, WORKER_2, 11, 25, backpack=[])
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, PIONEER) not in {"buy", "sell", "acceptTask"}
    step = move_pos(response, PIONEER)
    if step is not None:
        assert distance(step, TASK_1) <= 1
        assert step != TASK_1
    job = tasks_mod.MEMORY.jobs.get(PIONEER)
    assert job is not None
    assert job.kind == KIND_ACCEPT


def test_night_weapon_assignment_stays_on_first_tower(make_payload):
    """黑夜先分到加特林后,即使另一人更近,下一回合仍由原操作者开火。"""
    payload = fresh(make_payload(roundNo=85, phaseTask=""))
    place(payload, WORKER_1, 8, 24, backpack=[], health=220)
    place(payload, WORKER_2, 20, 10, backpack=[], health=220)
    place(payload, PIONEER, 20, 12, backpack=["Medicine"], health=200)
    payload["robot"] = _robots((6, 24))
    first = decide(payload)
    _validate(first, payload)
    assert first[str(GATLING)]["action"] == "attack"
    assert first[str(GATLING)]["controllerId"] == str(WORKER_1)
    job = tasks_mod.MEMORY.jobs.get(WORKER_1)
    assert job is not None
    assert job.kind == KIND_MAN_TOWER
    assert job.tower_id == GATLING

    place(payload, WORKER_1, 7, 24, backpack=[], health=220)
    place(payload, WORKER_2, 8, 24, backpack=[], health=220)
    payload["roundNo"] = 86
    second = decide(payload)
    _validate(second, payload)
    stuck = tasks_mod.MEMORY.jobs.get(WORKER_1)
    assert stuck is not None
    assert stuck.kind == KIND_MAN_TOWER
    assert stuck.tower_id == GATLING
    gatling = second.get(str(GATLING))
    if gatling is not None and gatling.get("action") == "attack":
        assert gatling["controllerId"] == str(WORKER_1)
    else:
        assert action_of(second, WORKER_1) == "move"
        step = move_pos(second, WORKER_1)
        assert step is not None
        assert distance(step, Pos(9, 24)) < distance(Pos(7, 24), Pos(9, 24))


def _opening_no_buildings(payload):
    payload["teamOur"]["goldNum"] = 75
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role.get("roleType") in ("station", "worker", "pioneer")
    ]
    place(payload, WORKER_1, 5, 23, backpack=[])
    place(payload, WORKER_2, 10, 16, backpack=[])
    place(payload, PIONEER, 10, 12, backpack=["Medicine"])
    return payload


def _block_tower_footholds(payload):
    world = World.load(payload)
    sites = _tower_sites(world)
    blocked = set(station_footprint(world.station().pos))
    blocked.update(sites)
    blocked.update(unit.pos for unit in world.controllable())
    wall_id = 50000
    for site in sites:
        for cell in _neighbours(site):
            if cell in blocked or not world.land(cell):
                continue
            payload["teamOur"]["roles"].append(
                {
                    "id": wall_id,
                    "pos": {"x": cell.x, "y": cell.y},
                    "roleType": "wall",
                    "health": 1000,
                    "level": 1,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backpack": [],
                }
            )
            wall_id += 1
            blocked.add(cell)
    return payload


def test_opening_workers_all_get_commands(make_payload):
    """开局 75 金、无塔无墙:两名工人都必须有指令,不得空闲站岗。"""
    payload = _opening_no_buildings(fresh(make_payload(roundNo=1)))
    start = Pos(5, 23)
    response = decide(payload)
    _validate(response, payload)
    assert action_of(response, WORKER_1) in {"move", "build"}
    assert action_of(response, WORKER_2) in {"move", "build", "collect"}
    assert action_of(response, WORKER_1) != "collect", (
        "开局贴着石矿也不得原地 collect,应去建塔"
    )
    if action_of(response, WORKER_1) == "move":
        step = move_pos(response, WORKER_1)
        assert step is not None
        sites = _tower_sites(World.load(payload))
        assert min(distance(step, site) for site in sites) < min(
            distance(start, site) for site in sites
        )


def test_opening_builder_approaches_when_tower_has_no_foothold(make_payload):
    """首选塔位周围无落脚点时,不得原地采石站岗,应走近塔位。"""
    payload = _block_tower_footholds(
        _opening_no_buildings(fresh(make_payload(roundNo=1)))
    )
    start = Pos(5, 23)
    world = World.load(payload)
    sites = _tower_sites(world)
    response = decide(payload)
    _validate(response, payload)
    action = action_of(response, WORKER_1)
    assert action == "move", (
        f"塔位无落脚时建造工应走近塔,不得 {action} 原地站岗"
    )
    step = move_pos(response, WORKER_1)
    assert step is not None
    assert min(distance(step, site) for site in sites) < min(
        distance(start, site) for site in sites
    )
    job = tasks_mod.MEMORY.jobs.get(WORKER_1)
    assert job is not None
    assert job.kind == "tower"


def test_opening_uses_free_ring_when_preferred_sites_occupied(make_payload):
    """3 个首选塔位被英雄占住时,改去空的内圈格建塔,不得空闲或原地采矿。"""
    payload = _opening_no_buildings(fresh(make_payload(roundNo=1)))
    preferred = _tower_sites(World.load(payload))
    assert len(preferred) == 3
    place(payload, WORKER_1, preferred[0].x, preferred[0].y, backpack=[])
    place(payload, WORKER_2, preferred[1].x, preferred[1].y, backpack=[])
    place(payload, PIONEER, preferred[2].x, preferred[2].y, backpack=[])
    sites = _tower_sites(World.load(payload))
    assert sites
    assert set(sites).isdisjoint(preferred), (
        f"被占的首选塔位应让路给空格子: still={sites} preferred={preferred}"
    )
    response = decide(payload)
    _validate(response, payload)
    action = action_of(response, WORKER_1)
    assert action in {"build", "move"}, f"占住首选塔位时仍应建塔,得到 {action}"
    if action == "build":
        raw = response[str(WORKER_1)]["targetPos"][0]
        built = Pos(int(raw["x"]), int(raw["y"]))
        assert built not in preferred
        assert response[str(WORKER_1)]["name"] in {"gatling", "railgun", "rocket"}
