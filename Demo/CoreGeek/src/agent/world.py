from dataclasses import dataclass, field
from typing import Any

from .protocol import (
    LAND,
    PIONEER,
    Pos,
    Robot,
    Turn,
    Unit,
    distance,
)

ORE_TYPES = ("stone", "iron", "copper")
HERO_MAX_HP = {
    "worker": 220,
    "pioneer": 200,
}
CHALLENGER_TASK_ZONES = ("challengerTaskPoint1", "challengerTaskPoint2")
DEFENDER_TASK_ZONES = ("defenderTaskPoint1", "defenderTaskPoint2")
ERROR_TEXT = {
    0: "未知错误",
    1: "任务超时",
    2: "答案错误或不完全正确",
    3: "网络错误",
    4: "指令错误（字段缺失或动作码无法识别）",
    5: "LLM额度超限",
}
SUMMON_TEXT = {
    0: "未探测（上回合未使用 summonTreasure 或动作非法）",
    1: "成功获取宝藏",
    2: "无宝藏或宝藏暂未开启（位置不对或时间未到）",
    3: "献祭物品错误（不能多、不能少、无顺序限制）",
    4: "宝藏已空",
}


@dataclass(frozen=True, slots=True)
class ShopItem:
    name: str
    price: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ShopItem":
        return cls(str(raw.get("name") or ""), int(raw.get("price") or 0))


@dataclass(frozen=True, slots=True)
class PlayerTask:
    task_type: str
    pos: Pos
    cooldown: int
    score_reward: int
    gold_reward: int
    valid: bool
    timeout_rounds: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "PlayerTask":
        return cls(
            str(raw.get("taskType") or ""),
            Pos.load(raw["taskPosition"]),
            int(raw.get("coldDownRounds") or 0),
            int(raw.get("scoreReward") or 0),
            int(raw.get("goldReward") or 0),
            bool(raw.get("isValid")),
            int(raw.get("timeoutRounds") or 0),
        )


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: int
    description: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ErrorInfo":
        return cls(int(raw.get("errorCode") or 0), str(raw.get("description") or ""))

    def reason(self) -> str:
        base = ERROR_TEXT.get(self.code, "未知错误码")
        if self.description:
            return f"{base} | {self.description}"
        return base


@dataclass(frozen=True, slots=True)
class BattleRobot:
    robot_id: int
    pos: Pos
    health: int
    kind: str
    state: str
    target_team: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "BattleRobot":
        return cls(
            int(raw["id"]),
            Pos.load(raw["pos"]),
            int(raw["health"]),
            str(raw.get("roleType") or ""),
            str(raw.get("abnormalState") or ""),
            str(raw.get("targetTeam") or ""),
        )

    @property
    def dizzy(self) -> bool:
        return self.state == "dizzy"


