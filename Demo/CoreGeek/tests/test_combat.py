"""agent.combat 单元测试:夜间武器选择目标逻辑。"""

from agent.combat import (
    _cone_ok,
    _gatling_targets,
    _line_cells,
    _railgun_damage,
    _rocket_targets,
    attack_positions,
    bomb_center,
)
from agent.protocol import Pos
from agent.world import BattleRobot, World


def _robot(robot_id, x, y, health=100, kind="smallRobot", state="",
           target_team="challenger"):
    return BattleRobot(
        robot_id=robot_id, pos=Pos(x, y), health=health,
        kind=kind, state=state, target_team=target_team,
    )


def make_world(towers=(), robots=()):
    """构造 40x30 世界:基地(10,20) + 指定武器 + 指定机器人。"""
    roles = [
        {"id": 10013, "pos": {"x": 10, "y": 20},
         "roleType": "station", "health": 1500, "level": 1},
    ]
    for unit_id, kind, x, y, level, attack_range in towers:
        roles.append({
            "id": unit_id, "pos": {"x": x, "y": y},
            "roleType": kind, "health": 1000,
            "attackPower": 10, "attackRange": attack_range, "level": level,
        })
    payload = {
        "roundNo": 85,
        "mapInfo": {"width": 40, "height": 30, "zones": []},
        "teamOur": {"type": "challenger", "goldNum": 0, "roles": roles},
        "robot": {"roles": []},
    }
    world = World.load(payload)
    world.battle_robots = tuple(robots)
    return world


def _tower(world, unit_id):
    return next(u for u in world.ours if u.unit_id == unit_id)


# ---------- attack_positions ----------

def test_no_reachable_robot_returns_none_and_notes():
    """场景:射程内无机器人返回 None 并记录决策备注。"""
    world = make_world(
        towers=[(10020, "gatling", 9, 24, 1, 4)],
        robots=[_robot(1, 30, 10)],  # 超出射程 4
    )
    assert attack_positions(world, _tower(world, 10020)) is None
    assert any("射程" in note for note in world.notes)


def test_gatling_targets_prefers_threatening_team():
    """场景:优先选 target_team=我方(威胁我方)的机器人。"""
    world = make_world(
        towers=[(10020, "gatling", 9, 24, 1, 4)],
        robots=[
            _robot(1, 8, 24, target_team="challenger"),
            _robot(2, 9, 20, target_team="defender"),
        ],
    )
    targets = attack_positions(world, _tower(world, 10020))
    assert targets == (Pos(8, 24),)


def test_gatling_l1_single_target():
    """场景:1 级加特林只选 1 个目标。"""
    world = make_world(
        towers=[(10020, "gatling", 9, 24, 1, 4)],
        robots=[_robot(1, 8, 24), _robot(2, 10, 24)],
    )
    targets = attack_positions(world, _tower(world, 10020))
    assert len(targets) == 1


def test_gatling_l2_multi_targets_within_cone():
    """场景:2 级加特林可多目标,且目标方向差不超 90 度锥角。"""
    world = make_world(
        towers=[(10020, "gatling", 9, 24, 2, 4)],
        robots=[_robot(1, 8, 24), _robot(2, 9, 25)],
    )
    targets = attack_positions(world, _tower(world, 10020))
    assert len(targets) == 2
    assert _cone_ok(Pos(9, 24), list(targets))


def test_dead_robot_not_targeted():
    """场景:health<=0 的机器人不参与攻击选择。"""
    world = make_world(
        towers=[(10020, "gatling", 9, 24, 1, 4)],
        robots=[_robot(1, 8, 24, health=0), _robot(2, 30, 10)],
    )
    assert attack_positions(world, _tower(world, 10020)) is None


def test_rocket_selects_densest_cluster():
    """场景:火箭按周围 1 格聚集数选目标,目标数=等级。"""
    world = make_world(
        towers=[(10040, "rocket", 7, 24, 1, 20)],
        robots=[
            _robot(1, 8, 24), _robot(2, 8, 25), _robot(3, 8, 26),
            _robot(4, 30, 30),
        ],
    )
    targets = attack_positions(world, _tower(world, 10040))
    assert targets is not None
    assert Pos(8, 25) in targets


