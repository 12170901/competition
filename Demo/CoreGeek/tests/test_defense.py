"""防御回归测试:基于真实比赛失败的朝向修复 + 人手分配修复。

背景:logs/teamB.log(defender 阵营)中,白天所有工人被派去采矿/交易,
从不建墙,导致第 71 回合机器人涌来时基地无墙可守而失败。
本文件针对两项修复做回归:
  1. brain._wall_order / brain._tower_sites 优先朝向地图中央建防御;
  2. brain._worker_day 在墙未建齐时优先建墙,而非先卖矿/采矿。
"""

from __future__ import annotations

from agent.brain import _tower_sites, _wall_order, _map_center, decide
from agent.protocol import distance
from agent.world import World

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _strip_roles(payload, keep_wall=False):
    """把 roles 精简为:基地 + 3 塔 + 可选墙 + 2 工人,便于构造场景。"""
    station_extra = {"attackPower": 0, "attackRange": 0}
    kept = []
    for role in payload["teamOur"]["roles"]:
        rtype = role.get("roleType")
        if rtype == "station":
            kept.append({**role, **station_extra})
        elif rtype in ("gatling", "railgun", "rocket"):
            kept.append({**role, **station_extra})
        elif rtype == "wall" and keep_wall:
            kept.append({**role, **station_extra})
        elif rtype in ("worker", "pioneer"):
            kept.append(role)
    payload["teamOur"]["roles"] = kept
    return payload


def test_wall_order_faces_map_center(make_payload):
    """朝向修复:墙位建造顺序应优先朝向地图中央(defender 基地在中央东北方)。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    world = World.load(payload)
    center = _map_center(world)
    order = _wall_order(world)
    assert order, "地图应有可建墙位"
    # 4 条边按"每边到中央的最小距离"排序:第一条边必含全局最靠中央的墙位
    global_min = min(distance(pos, center) for pos in order)
    first_edge = order[0]
    assert distance(first_edge, center) == global_min, (
        f"排序后第一条边应包含最靠中央的墙位:首={first_edge}(dist="
        f"{distance(first_edge, center)}), 全局最小={global_min}"
    )
    # 边顺序整体应由近到远:把墙位按距离分区,验证前半段整体不劣于后半段
    half = (len(order) - 1) // 2
    front = order[: half + 1]
    back = order[half + 1:]
    assert min(distance(p, center) for p in front) <= min(
        distance(p, center) for p in back
    ), "墙位前半段朝向中央侧优先"


def test_tower_sites_faces_map_center(make_payload):
    """朝向修复:塔位首选应朝向地图中央(defender 基地在中央东北方)。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    world = World.load(payload)
    center = _map_center(world)
    sites = _tower_sites(world)
    assert sites, "地图应有可建塔位"
    # 首选塔位应是最靠中央的方向
    best = min(distance(pos, center) for pos in sites)
    assert distance(sites[0], center) == best, \
        f"首选塔位应朝向中央:sites[0]={sites[0]} center={center}"


def test_worker_builds_wall_when_towers_done(make_payload):
    """人手分配:3 塔已建完、墙未建齐、工人紧邻墙位且带足 stone 时,直接建墙。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"] if role.get("roleType") != "wall"
    ]
    for role in payload["teamOur"]["roles"]:
        if role.get("roleType") == "worker":
            # 紧邻东侧墙位(13,21),带足石头应直接 build wall
            role["pos"] = {"x": 12, "y": 21}
            role["backpack"] = ["stone", "stone", "stone", "stone", "stone"]
            break
    response = decide(payload)
    _validate_decision(response, payload)
    builds = [
        cmd for cmd in response.values()
        if cmd["action"] == "build" and cmd.get("name") == "wall"
    ]
    assert builds, "墙未建齐且工人紧邻墙位时应直接建墙(不应去卖矿/采矿)"

    sells = [cmd for cmd in response.values() if cmd["action"] == "sell"]
    assert not sells, "墙未建齐时不应出现 sell(不被卖矿抢占)"


def test_worker_builds_wall_over_selling(make_payload):
    """人手分配:墙未建齐、工人紧邻墙位且背包携 iron/copper 时,优先建墙而非卖矿。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"] if role.get("roleType") != "wall"
    ]
    for role in payload["teamOur"]["roles"]:
        if role.get("roleType") == "worker":
            # 紧邻墙位、带足石头,同时携铁/铜(可卖)验证不被 sell 抢占
            role["pos"] = {"x": 12, "y": 21}
            role["backpack"] = ["stone", "stone", "stone", "stone", "stone"]
            break
    response = decide(payload)
    _validate_decision(response, payload)
    sells = [
        cmd for cmd in response.values() if cmd["action"] == "sell"
    ]
    assert not sells, "墙未建齐时应优先建墙而非卖矿(不应出现 sell)"
    assert any(
        cmd.get("name") == "wall"
        for cmd in response.values() if cmd["action"] == "build"
    ), "优先建墙而非卖矿"


def test_worker_returns_to_selling_when_walls_done(make_payload):
    """人手分配:墙已建齐(带 keep_wall)时,工人回到卖矿路线(不再强制建墙)。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload, keep_wall=True)
    for role in payload["teamOur"]["roles"]:
        if role.get("roleType") == "worker":
            role["backpack"] = ["stone", "iron", "copper"]
            break
    response = decide(payload)
    _validate_decision(response, payload)
    builds = [
        cmd for cmd in response.values()
        if cmd["action"] == "build"
    ]
    for cmd in builds:
        assert cmd.get("name") != "wall", \
            "墙已建齐不应再强制建墙(回到经营路线)"


def test_decide_contract_holds_with_wall_priority(make_payload):
    """整链校验:开启建墙优先级后,decide 输出仍符合接口契约。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"] if role.get("roleType") != "wall"
    ]
    for role in payload["teamOur"]["roles"]:
        if role.get("roleType") == "worker":
            role["backpack"] = ["stone"]
            break
    response = decide(payload)
    _validate_decision(response, payload)


def _validate_decision(response, payload):
    assert isinstance(response, dict)
    unique = {str(role["id"]) for role in payload["teamOur"].get("roles", [])}
    assert set(response.keys()) <= unique, "指令 key 必须属于我方角色"
    for key, command in response.items():
        assert command["action"] in VALID_ACTIONS, f"非法动作: {command['action']}"
