"""粘性 Job / 工种绑定的纯记忆层测试,不走 decide。"""

import agent.tasks as tasks_mod
from agent.jobs import (
    FAIL_LIMIT,
    KIND_MINE,
    ROLE_BUILDER,
    ROLE_MINER,
    ROLE_PIONEER,
    Job,
    assign_roles,
    claimed_targets,
    is_edge_miner,
    update_fail_streaks,
)
from agent.protocol import Pos
from agent.tasks import Memory
from agent.world import World

from tests.helpers import PIONEER, WORKER_1, WORKER_2, fresh


def test_assign_roles_splits_builder_and_miner(make_payload):
    payload = fresh(make_payload(roundNo=10))
    world = World.load(payload)
    memory = Memory()
    assign_roles(world, memory)
    assert memory.roles[WORKER_1] == ROLE_BUILDER
    assert memory.roles[WORKER_2] == ROLE_MINER
    assert memory.roles[PIONEER] == ROLE_PIONEER


def test_assign_roles_lone_worker_is_builder(make_payload):
    payload = fresh(make_payload(roundNo=10))
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role["id"] != WORKER_2
    ]
    world = World.load(payload)
    memory = Memory()
    assign_roles(world, memory)
    assert memory.roles[WORKER_1] == ROLE_BUILDER
    assert WORKER_2 not in memory.roles


def test_edge_miner_only_when_three_heroes(make_payload):
    payload = fresh(make_payload(roundNo=10))
    world = World.load(payload)
    memory = Memory()
    assign_roles(world, memory)
    assert is_edge_miner(world, memory, WORKER_2)
    assert not is_edge_miner(world, memory, WORKER_1)
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role["id"] != PIONEER
    ]
    world = World.load(payload)
    memory = Memory()
    assign_roles(world, memory)
    assert not is_edge_miner(world, memory, WORKER_2)


def test_fail_streak_clears_job_after_limit():
    memory = Memory()
    memory.jobs[WORKER_1] = Job(kind=KIND_MINE, target=Pos(7, 2), fail_streak=FAIL_LIMIT - 1)
    world = World.load({
        "roundNo": 10,
        "mapInfo": {"width": 10, "height": 10, "zones": []},
        "teamOur": {
            "type": "challenger",
            "goldNum": 0,
            "roles": [{"id": WORKER_1, "pos": {"x": 1, "y": 1}, "roleType": "worker", "health": 220}],
        },
        "lastRoundRoleActionResults": {str(WORKER_1): False},
    })
    update_fail_streaks(world, memory)
    assert WORKER_1 not in memory.jobs


def test_claimed_targets_skips_self():
    memory = Memory()
    memory.jobs[WORKER_1] = Job(kind=KIND_MINE, target=Pos(7, 2))
    memory.jobs[WORKER_2] = Job(kind=KIND_MINE, target=Pos(22, 26))
    assert claimed_targets(memory, WORKER_1) == {Pos(22, 26)}


def test_observe_round_going_backwards_clears_jobs():
    memory = Memory()
    memory.jobs[WORKER_1] = Job(kind=KIND_MINE, target=Pos(7, 2), started=10)
    tasks_mod.MEMORY = memory
    payload = {
        "roundNo": 5,
        "mapInfo": {"width": 10, "height": 10, "zones": []},
        "teamOur": {
            "type": "challenger",
            "goldNum": 10,
            "roles": [
                {"id": 10013, "pos": {"x": 10, "y": 20}, "roleType": "station", "health": 1500, "level": 1},
            ],
        },
    }
    tasks_mod.observe(World.load(payload))
    assert WORKER_1 in tasks_mod.MEMORY.jobs
    payload["roundNo"] = 3
    tasks_mod.observe(World.load(payload))
    assert tasks_mod.MEMORY.jobs == {}
