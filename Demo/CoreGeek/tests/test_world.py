"""agent.world 单元测试:数据类加载、World 聚合解析与查询方法。"""

from agent.protocol import Pos, Unit
from agent.world import (
    ERROR_TEXT,
    BattleRobot,
    ErrorInfo,
    PlayerTask,
    ShopItem,
    World,
    backpack_free,
    backpack_item,
    count_item,
    tower_shots,
)


def _payload(**overrides):
    payload = {
        "roundNo": 85,
        "mapInfo": {"width": 40, "height": 30, "zones": [
            {"neutralType": "stone", "pos": {"x": 4, "y": 24}},
            {"neutralType": "vendor", "pos": {"x": 20, "y": 16}},
            {"neutralType": "weaponShop", "pos": {"x": 25, "y": 20}},
            {"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}},
            {"neutralType": "defenderTaskPoint1", "pos": {"x": 23, "y": 14}},
            {"neutralType": "iron", "pos": {"x": 8, "y": 28}},
        ]},
        "teamOur": {
            "type": "challenger",
            "goldNum": 30,
            "totalScore": 280,
            "playerTasks": [
                {"taskType": "自进化类1", "taskPosition": {"x": 14, "y": 14},
                 "coldDownRounds": 0, "scoreReward": 50, "goldReward": 30,
                 "isValid": True, "timeoutRounds": 0},
            ],
            "roles": [
                {"id": 10013, "pos": {"x": 10, "y": 20}, "roleType": "station",
                 "health": 1500, "attackPower": 0, "attackRange": 0, "level": 1},
                {"id": 10020, "pos": {"x": 9, "y": 24}, "roleType": "gatling",
                 "health": 1000, "attackPower": 10, "attackRange": 4, "level": 2,
                 "backPackCapability": 0, "backpack": []},
                {"id": 10010, "pos": {"x": 5, "y": 23}, "roleType": "worker",
                 "health": 220, "attackPower": 0, "attackRange": 0,
                 "backPackCapability": 100,
                 "backpack": ["stone", "IRON", "copper"]},
                {"id": 10011, "pos": {"x": 10, "y": 12}, "roleType": "pioneer",
                 "health": 200, "attackPower": 0, "attackRange": 0,
                 "backPackCapability": 40, "backpack": ["medicine"]},
            ],
        },
        "teamEnemy": {"roles": [
            {"id": 20013, "pos": {"x": 30, "y": 10}, "roleType": "station",
             "health": 1500, "level": 1},
            {"id": 41000, "pos": {"x": 28, "y": 7}, "roleType": "wall",
             "health": 1000, "level": 1},
        ]},
        "robot": {"roles": [
            {"id": 30001, "pos": {"x": 4, "y": 4}, "roleType": "smallRobot",
             "health": 40, "abnormalState": ""},
            {"id": 30004, "pos": {"x": 5, "y": 5}, "roleType": "bossRobot",
             "health": 800, "abnormalState": "dizzy", "targetTeam": "challenger"},
        ]},
        "phaseTask": "自进化任务原文",
        "lastRoundRoleActionResults": {"10010": False, "10011": True},
        "lastSummonTreasureResult": 2,
        "llmResp": '{"x":1,"y":2}',
        "worldNews": {"officialNews": "官方新闻", "folkLegends": "民间传闻"},
        "lastCmdResult": "[exitCode:0]\nok",
        "vendorShopList": [{"name": "stone", "price": 1}, {"name": "iron", "price": 3}],
        "weaponShopList": [{"name": "Medicine", "price": 10}],
        "errors": [{"errorCode": 5, "description": "LLM额度超限"}],
    }
    payload.update(overrides)
    return payload


def _unit(**overrides):
    base = dict(
        unit_id=1, pos=Pos(0, 0), kind="worker", health=100,
        level=0, cooldown=0, attack_range=0, capacity=5,
        backpack=("a", "b"),
    )
    base.update(overrides)
    return Unit(**base)


# ---------- 数据类加载 ----------

def test_shop_item_load_defaults():
    """场景:ShopItem 缺字段时 name 空串 price 0。"""
    item = ShopItem.load({})
    assert item.name == "" and item.price == 0
    assert ShopItem.load({"name": "stone", "price": 3}).price == 3


def test_player_task_load():
    """场景:PlayerTask 逐字段加载,isValid 为 bool。"""
    task = PlayerTask.load({
        "taskType": "自进化类1", "taskPosition": {"x": 14, "y": 14},
        "coldDownRounds": 2, "scoreReward": 50, "goldReward": 30,
        "isValid": True, "timeoutRounds": 5,
    })
    assert task.task_type == "自进化类1"
    assert task.pos == Pos(14, 14)
    assert task.cooldown == 2
    assert task.valid is True


def test_error_info_load_and_reason():
    """场景:ErrorInfo 按 ERROR_TEXT 映射描述,带 description 时拼接。"""
    error = ErrorInfo.load({"errorCode": 5, "description": "额度超限"})
    assert error.code == 5
    assert error.reason() == f"{ERROR_TEXT[5]} | 额度超限"
    bare = ErrorInfo.load({"errorCode": 99, "description": ""})
    assert bare.reason() == "未知错误码"


def test_battle_robot_load_and_dizzy():
    """场景:BattleRobot 加载并识别头晕状态。"""
    robot = BattleRobot.load({
        "id": 30004, "pos": {"x": 5, "y": 5}, "health": 800,
        "roleType": "bossRobot", "abnormalState": "dizzy",
        "targetTeam": "challenger",
    })
    assert robot.robot_id == 30004 and robot.dizzy
    normal = BattleRobot.load({
        "id": 30001, "pos": {"x": 4, "y": 4}, "health": 40,
        "roleType": "smallRobot", "abnormalState": "",
    })
    assert not normal.dizzy


# ---------- World.load 聚合 ----------

def test_world_load_aggregates_all_payload():
    """场景:World.load 聚合顶层字段/新闻/商店/任务/敌人/机器人/错误/上回合结果。"""
    world = World.load(_payload())
    assert world.team_type == "challenger"
    assert world.score == 280
    assert world.phase_task == "自进化任务原文"
    assert world.last_cmd_result == "[exitCode:0]\nok"
    assert world.last_summon == 2
    assert world.llm_resp == '{"x":1,"y":2}'
    assert world.official_news == "官方新闻"
    assert world.folk_legends == "民间传闻"
    assert len(world.vendor_shop) == 2
    assert len(world.weapon_shop) == 1
    assert len(world.player_tasks) == 1
    assert len(world.enemy) == 2
    assert world.last_results == {10010: False, 10011: True}
    assert world.errors[0].code == 5
    assert len(world.battle_robots) == 2
    assert world.attack_power == {10013: 0, 10020: 10, 10010: 0, 10011: 0}


def test_world_load_missing_optional_fields():
    """场景:payload 缺可选字段不崩溃,给定默认值。"""
    world = World.load({
        "roundNo": 1,
        "mapInfo": {"width": 10, "height": 10},
        "teamOur": {},
    })
    assert world.gold == 0
    assert world.team_type == ""
    assert world.ours == ()
    assert world.robots == ()
    assert world.errors == ()


def test_world_delegates_turn_attributes():
    """场景:world 通过 __getattr__ 代理 turn 的 round_no/is_day/zones 等。"""
    world = World.load(_payload())
    assert world.round_no == 85
    assert world.is_day is False  # (85-1)%130=84 >= 70
    assert world.zones[Pos(4, 24)] == "stone"
    assert world.gold == 30


def test_day_index_and_round_in_day():
    """场景:day_index 与 round_in_day 基于 130 回合/天 折算。"""
    world = World.load(_payload())
    assert world.day_index == 1
    assert world.round_in_day == 85
    world = World.load(_payload(roundNo=131))
    assert world.day_index == 2
    assert world.round_in_day == 1


# ---------- 查询方法 ----------

def test_pioneer_returns_single_pioneer_or_none():
    """场景:pioneer() 返回开拓者,否则 None。"""
    world = World.load(_payload())
    assert world.pioneer().kind == "pioneer"
    payload = _payload()
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"] if role["roleType"] != "pioneer"
    ]
    assert World.load(payload).pioneer() is None


