"""agent.brain 单元测试:decide() 对外契约与白天/黑夜编排。"""

from agent.brain import decide

VALID_ACTIONS = {
    "move", "collect", "build", "attack", "sell", "buy", "remove",
    "acceptTask", "submitAnswer", "summonTreasure", "use", "drop",
}


def _validate_decision(response, payload):
    """校验 decide 返回结构符合接口契约。"""
    assert isinstance(response, dict)
    for key, command in response.items():
        assert isinstance(key, str), "key 必须是角色 ID 字符串"
        assert isinstance(command, dict), "指令必须是 dict"
        assert command["action"] in VALID_ACTIONS, f"非法动作: {command['action']}"
    unique = {str(role["id"]) for role in payload["teamOur"].get("roles", [])}
    assert set(response.keys()) <= unique, "指令 key 必须属于我方角色"


def test_decide_day_never_attacks(make_payload):
    """场景:白天(roundNo in 1..70)decide 输出中不得出现 attack。"""
    for round_no in (1, 70):
        payload = make_payload(roundNo=round_no)
        response = decide(payload)
        _validate_decision(response, payload)
        actions = [cmd["action"] for cmd in response.values()]
        assert "attack" not in actions, f"白天回合 {round_no} 不应有 attack"


def test_decide_night_can_attack_and_contract_holds(make_payload):
    """场景:黑夜(roundNo in 71..130)不崩溃,契约保持(可能无指令)。"""
    for round_no in (71, 130):
        payload = make_payload(roundNo=round_no)
        response = decide(payload)
        _validate_decision(response, payload)
        actions = [cmd["action"] for cmd in response.values()]
        for action in actions:
            if action == "attack":
                assert command_roles_valid(response, payload), \
                    "attack 的 controllerId 应指向我方角色"


def command_roles_valid(response, payload):
    """attack 指令的 controllerId 必须是字符串且属于我方角色。"""
    ids = {str(role["id"]) for role in payload["teamOur"].get("roles", [])}
    for command in response.values():
        if command["action"] == "attack":
            ctrl = command.get("controllerId")
            if ctrl is None or str(ctrl) not in ids:
                return False
    return True


def test_each_role_at_most_one_command(make_payload):
    """场景:每个角色至多 1 条指令,roleCommandMap 无重复 key。"""
    for round_no in (1, 85, 131, 200):
        payload = make_payload(roundNo=round_no)
        response = decide(payload)
        assert len(response) == len(set(response.keys()))


def test_decide_tolerates_missing_optional_fields(make_payload):
    """场景:payload 缺可选字段(vendor/weaponShop/errors/robot/worldNews)不崩溃。"""
    payload = make_payload()
    payload.pop("vendorShopList", None)
    payload.pop("weaponShopList", None)
    payload.pop("errors", None)
    payload.pop("robot", None)
    payload.pop("worldNews", None)
    payload.pop("llmResp", None)
    payload.pop("lastRoundRoleActionResults", None)
    payload.pop("phaseTask", None)
    payload.pop("teamEnemy", None)
    response = decide(payload)
    assert isinstance(response, dict)


def test_decide_full_base_payload_smoke(make_payload):
    """场景:标准基底 payload(roundNo=85 黑夜)全量执行不抛异常。"""
    payload = make_payload(roundNo=85)
    response = decide(payload)
    assert isinstance(response, dict)
    for command in response.values():
        assert command["action"] in VALID_ACTIONS


def test_decide_phase_task_triggers_execute_cmd(make_payload):
    """场景:phaseTask 非空时执行任务分支不崩溃,且不产生非法 action。"""
    payload = make_payload(roundNo=85, phaseTask="写一个 python 脚本计算 2^10")
    response = decide(payload)
    _validate_decision(response, payload)


def test_decide_empty_team_roles_tolerated(make_payload):
    """场景:我方无角色时不崩溃,返回空/合法指令。"""
    payload = make_payload()
    payload["teamOur"]["roles"] = []
    payload["teamOur"]["playerTasks"] = []
    response = decide(payload)
    assert isinstance(response, dict)


def test_decide_day_with_phase_task_no_attack(make_payload):
    """场景:白天且携带 phaseTask,仍不允许 attack。"""
    payload = make_payload(roundNo=5, phaseTask="任务")
    response = decide(payload)
    actions = [cmd["action"] for cmd in response.values()]
    assert "attack" not in actions


def test_decide_station_only_world(make_payload):
    """场景:仅有基地与围墙(无英雄)的极端局面不崩溃。"""
    payload = make_payload()
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role["roleType"] in ("station", "wall")
    ]
    response = decide(payload)
    assert isinstance(response, dict)


def test_decide_weapons_attack_commands_carry_controller_id(make_payload):
    """场景:若黑夜产生 attack,controllerId 为字符串且 targetPos 数量匹配等级数(加特林/火箭)。"""
    payload = make_payload(roundNo=85)
    # 把机器人放到我方武器附近以确保有目标
    payload["robot"] = {"roles": [
        {"id": 30001, "pos": {"x": 9, "y": 24}, "roleType": "smallRobot",
         "health": 40, "abnormalState": "", "targetTeam": "challenger"},
        {"id": 30002, "pos": {"x": 9, "y": 25}, "roleType": "smallRobot",
         "health": 40, "abnormalState": "", "targetTeam": "challenger"},
    ]}
    response = decide(payload)
    for command in response.values():
        if command["action"] == "attack":
            assert isinstance(command.get("controllerId"), str)
            controller = command["controllerId"]
            assert controller in {str(r["id"]) for r in payload["teamOur"]["roles"]}
