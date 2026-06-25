from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ColorState(Enum):
    NON = "non"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    GREEN = "green"


class TrendState(Enum):
    NON = "non"
    UP = "up"
    DOWN = "down"


class SignalAction(Enum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"


class Direction(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class MinuteBar:
    trade_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    trading_day: str
    day_index: int


@dataclass(frozen=True)
class PeriodSnapshot:
    period: int
    macd: float | None
    color: ColorState
    trend: TrendState


@dataclass(frozen=True)
class ResonanceInterval:
    direction: Direction
    p_min: int
    p_max: int
    length: int
    trend_count: int
    max_consecutive_trend: int
    trend_ratio: float
    trigger_period: int


@dataclass(frozen=True)
class Signal:
    trade_time: datetime
    action: SignalAction
    price: float
    reason: str
    p_min: int | None
    p_max: int | None
    trigger_period: int | None
    trigger_prev_color: ColorState | None
    trigger_color: ColorState | None


@dataclass(frozen=True)
class BacktestResult:
    signals: list[Signal]
    intervals: list[dict[str, object]]
    summary: dict[str, object]