def test_all_mines_only_ore_types():
    """场景:all_mines 只含 stone/iron/copper 三类矿区。"""
    world = World.load(_payload())
    mines = world.all_mines()
    assert set(kind for _, kind in mines) == {"stone", "iron"}
    assert (Pos(4, 24), "stone") in mines


def test_vendor_and_weapon_shop_positions():
    """场景:vendor/weaponShop 中立区定位命中,不存在返回 None。"""
    world = World.load(_payload())
    assert world.vendor() == Pos(20, 16)
    assert world.weapon_shop_pos() == Pos(25, 20)
    empty = World.load({
        "roundNo": 1,
        "mapInfo": {"width": 5, "height": 5, "zones": []},
        "teamOur": {},
    })
    assert empty.vendor() is None and empty.weapon_shop_pos() is None


def test_own_task_zones_by_team_type():
    """场景:阵营决定任务区集合,challenger 用 challengerTaskPoint*。"""
    world = World.load(_payload())
    assert world.own_task_zones() == (Pos(14, 14),)
    payload = _payload()
    payload["teamOur"]["type"] = "defender"
    assert World.load(payload).own_task_zones() == (Pos(23, 14),)


def test_vendor_price_case_insensitive_and_default_zero():
    """场景:vendor_price 大小写不敏感,未收录返回 0。"""
    world = World.load(_payload())
    assert world.vendor_price("IRON") == 3
    assert world.vendor_price("copper") == 0
    assert world.vendor_price("") == 0


