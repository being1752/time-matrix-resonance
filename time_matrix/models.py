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
class SignalValidation:
    validation_id: int
    signal_time: datetime
    direction: Direction
    p_min: int
    p_max: int
    length: int
    trigger_period: int
    elapsed_in_min_period: int
    expected_minutes: int
    observed_minutes: int
    start_price: float
    end_time: datetime | None
    end_price: float | None
    return_pct: float | None
    max_high: float
    max_gain_time: datetime | None
    max_gain_observed_minute: int | None
    max_gain_pct: float
    min_low: float
    max_drawdown_time: datetime | None
    max_drawdown_observed_minute: int | None
    max_drawdown_pct: float
    is_expected_direction: bool | None
    start_trend_count: int
    end_trend_count: int | None
    min_trend_count: int
    max_trend_count: int
    start_trend_ratio: float
    end_trend_ratio: float | None
    trend_count_change: int | None
    trend_strength_change: str
    interval_valid_at_end: bool | None
    completed: bool
    completion_reason: str


@dataclass(frozen=True)
class EventSnapshot:
    event_time: datetime
    event_type: str
    reason: str
    price: float
    minute_open: float
    minute_high: float
    minute_low: float
    minute_close: float
    minute_volume: int
    trading_day: str
    day_index: int
    position_state: str
    position_open_time: datetime | None
    position_open_price: float | None
    position_pnl: float | None
    position_high: float | None
    position_low: float | None
    old_p_min: int | None
    old_p_max: int | None
    old_length: int | None
    old_trend_count: int | None
    old_trend_ratio: float | None
    new_p_min: int | None
    new_p_max: int | None
    new_length: int | None
    new_trend_count: int | None
    new_max_consecutive_trend: int | None
    new_trend_ratio: float | None
    trigger_period: int | None
    trigger_macd: float | None
    trigger_prev_color: ColorState | None
    trigger_color: ColorState | None
    trigger_trend: TrendState | None
    p_min_macd: float | None
    p_min_color: ColorState | None
    p_min_trend: TrendState | None
    p_max_macd: float | None
    p_max_color: ColorState | None
    p_max_trend: TrendState | None
    interval_change_type: str


@dataclass(frozen=True)
class BacktestResult:
    signals: list[Signal]
    intervals: list[dict[str, object]]
    signal_validations: list[SignalValidation]
    event_snapshots: list[EventSnapshot]
    summary: dict[str, object]
