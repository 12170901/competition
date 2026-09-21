from typing import Any

from .combat import attack_positions, bomb_center
from .debuglog import set_extra, write_round_log
from .grid import next_step
from .monitor import scan_idle
from .protocol import (
    Pos,
    TOWER_TYPES,
    Unit,
    WALL,
    WALL_MATERIAL,
    WEAPON_BUILD_COST,
    accept_task_command,
    attack_commands,
    build_command,
    buy_command,
    collect_command,
    distance,
    drop_command,
    move_command,
    sell_command,
    station_footprint,
    submit_answer_command,
    summon_treasure_command,
    use_command,
)
from .tasks import (
    can_prompt,
    consume_names,
    mark_prompt,
    missing_treasure_items,
    next_task_command,
    observe,
    task_prompt,
    treasure_prompt,
    treasure_ready,
)
from .world import HERO_MAX_HP, World, backpack_item, count_item

TOWER_LOADOUT = ("gatling", "railgun", "rocket")
STONE_KEEP = 4
RECALL_FROM = 56
_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)
UPGRADE_MAP = {
    "WeaponUpgradeVoucher1": (TOWER_TYPES, 1),
    "WeaponUpgradeVoucher2": (TOWER_TYPES, 2),
    "WallUpgradeVoucher1": ((WALL,), 1),
    "WallUpgradeVoucher2": ((WALL,), 2),
    "StationUpgradeVoucher1": (("station",), 1),
    "StationUpgradeVoucher2": (("station",), 2),
}