def test_railgun_single_best_damage_target():
    """场景:电磁炮单目标,选择能量路径伤害最大的机器人。"""
    world = make_world(
        towers=[(10030, "railgun", 9, 24, 1, 20)],
        robots=[_robot(1, 8, 24, health=30), _robot(2, 30, 10, health=1000)],
    )
    targets = attack_positions(world, _tower(world, 10030))
    assert targets == (Pos(8, 24),)


# ---------- bomb_center ----------

def test_bomb_center_none_without_robots():
    """场景:无机器人时 bomb_center 返回 None。"""
    world = make_world()
    assert bomb_center(world) is None


def test_bomb_center_picks_dense_cluster():
    """场景:选 1 格内邻居最多的机器人作为轰炸中心。"""
    world = make_world(robots=[
        _robot(1, 5, 5, health=40),
        _robot(2, 5, 6, health=60),
        _robot(3, 6, 5, health=500),
        _robot(4, 20, 25, health=800),
    ])
    center = bomb_center(world)
    assert center in (Pos(5, 5), Pos(5, 6), Pos(6, 5))


def test_bomb_center_requires_two_neighbors():
    """场景:任何机器人 1 格内邻居 <2 时返回 None。"""
    world = make_world(robots=[
        _robot(1, 5, 5, health=40),
        _robot(2, 20, 25, health=800),
    ])
    assert bomb_center(world) is None


# ---------- 内部纯函数 ----------

def test_cone_ok_single_point_always_true():
    """场景:单点视角总是合法锥角。"""
    assert _cone_ok(Pos(0, 0), [Pos(1, 1)])


def test_cone_ok_90_degree_boundary():
    """场景:90 度方向差恰在边界(<=90+eps 合法),超过则非法。"""
    origin = Pos(0, 0)
    assert _cone_ok(origin, [Pos(1, 0), Pos(0, 1)])
    assert not _cone_ok(origin, [Pos(5, 0), Pos(-1, 1)])


def test_railgun_damage_pierces_through_line():
    """场景:能量沿直线穿透,依次扣减路径上的机器人血量。"""
    robots = [_robot(1, 6, 24, health=30), _robot(2, 9, 24, health=20)]
    assert _railgun_damage(Pos(9, 24), Pos(6, 24), robots, energy=50) == 50
    assert _railgun_damage(Pos(9, 24), Pos(6, 24), robots, energy=10) == 10
    assert _railgun_damage(Pos(9, 24), Pos(6, 24), [], energy=99) == 0


def test_line_cells_vertical_and_stationary():
    """场景:直线采样包含起点与终点;同一格只返回自身。"""
    assert _line_cells(Pos(0, 0), Pos(0, 3)) == (
        Pos(0, 0), Pos(0, 1), Pos(0, 2), Pos(0, 3),
    )
    horizontal = _line_cells(Pos(0, 0), Pos(3, 0))
    assert horizontal[0] == Pos(0, 0) and horizontal[-1] == Pos(3, 0)
    assert _line_cells(Pos(2, 2), Pos(2, 2)) == (Pos(2, 2),)


def test_rocket_targets_picks_cluster_top():
    """场景:火箭目标选聚集度最高的机器人集合。"""
    robots = [
        _robot(1, 8, 24, health=100),
        _robot(2, 8, 25, health=100),
        _robot(3, 30, 30, health=100),
    ]
    picked = _rocket_targets(robots, count=2)
    assert len(picked) == 2
    assert Pos(8, 24) in picked and Pos(8, 25) in picked


def test_gatling_targets_fallback_first_when_cone_invalid():
    """场景:锥角过滤后无合法组合时回退到最靠前目标。"""
    robots = [
        _robot(1, 1, 0, health=100),
        _robot(2, 5, 0, health=100),
        _robot(3, 0, 3, health=100),
    ]
    picked = _gatling_targets(Pos(0, 0), robots, count=2)
    assert len(picked) == 2
