from math import atan2, degrees

from .protocol import Pos, Unit, distance
from .world import BattleRobot, World, tower_shots


def attack_positions(turn: World, tower: Unit) -> tuple[Pos, ...] | None:
    reach = tower.range_of_attack()
    station = turn.station()
    base = station.pos if station else tower.pos
    robots = [
        robot for robot in turn.robots
        if robot.health > 0 and distance(tower.pos, robot.pos) <= reach
    ]
    if not robots:
        turn.note(f"武器 {tower.unit_id}({tower.kind}) 射程 {reach} 内没有可攻击机器人")
        return None
    robots.sort(
        key=lambda robot: (
            0 if robot.target_team == turn.team_type else 1,
            distance(base, robot.pos),
            distance(tower.pos, robot.pos),
            -robot.health,
            robot.robot_id,
        )
    )
    if tower.kind == "railgun":
        energy = turn.unit_attack_power(tower)
        target = _railgun_target(tower, robots, energy)
        return (target,) if target else None
    count = tower_shots(tower) if tower.kind in ("gatling", "rocket") else 1
    if tower.kind == "rocket":
        picked = _rocket_targets(robots, count)
        return picked or None
    picked = _gatling_targets(tower.pos, robots, count)
    return picked or None


def bomb_center(turn: World) -> Pos | None:
    robots = [robot for robot in turn.robots if robot.health > 0]
    if not robots:
        return None
    best: tuple[int, int, int, Pos] | None = None
    station = turn.station()
    for robot in robots:
        hits = sum(
            1 for other in robots
            if distance(robot.pos, other.pos) <= 1
        )
        near = -distance(station.pos, robot.pos) if station else 0
        candidate = (hits, near, -robot.robot_id, robot.pos)
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    return None if best is None or best[0] < 2 else best[3]


def _gatling_targets(origin: Pos, robots: list[BattleRobot], count: int) -> tuple[Pos, ...]:
    if count <= 1:
        return (robots[0].pos,)
    chosen: list[BattleRobot] = []
    for robot in robots:
        trial = chosen + [robot]
        if _cone_ok(origin, [item.pos for item in trial]):
            chosen.append(robot)
        if len(chosen) >= count:
            break
    if not chosen:
        chosen = robots[:1]
    return tuple(item.pos for item in chosen)


def _cone_ok(origin: Pos, points: list[Pos]) -> bool:
    if len(points) <= 1:
        return True
    angles = [atan2(pos.y - origin.y, pos.x - origin.x) for pos in points]
    for i, left in enumerate(angles):
        for right in angles[i + 1:]:
            delta = abs(degrees(left - right)) % 360
            delta = min(delta, 360 - delta)
            if delta > 90.0 + 1e-6:
                return False
    return True


def _rocket_targets(robots: list[BattleRobot], count: int) -> tuple[Pos, ...]:
    remaining = list(robots)
    picked: list[Pos] = []
    while remaining and len(picked) < count:
        best = max(
            remaining,
            key=lambda robot: (
                sum(1 for other in remaining if distance(robot.pos, other.pos) <= 1),
                robot.health,
                -robot.robot_id,
            ),
        )
        picked.append(best.pos)
        remaining = [robot for robot in remaining if robot.pos != best.pos]
    return tuple(picked)


def _railgun_target(
    tower: Unit, robots: list[BattleRobot], energy: int,
) -> Pos | None:
    best: tuple[int, int, Pos] | None = None
    for robot in robots:
        damage = _railgun_damage(tower.pos, robot.pos, robots, energy)
        score = (damage, -distance(tower.pos, robot.pos), robot.pos)
        if best is None or score[0] > best[0] or (
            score[0] == best[0] and score[1] > best[1]
        ):
            best = (score[0], score[1], robot.pos)
    return None if best is None else best[2]


def _railgun_damage(
    origin: Pos, end: Pos, robots: list[BattleRobot], energy: int,
) -> int:
    path = set(_line_cells(origin, end))
    ordered = sorted(
        (robot for robot in robots if robot.pos in path),
        key=lambda robot: (distance(origin, robot.pos), robot.robot_id),
    )
    remain = energy
    total = 0
    for robot in ordered:
        if remain <= 0:
            break
        hit = min(remain, robot.health)
        total += hit
        remain -= hit
    return total


def _line_cells(start: Pos, end: Pos) -> tuple[Pos, ...]:
    dx = end.x - start.x
    dy = end.y - start.y
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return (start,)
    cells = []
    for index in range(steps + 1):
        x = start.x + round(index * dx / steps)
        y = start.y + round(index * dy / steps)
        cells.append(Pos(x, y))
    return tuple(cells)