def decide(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    turn = World.load(payload)
    memory = observe(turn)
    commands: dict[int, dict[str, Any]] = {}
    prompt = ""
    execute_cmd = ""
    if turn.is_day:
        execute_cmd, prompt = _day(turn, memory, commands)
    else:
        execute_cmd, prompt = _night(turn, memory, commands)
    scan_idle(turn, commands)
    set_extra(prompt, execute_cmd)
    write_round_log(turn, commands, prompt, execute_cmd)
    return {str(key): value for key, value in commands.items()}


def _day(
    turn: World,
    memory,
    commands: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    sites = _tower_sites(turn)
    order = _wall_order(turn)
    standing_towers = {unit.pos for unit in turn.weapons()}
    standing_walls = {unit.pos for unit in turn.walls()}
    occupied = turn.occupied_for_build()
    towers_missing = [pos for pos in sites if pos not in standing_towers]
    walls_missing = [pos for pos in order if pos not in standing_walls]
    free_towers = [pos for pos in towers_missing if pos not in occupied]
    free_walls = [pos for pos in walls_missing if pos not in occupied]
    claimed: set[Pos] = set()
    gold_left = turn.gold
    builds_left = max(0, 3 - len(turn.weapons()))
    execute_cmd = ""
    prompt = ""

    pioneer = turn.pioneer()
    if pioneer is not None:
        execute_cmd, prompt = _pioneer_day(
            turn, pioneer, memory, claimed, commands,
        )

    for role in turn.workers():
        if role.unit_id in commands:
            continue
        gold_left, builds_left = _worker_day(
            turn, role, sites, free_towers, free_walls, claimed,
            commands, gold_left, builds_left, memory,
        )
    return execute_cmd, prompt


def _worker_day(
    turn: World,
    role: Unit,
    sites: tuple[Pos, ...],
    towers_missing: list[Pos],
    walls_missing: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    gold_left: int,
    builds_left: int,
    memory,
) -> tuple[int, int]:
    if _try_heal(role, commands):
        return gold_left, builds_left
    if _try_upgrade_or_fix(turn, role, commands):
        return gold_left, builds_left
    if towers_missing and gold_left >= WEAPON_BUILD_COST and builds_left > 0:
        for index, site in enumerate(sites):
            if site in towers_missing and site not in claimed:
                if _build_or_walk(
                    turn, role, site, TOWER_LOADOUT[index], claimed, commands,
                ):
                    if role.unit_id in commands and commands[role.unit_id]["action"] == "build":
                        gold_left -= WEAPON_BUILD_COST
                        builds_left -= 1
                        if site in towers_missing:
                            towers_missing.remove(site)
                    return gold_left, builds_left
    if _in_recall(turn):
        if walls_missing and count_item(role, WALL_MATERIAL):
            for site in list(walls_missing):
                if site in claimed or distance(role.pos, site) > 1 or role.pos == site:
                    continue
                if _build_or_walk(turn, role, site, WALL, claimed, commands):
                    if (
                        role.unit_id in commands
                        and commands[role.unit_id]["action"] == "build"
                    ):
                        walls_missing.remove(site)
                    return gold_left, builds_left
        _recall_to_tower(turn, role, claimed, commands)
        return gold_left, builds_left
    if walls_missing:
        if _build_walls(turn, role, walls_missing, claimed, commands):
            return gold_left, builds_left
    if _try_shop(turn, role, claimed, commands, gold_left, memory):
        if role.unit_id in commands and commands[role.unit_id]["action"] == "buy":
            item = turn.shop_item(commands[role.unit_id]["name"])
            if item:
                gold_left -= item.price
        return gold_left, builds_left
    if _try_sell(turn, role, claimed, commands, walls_missing):
        return gold_left, builds_left
    _mine(turn, role, claimed, commands)
    return gold_left, builds_left


def _in_recall(turn: World) -> bool:
    return bool(turn.is_day) and turn.round_in_day >= RECALL_FROM


def _recall_to_tower(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    weapons = turn.weapons()
    if weapons:
        tower = min(
            weapons,
            key=lambda unit: (distance(role.pos, unit.pos), unit.unit_id),
        )
        target = tower.pos
    else:
        station = turn.station()
        if station is None:
            return False
        target = station.pos
    if role.pos != target and distance(role.pos, target) <= 1:
        return False
    return _walk_adjacent(turn, role, target, claimed, commands)


def _nearest_mine(
    turn: World,
    role: Unit,
    kind: str,
    claimed: set[Pos],
) -> Pos | None:
    candidates = [
        pos for pos, name in turn.all_mines()
        if name == kind and pos not in claimed
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda pos: (distance(role.pos, pos), pos.x, pos.y),
    )


def _build_walls(
    turn: World,
    role: Unit,
    walls_missing: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    """墙未建齐时,优先负责建墙:先采/走向石头矿,有石头则建墙。"""
    stones = count_item(role, WALL_MATERIAL)
    mine = _adjacent_mine(turn, role, "stone")
    if mine is not None and stones < STONE_KEEP:
        commands[role.unit_id] = collect_command(mine)
        claimed.add(mine)
        return True
    if stones:
        for site in walls_missing:
            if site not in claimed:
                if _build_or_walk(turn, role, site, WALL, claimed, commands):
                    if (
                        role.unit_id in commands
                        and commands[role.unit_id]["action"] == "build"
                    ):
                        walls_missing.remove(site)
                return True
    stone = _nearest_mine(turn, role, WALL_MATERIAL, claimed)
    if stone is not None:
        if role.pos != stone and distance(role.pos, stone) <= 1:
            commands[role.unit_id] = collect_command(stone)
            claimed.add(stone)
            return True
        return _walk_adjacent(turn, role, stone, claimed, commands)
    return False


def _pioneer_day(
    turn: World,
    role: Unit,
    memory,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    if _try_heal(role, commands):
        return "", _maybe_prompt(turn, memory)
    if turn.phase_task:
        return _run_task(turn, role, memory, claimed, commands)
    if _in_recall(turn):
        _recall_to_tower(turn, role, claimed, commands)
        return "", _maybe_prompt(turn, memory)
    if _try_accept_task(turn, role, claimed, commands):
        return "", _maybe_prompt(turn, memory)
    if _try_treasure(turn, role, memory, claimed, commands):
        return "", _maybe_prompt(turn, memory)
    if _try_shop(turn, role, claimed, commands, turn.gold, memory):
        return "", _maybe_prompt(turn, memory)
    if _try_sell(turn, role, claimed, commands, []):
        return "", _maybe_prompt(turn, memory)
    return "", _maybe_prompt(turn, memory)


def _run_task(
    turn: World,
    role: Unit,
    memory,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    execute_cmd, answer = next_task_command(turn, memory)
    if answer:
        commands[role.unit_id] = submit_answer_command(answer)
        execute_cmd = ""
    elif not _near_own_task(turn, role):
        _walk_to_task(turn, role, claimed, commands)
        execute_cmd = ""
    prompt = ""
    if can_prompt(turn, memory):
        prompt = task_prompt(turn)
        mark_prompt(turn, memory)
    return execute_cmd, prompt


def _night(
    turn: World, memory, commands: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    claimed: set[Pos] = set()
    busy: set[int] = set()
    execute_cmd = ""
    prompt = ""
    if turn.phase_task:
        pioneer = turn.pioneer()
        if pioneer is not None:
            execute_cmd, prompt = _run_task(
                turn, pioneer, memory, claimed, commands,
            )
            busy.add(pioneer.unit_id)
    for role in turn.controllable():
        if role.unit_id in busy:
            continue
        if _try_heal(role, commands):
            busy.add(role.unit_id)
            continue
        if _try_night_item(turn, role, commands):
            busy.add(role.unit_id)
    free = [role for role in turn.controllable() if role.unit_id not in busy]
    for role, tower in _assign_weapons(free, turn.weapons()):
        if distance(role.pos, tower.pos) <= 1:
            if tower.cooldown > 0:
                turn.note(
                    f"武器 {tower.unit_id} 仍在冷却 cooldown={tower.cooldown}，本回合不能 attack"
                )
                continue
            targets = attack_positions(turn, tower)
            if targets:
                commands[tower.unit_id] = attack_commands(role.unit_id, targets)
            continue
        step = _step_toward(turn, role, tower.pos, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)
    if not prompt:
        prompt = _maybe_prompt(turn, memory)
    return execute_cmd, prompt


def _maybe_prompt(turn: World, memory) -> str:
    if turn.phase_task:
        return ""
    if memory.treasure_done or not can_prompt(turn, memory):
        return ""
    missing = memory.treasure_pos is None or not memory.treasure_items
    if not (
        turn.round_in_day == 1
        or turn.last_summon in (2, 3)
        or (missing and turn.round_in_day <= 2)
    ):
        return ""
    mark_prompt(turn, memory)
    return treasure_prompt(turn, memory)


def _try_heal(role: Unit, commands: dict[int, dict[str, Any]]) -> bool:
    cap = HERO_MAX_HP.get(role.kind)
    if cap is None or role.health >= cap:
        return False
    name = backpack_item(role, "Medicine")
    if name is None:
        return False
    commands[role.unit_id] = use_command(name)
    return True


def _try_upgrade_or_fix(
    turn: World, role: Unit, commands: dict[int, dict[str, Any]],
) -> bool:
    for voucher, (kinds, level) in UPGRADE_MAP.items():
        name = backpack_item(role, voucher)
        if name is None:
            continue
        for unit in turn.ours:
            if unit.kind not in kinds or unit.level != level:
                continue
            if not _adjacent_building(turn, role, unit):
                continue
            commands[role.unit_id] = use_command(name, unit.pos)
            return True
    fixer = backpack_item(role, "WallFixer")
    if fixer:
        for wall in turn.walls():
            if wall.health >= _wall_max(wall.level):
                continue
            if _adjacent_building(turn, role, wall):
                commands[role.unit_id] = use_command(fixer, wall.pos)
                return True
    return False


def _try_night_item(
    turn: World, role: Unit, commands: dict[int, dict[str, Any]],
) -> bool:
    center = bomb_center(turn)
    if center is None:
        return False
    for item_name in ("DizzyWeapon", "Bomb"):
        name = backpack_item(role, item_name)
        if name is None:
            continue
        commands[role.unit_id] = use_command(name, center)
        return True
    return False


def _try_sell(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    walls_missing: list[Pos],
) -> bool:
    vendor = turn.vendor()
    if vendor is None:
        return False
    keep_stone = 1 if walls_missing else 0
    ore = _sellable_ore(role, turn, keep_stone)
    if ore is None:
        return False
    if turn.adjacent_to_zone(role, vendor):
        name, num = ore
        commands[role.unit_id] = sell_command(name, num)
        return True
    if role.backpack_full or num_ores(role) >= 8:
        return _walk_adjacent(turn, role, vendor, claimed, commands)
    return False


def _try_shop(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    gold_left: int,
    memory,
) -> bool:
    shop = turn.weapon_shop_pos()
    if shop is None or role.backpack_full:
        return False
    want = _wanted_item(turn, role, gold_left, memory)
    if want is None:
        return False
    if turn.adjacent_to_zone(role, shop):
        commands[role.unit_id] = buy_command(want, 1)
        return True
    urgent = want.lower() in {item.lower() for item in memory.treasure_items} or want.lower().endswith("voucher1")
    if urgent or gold_left >= 100:
        return _walk_adjacent(turn, role, shop, claimed, commands)
    return False


def _wanted_item(turn: World, role: Unit, gold_left: int, memory) -> str | None:
    if treasure_ready(turn, memory) or memory.treasure_items:
        for name in missing_treasure_items(role, memory.treasure_items):
            item = turn.shop_item(name)
            if item and item.price <= gold_left:
                return item.name
    wishlist: list[str] = []
    if any(unit.kind in TOWER_TYPES and unit.level == 1 for unit in turn.ours):
        wishlist.append("WeaponUpgradeVoucher1")
    if turn.station() and turn.station().level == 1:
        wishlist.append("StationUpgradeVoucher1")
    if any(unit.kind in TOWER_TYPES and unit.level == 2 for unit in turn.ours):
        wishlist.append("WeaponUpgradeVoucher2")
    cap = HERO_MAX_HP.get(role.kind, 0)
    if role.health < cap and backpack_item(role, "Medicine") is None:
        wishlist.append("Medicine")
    if any(wall.health < _wall_max(wall.level) for wall in turn.walls()):
        wishlist.append("WallFixer")
    wishlist.extend(("DizzyWeapon", "Bomb"))
    for name in wishlist:
        item = turn.shop_item(name)
        if item is None or item.price > gold_left:
            continue
        if backpack_item(role, item.name):
            continue
        if name.startswith("Weapon") and gold_left < item.price + 0:
            continue
        return item.name
    return None


def _try_accept_task(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    tasks = [task for task in turn.player_tasks if task.valid]
    if not tasks:
        turn.note(
            f"开拓者 {role.unit_id} 无法领任务：isValid=false 或冷却中/任务已做完"
        )
        return False
    if _near_own_task(turn, role):
        commands[role.unit_id] = accept_task_command()
        return True
    target = min(tasks, key=lambda task: distance(role.pos, task.pos))
    return _walk_adjacent(turn, role, target.pos, claimed, commands)


def _try_treasure(
    turn: World,
    role: Unit,
    memory,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    if not treasure_ready(turn, memory) or memory.treasure_pos is None:
        return False
    missing = missing_treasure_items(role, memory.treasure_items)
    if missing:
        return False
    target = memory.treasure_pos
    if turn.adjacent_to_zone(role, target):
        items = consume_names(role, memory.treasure_items)
        commands[role.unit_id] = summon_treasure_command(target, items)
        return True
    return _walk_adjacent(turn, role, target, claimed, commands)


def _near_own_task(turn: World, role: Unit) -> bool:
    cells = turn.own_task_zones()
    if cells and turn.adjacent_to_any(role, cells):
        return True
    return any(
        turn.adjacent_to_zone(role, task.pos) for task in turn.player_tasks
    )


def _walk_to_task(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    cells = turn.own_task_zones() or tuple(task.pos for task in turn.player_tasks)
    if not cells:
        return False
    target = min(cells, key=lambda pos: distance(role.pos, pos))
    return _walk_adjacent(turn, role, target, claimed, commands)


def _adjacent_mine(turn: World, role: Unit, kind: str | None = None) -> Pos | None:
    mines = []
    for pos, name in turn.all_mines():
        if kind and name != kind:
            continue
        if role.pos != pos and distance(role.pos, pos) <= 1:
            mines.append(pos)
    mines.sort(key=lambda pos: (distance(role.pos, pos), pos.x, pos.y))
    return mines[0] if mines else None


def _mine(
    turn: World,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    if role.backpack_full:
        extra = next((item for item in role.backpack if item.lower() not in ("stone", "iron", "copper") and "voucher" not in item.lower()), None)
        if extra and turn.vendor() is None:
            commands[role.unit_id] = drop_command(extra)
            return True
        vendor = turn.vendor()
        if vendor is not None:
            return _walk_adjacent(turn, role, vendor, claimed, commands)
        return False
    ranked = sorted(
        (
            (pos, kind) for pos, kind in turn.all_mines()
            if pos not in claimed
        ),
        key=lambda item: (
            -turn.vendor_price(item[1]),
            distance(role.pos, item[0]),
            item[0].x,
            item[0].y,
        ),
    )
    failed = turn.last_ok(role.unit_id) is False
    for pos, _kind in ranked:
        if failed and distance(role.pos, pos) <= 1:
            continue
        if role.pos != pos and distance(role.pos, pos) <= 1:
            commands[role.unit_id] = collect_command(pos)
            claimed.add(pos)
            return True
        if _walk_adjacent(turn, role, pos, claimed, commands):
            return True
    return False


def _build_or_walk(
    turn: World,
    role: Unit,
    target: Pos,
    name: str,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    if role.pos != target and distance(role.pos, target) <= 1:
        commands[role.unit_id] = build_command(target, name)
        claimed.add(target)
        return True
    step = _step_toward(turn, role, target, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _walk_adjacent(
    turn: World,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    if role.pos != target and distance(role.pos, target) <= 1:
        return False
    step = _step_toward(turn, role, target, claimed)
    if step is None:
        return False
    commands[role.unit_id] = move_command(step)
    return True


def _step_toward(
    turn: World,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    *,
    inside_only: bool = False,
) -> Pos | None:
    for stand in _stand_cells(turn, role, target, claimed, inside_only):
        if stand == role.pos:
            return None
        step = next_step(turn, role, stand)
        if step is None or step in claimed:
            continue
        claimed.add(step)
        return step
    turn.note(
        f"角色 {role.unit_id} 无法走向 ({target.x},{target.y})："
        "周围落脚点被占、越界、或被建筑/中立单位/机器人挡住"
    )
    return None


def _stand_cells(
    turn: World,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    inside_only: bool = False,
) -> list[Pos]:
    station = turn.station()
    footprint = station_footprint(station.pos) if station else ()
    blocked = turn.blocked(role)
    cells = [
        pos for pos in _neighbours(target)
        if turn.land(pos)
        and pos not in blocked
        and (pos == role.pos or pos not in claimed)
        and (
            not inside_only
            or _footprint_distance(pos, footprint) <= 1
        )
    ]
    cells.sort(key=lambda pos: (_footprint_distance(pos, footprint), pos.x, pos.y))
    return cells


def _map_center(turn: World) -> Pos:
    return Pos(turn.width // 2, turn.height // 2)


def _tower_sites(turn: World) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    center = _map_center(turn)
    cells = [
        pos for pos in _cells_at_distance(station.pos, 1) if turn.land(pos)
    ]
    cells.sort(
        key=lambda pos: (
            distance(pos, center),
            _footprint_distance(pos, footprint),
            pos.x,
            pos.y,
        )
    )
    return tuple(cells[:3])


def _station_bounds(turn: World) -> tuple[int, int, int, int] | None:
    station = turn.station()
    if station is None:
        return None
    footprint = station_footprint(station.pos)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    return min(xs), max(xs), min(ys), max(ys)


def _wall_ring(turn: World) -> tuple[Pos, ...]:
    """基地占地切比雪夫距离 2 的完整一圈可建墙格(黄区外圈)。"""
    station = turn.station()
    if station is None:
        return ()
    return tuple(
        pos for pos in _cells_at_distance(station.pos, 2) if turn.land(pos)
    )


def _center_facing_sides(turn: World) -> frozenset[str]:
    """指向地图中心的那两条边:东/西与南/北各取朝向中心的一侧。"""
    bounds = _station_bounds(turn)
    if bounds is None:
        return frozenset()
    xmin, xmax, ymin, ymax = bounds
    center = _map_center(turn)
    dx = center.x - (xmin + xmax) / 2
    dy = center.y - (ymin + ymax) / 2
    sides: set[str] = set()
    if dx > 0:
        sides.add("east")
    elif dx < 0:
        sides.add("west")
    if dy > 0:
        sides.add("north")
    elif dy < 0:
        sides.add("south")
    return frozenset(sides)


def _wall_sides(pos: Pos, turn: World) -> frozenset[str]:
    bounds = _station_bounds(turn)
    if bounds is None:
        return frozenset()
    xmin, xmax, ymin, ymax = bounds
    sides: set[str] = set()
    if pos.y == ymin - 2:
        sides.add("south")
    if pos.y == ymax + 2:
        sides.add("north")
    if pos.x == xmin - 2:
        sides.add("west")
    if pos.x == xmax + 2:
        sides.add("east")
    return frozenset(sides)


def _wall_order(turn: World) -> tuple[Pos, ...]:
    """第一天目标墙位:朝向地图中心的约一半围墙,按距中心从近到远建造。

    旧实现按整边排序并在东南侧留缺口,挑战者(左上)的缺口正好开在朝向
    中心的正面,且会把背向中心的边也排进建造清单。现在只保留中心朝向
    的两条边(约 50%),背面自然留作出入口。
    """
    center = _map_center(turn)
    facing = _center_facing_sides(turn)
    chosen = [
        pos for pos in _wall_ring(turn)
        if _wall_sides(pos, turn) & facing
    ]
    if not chosen:
        ring = list(_wall_ring(turn))
        ring.sort(key=lambda pos: (distance(pos, center), pos.x, pos.y))
        quota = max(1, (len(ring) + 1) // 2) if ring else 0
        return tuple(ring[:quota])
    chosen.sort(key=lambda pos: (distance(pos, center), pos.x, pos.y))
    return tuple(chosen)


def _cells_at_distance(station_pos: Pos, radius: int) -> tuple[Pos, ...]:
    footprint = station_footprint(station_pos)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    cells = []
    for x in range(min(xs) - radius, max(xs) + radius + 1):
        for y in range(min(ys) - radius, max(ys) + radius + 1):
            pos = Pos(x, y)
            if pos in footprint:
                continue
            if _footprint_distance(pos, footprint) == radius:
                cells.append(pos)
    return tuple(cells)


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    if not footprint:
        return 0
    return min(distance(pos, cell) for cell in footprint)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(
        Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS
    )


def _assign_weapons(
    heroes: list[Unit], weapons: tuple[Unit, ...],
) -> list[tuple[Unit, Unit]]:
    pairs: list[tuple[Unit, Unit]] = []
    used_h: set[int] = set()
    used_w: set[int] = set()
    options = sorted(
        (
            (distance(hero.pos, tower.pos), hero.unit_id, tower.unit_id)
            for hero in heroes
            for tower in weapons
        )
    )
    hero_map = {hero.unit_id: hero for hero in heroes}
    tower_map = {tower.unit_id: tower for tower in weapons}
    for _, hid, tid in options:
        if hid in used_h or tid in used_w:
            continue
        used_h.add(hid)
        used_w.add(tid)
        pairs.append((hero_map[hid], tower_map[tid]))
    return pairs


def _adjacent_building(turn: World, role: Unit, unit: Unit) -> bool:
    return any(
        role.pos != cell and distance(role.pos, cell) <= 1
        for cell in turn.footprint(unit)
    )


def _wall_max(level: int) -> int:
    return {1: 1000, 2: 1500, 3: 2000}.get(max(level, 1), 1000)


def _sellable_ore(
    role: Unit, turn: World, keep_stone: int,
) -> tuple[str, int] | None:
    best: tuple[int, str, int] | None = None
    for name in ("copper", "iron", "stone"):
        have = count_item(role, name)
        if name == "stone":
            have -= keep_stone
        if have <= 0:
            continue
        actual = backpack_item(role, name)
        if actual is None:
            continue
        price = turn.vendor_price(name)
        score = (price, have)
        if best is None or score > (best[0], best[2]):
            best = (price, actual, have)
    if best is None:
        return None
    return best[1], best[2]


def num_ores(role: Unit) -> int:
    return sum(count_item(role, name) for name in ("stone", "iron", "copper"))
