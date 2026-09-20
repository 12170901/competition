"""agent.protocol 单元测试:数据类加载、查询方法与指令构造器。"""

from agent.protocol import (
    DAY_ROUNDS,
    NIGHT_ROUNDS,
    ROUNDS_PER_DAY,
    TOWER_RANGE_BY_LEVEL,
    WALL,
    WORKER,
    Pos,
    Robot,
    Turn,
    Unit,
    accept_task_command,
    attack_command,
    attack_commands,
    build_command,
    buy_command,
    collect_command,
    distance,
    drop_command,
    move_command,
    remove_command,
    sell_command,
    station_footprint,
    submit_answer_command,
    summon_treasure_command,
    use_command,
)


def _unit_raw(**overrides):
    raw = {
        "id": 10010,
        "pos": {"x": 5, "y": 23},
        "roleType": "worker",
        "health": 220,
        "level": 0,
        "cooldown": 0,
        "attackRange": 0,
        "backPackCapability": 100,
        "backpack": ["stone", "iron"],
    }
    raw.update(overrides)
    return raw


def _payload(**overrides):
    payload = {
        "roundNo": 1,
        "mapInfo": {"width": 40, "height": 30, "zones": [
            {"neutralType": "stone", "pos": {"x": 4, "y": 24}},
            {"neutralType": "wall", "pos": {"x": 8, "y": 8}},
        ]},
        "teamOur": {"goldNum": 10, "type": "challenger", "roles": [
            {
                "id": 10013,
                "pos": {"x": 10, "y": 20},
                "roleType": "station",
                "health": 1500,
                "level": 1,
                "backPackCapability": 0,
                "backpack": [],
            },
            {
                "id": 10010,
                "pos": {"x": 5, "y": 23},
                "roleType": "worker",
                "health": 220,
                "level": 0,
                "backPackCapability": 100,
                "backpack": ["stone"],
            },
            {
                "id": 40000,
                "pos": {"x": 8, "y": 8},
                "roleType": "wall",
                "health": 1000,
                "level": 1,
            },
        ]},
        "robot": {"roles": [
            {"id": 30001, "pos": {"x": 4, "y": 4}, "roleType": "smallRobot",
             "health": 40, "abnormalState": "", "targetTeam": "challenger"},
        ]},
    }
    payload.update(overrides)
    return payload


# ---------- Pos ----------

def test_pos_load_and_dump_roundtrip():
    """场景:从字典加载 Pos 再由 dump 输出,应保持 x/y 一致。"""
    pos = Pos.load({"x": 3, "y": 7})
    assert pos == Pos(3, 7)
    assert pos.dump() == {"x": 3, "y": 7}


def test_pos_value_semantics():
    """场景:frozen dataclass,相同字段值应相等且可作为字典 key。"""
    assert Pos(1, 1) == Pos(1, 1)
    assert {Pos(1, 1): "a"}[Pos(1, 1)] == "a"


def test_distance_is_chebyshev():
    """场景:距离定义为切比雪夫距离 max(|dx|,|dy|)。"""
    assert distance(Pos(0, 0), Pos(0, 0)) == 0
    assert distance(Pos(0, 0), Pos(3, 1)) == 3
    assert distance(Pos(5, 5), Pos(2, 9)) == 4


def test_station_footprint_four_cells():
    """场景:基地 2*2,footprint 以左上角为 pos 展开 4 格。"""
    footprint = station_footprint(Pos(10, 20))
    assert footprint == (
        Pos(10, 20), Pos(11, 20), Pos(10, 19), Pos(11, 19),
    )


# ---------- Unit ----------

def test_unit_load_full_fields():
    """场景:完整原始数据加载 Unit,各字段逐项转换。"""
    unit = Unit.load(_unit_raw())
    assert unit.unit_id == 10010
    assert unit.pos == Pos(5, 23)
    assert unit.kind == "worker"
    assert unit.health == 220
    assert unit.level == 0
    assert unit.capacity == 100
    assert unit.backpack == ("stone", "iron")


def test_unit_load_missing_optional_fields_defaults():
    """场景:缺省字段(id/level/cooldown/attackRange/capacity/backpack)提供默认值。"""
    raw = {
        "pos": {"x": 1, "y": 1},
        "roleType": "worker",
        "health": 100,
    }
    unit = Unit.load(raw)
    assert unit.unit_id == 0
    assert unit.level == 0
    assert unit.cooldown == 0
    assert unit.attack_range == 0
    assert unit.capacity is None
    assert unit.backpack == ()


def test_backpack_full_with_capacity():
    """场景:容量有限时,背包数量达到容量即为满。"""
    assert Unit.load(_unit_raw(backPackCapability=3, backpack=["a", "b", "c"])).backpack_full
    assert not Unit.load(_unit_raw(backPackCapability=3, backpack=["a", "b"])).backpack_full