@dataclass
class World:
    turn: Turn
    payload: dict[str, Any]
    team_type: str = ""
    score: int = 0
    phase_task: str = ""
    last_cmd_result: str = ""
    last_summon: int = 0
    llm_resp: str = ""
    official_news: str = ""
    folk_legends: str = ""
    vendor_shop: tuple[ShopItem, ...] = ()
    weapon_shop: tuple[ShopItem, ...] = ()
    player_tasks: tuple[PlayerTask, ...] = ()
    enemy: tuple[Unit, ...] = ()
    last_results: dict[int, bool] = field(default_factory=dict)
    errors: tuple[ErrorInfo, ...] = ()
    battle_robots: tuple[BattleRobot, ...] = ()
    attack_power: dict[int, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "World":
        turn = Turn.load(payload)
        team = payload.get("teamOur") or {}
        news = payload.get("worldNews") or {}
        last_results_raw = payload.get("lastRoundRoleActionResults") or {}
        robots_raw = (payload.get("robot") or {}).get("roles") or ()
        attack_power = {
            int(role.get("id") or 0): int(role.get("attackPower") or 0)
            for role in team.get("roles") or ()
        }
        world = cls(
            turn,
            payload,
            str(team.get("type") or ""),
            int(team.get("totalScore") or 0),
            str(payload.get("phaseTask") or ""),
            str(payload.get("lastCmdResult") or ""),
            int(payload.get("lastSummonTreasureResult") or 0),
            str(payload.get("llmResp") or ""),
            str(news.get("officialNews") or ""),
            str(news.get("folkLegends") or ""),
            tuple(ShopItem.load(item) for item in payload.get("vendorShopList") or ()),
            tuple(ShopItem.load(item) for item in payload.get("weaponShopList") or ()),
            tuple(PlayerTask.load(item) for item in team.get("playerTasks") or ()),
            tuple(
                Unit.load(role)
                for role in (payload.get("teamEnemy") or {}).get("roles") or ()
            ),
            {int(key): bool(value) for key, value in last_results_raw.items()},
            tuple(ErrorInfo.load(item) for item in payload.get("errors") or ()),
            tuple(BattleRobot.load(robot) for robot in robots_raw),
            attack_power,
        )
        return world

    def __getattr__(self, name: str) -> Any:
        return getattr(self.turn, name)

    @property
    def robots(self) -> tuple[BattleRobot, ...]:
        return self.battle_robots

    @property
    def day_index(self) -> int:
        from .protocol import ROUNDS_PER_DAY
        return (self.round_no - 1) // ROUNDS_PER_DAY + 1

    @property
    def round_in_day(self) -> int:
        from .protocol import ROUNDS_PER_DAY
        return (self.round_no - 1) % ROUNDS_PER_DAY + 1

    def pioneer(self) -> Unit | None:
        roles = self.alive((PIONEER,))
        return roles[0] if roles else None

    def all_mines(self) -> tuple[tuple[Pos, str], ...]:
        return tuple(
            (pos, kind) for pos, kind in self.zones.items() if kind in ORE_TYPES
        )

    def vendor(self) -> Pos | None:
        return self._zone("vendor")

    def weapon_shop_pos(self) -> Pos | None:
        return self._zone("weaponShop")

    def own_task_zones(self) -> tuple[Pos, ...]:
        names = (
            CHALLENGER_TASK_ZONES
            if self.team_type == "challenger"
            else DEFENDER_TASK_ZONES
        )
        return tuple(pos for pos, kind in self.zones.items() if kind in names)

    def vendor_price(self, name: str) -> int:
        wanted = name.lower()
        for item in self.vendor_shop:
            if item.name.lower() == wanted:
                return item.price
        return 0

    def shop_item(self, name: str) -> ShopItem | None:
        wanted = name.lower()
        for item in self.weapon_shop:
            if item.name.lower() == wanted:
                return item
        return None

    def occupied_for_build(self) -> frozenset[Pos]:
        cells = set(self.occupied_cells())
        for unit in self.enemy:
            cells.update(self.footprint(unit))
        for robot in self.battle_robots:
            if robot.health > 0:
                cells.add(robot.pos)
        cells.update(pos for pos, kind in self.zones.items() if kind != LAND)
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        cells = set(self.turn.blocked(moving))
        for unit in self.enemy:
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def adjacent_to_zone(self, role: Unit, target: Pos) -> bool:
        return role.pos != target and distance(role.pos, target) <= 1

    def adjacent_to_any(self, role: Unit, cells: tuple[Pos, ...]) -> bool:
        return any(self.adjacent_to_zone(role, pos) for pos in cells)

    def last_ok(self, unit_id: int) -> bool | None:
        return self.last_results.get(unit_id)

    def llm_limited(self) -> bool:
        return any(error.code == 5 for error in self.errors)

    def unit_attack_power(self, unit: Unit) -> int:
        return self.attack_power.get(unit.unit_id, unit.level * 10 if unit.kind != "rocket" else unit.level * 20)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def _zone(self, name: str) -> Pos | None:
        for pos, kind in self.zones.items():
            if kind == name:
                return pos
        return None


def backpack_item(role: Unit, name: str) -> str | None:
    wanted = name.lower()
    for item in role.backpack:
        if item.lower() == wanted:
            return item
    return None


def count_item(role: Unit, name: str) -> int:
    wanted = name.lower()
    return sum(1 for item in role.backpack if item.lower() == wanted)


def backpack_free(role: Unit) -> int:
    if role.capacity is None:
        return 0
    return max(0, role.capacity - len(role.backpack))


def tower_shots(unit: Unit) -> int:
    return max(1, unit.level or 1)