def test_shop_item_case_insensitive():
    """场景:shop_item 大小写不敏感返回 ShopItem,未收录返回 None。"""
    world = World.load(_payload())
    item = world.shop_item("medicine")
    assert item is not None and item.name == "Medicine" and item.price == 10
    assert world.shop_item("NotExist") is None


def test_occupied_for_build_includes_enemy_robots_zones():
    """场景:建造占用判断汇总我方占地/敌方 footprint/存活机器人/非 land 中立区。"""
    world = World.load(_payload())
    cells = world.occupied_for_build()
    assert Pos(4, 24) in cells  # stone 中立区
    assert Pos(30, 10) in cells and Pos(31, 10) in cells  # 敌基 footprint
    assert Pos(5, 5) in cells  # 存活机器人
    assert Pos(28, 7) in cells  # 敌墙


def test_blocked_includes_enemy_footprints():
    """场景:World.blocked 在 Turn.blocked 基础上叠加敌方 footprint。"""
    world = World.load(_payload())
    blocked = world.blocked(world.workers()[0])
    assert Pos(30, 10) in blocked  # 敌方基地角
    assert Pos(31, 10) in blocked


def test_adjacent_to_zone_rules():
    """场景:周围一格=相邻8格(切比雪夫距离1)且不允许原地。"""
    world = World.load(_payload())
    worker = world.workers()[0]  # (5,23)
    assert world.adjacent_to_zone(worker, Pos(4, 24))
    assert world.adjacent_to_zone(worker, Pos(6, 22))
    assert not world.adjacent_to_zone(worker, Pos(5, 23))  # 自身
    assert not world.adjacent_to_zone(worker, Pos(7, 23))  # 距离2


def test_adjacent_to_any():
    """场景:adjacent_to_any 任一相邻即 True,空集合 False。"""
    world = World.load(_payload())
    worker = world.workers()[0]
    assert world.adjacent_to_any(worker, (Pos(4, 24),))
    assert not world.adjacent_to_any(worker, (Pos(1, 1),))


def test_last_ok_and_llm_limited():
    """场景:last_ok 查询上回合结果;errors 含 code=5 视为 LLM 额度受限。"""
    world = World.load(_payload())
    assert world.last_ok(10010) is False
    assert world.last_ok(10011) is True
    assert world.last_ok(99999) is None
    assert world.llm_limited()
    ok = World.load(_payload())
    ok.errors = ()
    assert not ok.llm_limited()


def test_unit_attack_power_lookup_and_fallback():
    """场景:attack_power 命中返回显式值;缺省时按等级 10/20(火箭加倍)。"""
    world = World.load(_payload())
    gatling = next(u for u in world.ours if u.kind == "gatling")
    assert world.unit_attack_power(gatling) == 10
    world.attack_power = {}
    assert world.unit_attack_power(gatling) == gatling.level * 10
    rocket = _unit(unit_id=10040, kind="rocket", level=3)
    assert world.unit_attack_power(rocket) == 60


def test_note_appends_notes():
    """场景:note 追加决策备注。"""
    world = World.load(_payload())
    world.note("第一条")
    world.note("第二条")
    assert world.notes == ["第一条", "第二条"]


# ---------- 模块级辅助函数 ----------

def test_backpack_item_case_insensitive():
    """场景:backpack_item 按名称匹配返回背包中的实际物品名。"""
    world = World.load(_payload())
    worker = world.workers()[0]  # backpack ["stone","IRON","copper"]
    assert backpack_item(worker, "iron") == "IRON"
    assert backpack_item(worker, "gold") is None


def test_count_item_counts_duplicates_case_insensitive():
    """场景:count_item 对重复同名物品统计数量,大小写不敏感。"""
    unit = _unit(backpack=("stone", "STONE", "Iron", "stone"))
    assert count_item(unit, "stone") == 3
    assert count_item(unit, "iron") == 1
    assert count_item(unit, "copper") == 0


def test_backpack_free():
    """场景:可用容量为 capacity - len(backpack),负数取 0;无容量为 0。"""
    assert backpack_free(_unit(capacity=5, backpack=("a", "b"))) == 3
    assert backpack_free(_unit(capacity=2, backpack=("a", "b", "c"))) == 0
    assert backpack_free(_unit(capacity=None, backpack=("a",))) == 0


def test_tower_shots():
    """场景:tower_shots 至少 1 发,取等级值。"""
    assert tower_shots(_unit(level=0)) == 1
    assert tower_shots(_unit(level=1)) == 1
    assert tower_shots(_unit(level=3)) == 3