def test_backpack_full_when_capacity_none():
    """场景:容量缺失(建筑类)视为永不满载。"""
    unit = Unit.load(_unit_raw(backPackCapability=None, backpack=["a"]))
    assert unit.capacity is None
    assert not unit.backpack_full


def test_range_of_attack_prefers_explicit_range():
    """场景:attackRange>0 时直接返回显式攻击距离,不走等级表。"""
    unit = Unit.load(_unit_raw(attackRange=7, roleType="gatling", level=3))
    assert unit.range_of_attack() == 7


def test_range_of_attack_level_table():
    """场景:无显式范围时按武器等级查表,gatling 3/5/7。"""
    for level, expected in ((1, 3), (2, 5), (3, 7)):
        unit = Unit.load(_unit_raw(attackRange=0, roleType="gatling", level=level))
        assert unit.range_of_attack() == expected


def test_range_of_attack_clamps_level():
    """场景:level 0 或超上限时,等级被裁剪到 1..len(table)。"""
    low = Unit.load(_unit_raw(attackRange=0, roleType="rocket", level=0))
    high = Unit.load(_unit_raw(attackRange=0, roleType="rocket", level=99))
    assert low.range_of_attack() == TOWER_RANGE_BY_LEVEL["rocket"][0]
    assert high.range_of_attack() == TOWER_RANGE_BY_LEVEL["rocket"][-1]


def test_range_of_attack_unknown_kind():
    """场景:未知武器类型且无显式范围,返回 0。"""
    unit = Unit.load(_unit_raw(attackRange=0, roleType="mystery"))
    assert unit.range_of_attack() == 0


# ---------- Robot ----------

def test_robot_load():
    """场景:Robot 从字典加载 id/pos/health。"""
    robot = Robot.load({"id": 30001, "pos": {"x": 4, "y": 4}, "health": 40})
    assert robot.robot_id == 30001
    assert robot.pos == Pos(4, 4)
    assert robot.health == 40


# ---------- Turn ----------

def test_turn_load_basic():
    """场景:Turn 聚合 roundNo/mapInfo/teamOur/robot 数据。"""
    turn = Turn.load(_payload())
    assert turn.round_no == 1
    assert turn.is_day is True
    assert turn.gold == 10
    assert turn.width == 40
    assert turn.height == 30
    assert turn.zones == {
        Pos(4, 24): "stone",
        Pos(8, 8): "wall",
    }
    assert len(turn.ours) == 3
    assert len(turn.robots) == 1
    assert turn.robots[0].robot_id == 30001


def test_turn_is_day_boundaries():
    """场景:白天 70 回合/黑夜 60 回合;roundNo 从 1 开始,(roundNo-1)%130<70 为白天。"""
    assert ROUNDS_PER_DAY == DAY_ROUNDS + NIGHT_ROUNDS == 130
    assert Turn.load(_payload(roundNo=1)).is_day is True
    assert Turn.load(_payload(roundNo=70)).is_day is True
    assert Turn.load(_payload(roundNo=71)).is_day is False
    assert Turn.load(_payload(roundNo=130)).is_day is False
    assert Turn.load(_payload(roundNo=131)).is_day is True


def test_station_missing_returns_none():
    """场景:无 station 单位时 station() 返回 None。"""
    payload = _payload()
    payload["teamOur"]["roles"] = payload["teamOur"]["roles"][1:]
    assert Turn.load(payload).station() is None


def test_station_present():
    """场景:存在 station 时返回其 Unit。"""
    turn = Turn.load(_payload())
    assert turn.station() is not None
    assert turn.station().kind == "station"


def test_alive_filters_dead_and_kind():
    """场景:alive 只保留 kind 匹配且 health>0 的单位。"""
    payload = _payload()
    payload["teamOur"]["roles"][1]["health"] = 0  # worker 死亡
    turn = Turn.load(payload)
    assert len(turn.alive((WORKER,))) == 0
    walls = turn.alive((WALL,))
    assert len(walls) == 1 and walls[0].kind == "wall"


def test_controllable_sorted_workers_sorted():
    """场景:controllable/workers 仅英雄且按 unit_id 升序。"""
    payload = _payload()
    payload["teamOur"]["roles"].append(
        {"id": 10012, "pos": {"x": 1, "y": 1}, "roleType": "worker",
         "health": 200, "backPackCapability": 100, "backpack": []}
    )
    turn = Turn.load(payload)
    ids = [u.unit_id for u in turn.controllable()]
    assert ids == sorted(ids)
    assert [u.unit_id for u in turn.workers()] == sorted(
        u.unit_id for u in turn.alive((WORKER,))
    )


