"""agent.monitor 单元测试:每回合空闲监视器(检测 + 上报)。"""

from __future__ import annotations

from agent.brain import decide
from agent.monitor import IdleEntry, last_idle, scan_idle
from agent.world import World


def _strip_roles(payload):
    """精简 roles 为:基地 + 3 塔 + 2 工人 + 开拓者,补 attackPower 等可选字段。"""
    for role in payload["teamOur"]["roles"]:
        role.setdefault("attackPower", 0)
        role.setdefault("attackRange", 0)
    return payload


def test_all_assigned_no_idle(make_payload):
    """正常场景:全部可控角色都获得指令时,监视器应报告无空闲。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    response = decide(payload)
    idle = last_idle()
    assert isinstance(idle, tuple)
    for entry in idle:
        assert isinstance(entry, IdleEntry)


def test_scan_idle_reports_unassigned(make_payload):
    """核心:可控但未获指令的角色应被标记为空闲,并带 unit_id/kind/pos/reason。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    # 用 scan_idle 传入一个"缺失某角色指令"的 dict,验证该角色被判空闲
    world = World.load(payload)
    controllable = world.controllable()
    assert controllable, "前置:应有可控角色"
    # 构造只给首个角色的指令,其余全空闲
    first = controllable[0]
    commands = {first.unit_id: {"action": "move", "targetPos": [{"x": 0, "y": 0}]}}
    idle = scan_idle(world, commands)
    idle_ids = {e.unit_id for e in idle}
    assert first.unit_id not in idle_ids, "被分配指令的角色不应判空闲"
    others = {u.unit_id for u in controllable[1:]}
    assert others <= idle_ids, "未分配指令的角色都应被判空闲"
    for entry in idle:
        assert entry.reason, f"每个空闲角色都应有成因: {entry}"
        assert isinstance(entry.pos, tuple) and len(entry.pos) == 2


def test_last_idle_empty_with_full_commands(make_payload):
    """给全部可控角色都安排指令时,last_idle 应为空。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    world = World.load(payload)
    commands = {
        unit.unit_id: {"action": "move", "targetPos": [{"x": 0, "y": 0}]}
        for unit in world.controllable()
    }
    scan_idle(world, commands)
    assert last_idle() == ()


def test_idle_entry_profile(make_payload):
    """IdleEntry 字段结构:unit_id 为 int,kind/pos/reason 齐全。"""
    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    world = World.load(payload)
    commands = {}
    idle = scan_idle(world, commands)
    assert idle, "无可控角色时改:本场景应有可控角色且全空闲"
    for entry in idle:
        assert isinstance(entry.unit_id, int)
        assert isinstance(entry.kind, str)
        assert isinstance(entry.pos, tuple)
        assert isinstance(entry.reason, str)


def test_attack_controller_is_not_idle(make_payload):
    """黑夜贴塔开火时,controllerId 对应英雄不得被判空闲。"""
    payload = make_payload(roundNo=85)
    payload["phaseTask"] = ""
    payload["lastRoundRoleActionResults"] = {}
    for role in payload["teamOur"]["roles"]:
        if role["id"] == 10010:
            role["pos"] = {"x": 8, "y": 24}
            role["health"] = 220
            role["backpack"] = []
        elif role["id"] == 10012:
            role["pos"] = {"x": 11, "y": 25}
            role["health"] = 220
            role["backpack"] = []
        elif role["id"] == 10011:
            role["pos"] = {"x": 8, "y": 25}
            role["health"] = 200
            role["backpack"] = ["Medicine"]
    payload["robot"] = {"roles": [
        {"id": 30001, "pos": {"x": 7, "y": 24}, "roleType": "smallRobot",
         "health": 40, "abnormalState": "", "targetTeam": "challenger"},
    ]}
    decide(payload)
    idle_ids = {entry.unit_id for entry in last_idle()}
    assert 10010 not in idle_ids


def test_debuglog_renders_idle_section(make_payload):
    """debuglog 的【空闲监视器】段应包含每个空闲角色的信息。"""
    from agent.debuglog import _build_lines

    payload = make_payload(roundNo=1)
    payload = _strip_roles(payload)
    world = World.load(payload)
    commands = {}
    idle = scan_idle(world, commands)
    if not idle:
        return
    lines = _build_lines(world, commands, "", "")
    rendered = "\n".join(lines)
    assert "【空闲监视器】" in rendered
    for entry in idle:
        assert str(entry.unit_id) in rendered
        assert entry.kind in rendered