def test_weapons_sorted_by_position():
    """场景:weapons 按 (x, y) 排序。"""
    payload = _payload()
    payload["teamOur"]["roles"].extend([
        {"id": 10020, "pos": {"x": 9, "y": 24}, "roleType": "gatling",
         "health": 1000, "level": 1},
        {"id": 10040, "pos": {"x": 8, "y": 24}, "roleType": "rocket",
         "health": 1000, "level": 1},
    ])
    turn = Turn.load(payload)
    positions = [(w.pos.x, w.pos.y) for w in turn.weapons()]
    assert positions == sorted(positions)


def test_stone_mines_from_zones():
    """场景:stone_mines 只返回材质为 stone 的中立区。"""
    turn = Turn.load(_payload())
    assert turn.stone_mines() == (Pos(4, 24),)


def test_footprint_station_vs_single():
    """场景:station footprint 4 格,其他单位只有自身一格。"""
    turn = Turn.load(_payload())
    station = turn.station()
    assert turn.footprint(station) == station_footprint(station.pos)
    worker = turn.workers()[0]
    assert turn.footprint(worker) == (worker.pos,)


def test_land_bounds_and_zones():
    """场景:越界或非 land 中立区不可落子,其余默认为 land。"""
    turn = Turn.load(_payload())
    assert turn.land(Pos(0, 0))
    assert not turn.land(Pos(-1, 0))
    assert not turn.land(Pos(0, 100))
    assert not turn.land(Pos(4, 24))  # stone
    assert turn.land(Pos(50, 50)) is False


def test_occupied_cells_includes_footprints():
    """场景:occupied_cells 汇总所有我方单位占地,station 为 4 格。"""
    turn = Turn.load(_payload())
    cells = turn.occupied_cells()
    assert Pos(10, 20) in cells and Pos(11, 19) in cells  # station 两角
    assert Pos(5, 23) in cells  # worker
    assert Pos(8, 8) in cells  # wall


def test_blocked_excludes_moving_pos_and_marks_obstacles():
    """场景:blocked = 非 land 中立区 + 我方占地 + 机器人坐标,但不含移动者自身。"""
    turn = Turn.load(_payload())
    worker = turn.workers()[0]
    blocked = turn.blocked(worker)
    assert worker.pos not in blocked
    assert Pos(4, 24) in blocked  # stone 区
    assert Pos(4, 4) in blocked  # 机器人
    assert Pos(5, 23) not in blocked


# ---------- 指令构造器 ----------

def test_command_constructors():
    """场景:全部指令构造器输出符合接口约定的动作字典。"""
    p = Pos(3, 4)
    assert move_command(p) == {"action": "move", "targetPos": [{"x": 3, "y": 4}]}
    assert collect_command(p) == {"action": "collect", "targetPos": [{"x": 3, "y": 4}]}
    assert build_command(p, "wall") == {
        "action": "build", "targetPos": [{"x": 3, "y": 4}], "name": "wall",
    }
    assert sell_command("iron") == {"action": "sell", "name": "iron", "num": 1}
    assert sell_command("iron", 3) == {"action": "sell", "name": "iron", "num": 3}
    assert buy_command("Medicine", 2) == {
        "action": "buy", "name": "Medicine", "num": 2,
    }
    assert accept_task_command() == {"action": "acceptTask"}
    assert submit_answer_command("42") == {
        "action": "submitAnswer", "taskAnswer": "42",
    }
    assert drop_command("stone") == {"action": "drop", "name": "stone"}
    assert remove_command(p) == {"action": "remove", "targetPos": [{"x": 3, "y": 4}]}


def test_attack_commands_single_and_multi():
    """场景:attack 携带 controllerId(字符串)与 targetPos 数组。"""
    p = Pos(3, 4)
    assert attack_command(10010, p) == {
        "action": "attack",
        "targetPos": [{"x": 3, "y": 4}],
        "controllerId": "10010",
    }
    multi = attack_commands(10010, (Pos(3, 4), Pos(5, 6)))
    assert multi["action"] == "attack"
    assert multi["controllerId"] == "10010"
    assert multi["targetPos"] == [{"x": 3, "y": 4}, {"x": 5, "y": 6}]


def test_summon_treasure_command_uses_list_items():
    """场景:summonTreasure 的 item 字段转为 list,目标为一个坐标。"""
    command = summon_treasure_command(Pos(2, 2), ("AcientTablet", "StarSand"))
    assert command["action"] == "summonTreasure"
    assert command["targetPos"] == [{"x": 2, "y": 2}]
    assert command["item"] == ["AcientTablet", "StarSand"]


def test_use_command_with_and_without_pos():
    """场景:use 无 pos 时不带 targetPos,有 pos 时携带单个目标。"""
    assert use_command("Medicine") == {"action": "use", "name": "Medicine"}
    assert use_command("WeaponUpgradeVoucher1", Pos(1, 1)) == {
        "action": "use", "name": "WeaponUpgradeVoucher1",
        "targetPos": [{"x": 1, "y": 1}],
    }
