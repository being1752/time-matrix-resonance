import logging
from dataclasses import dataclass
from datetime import datetime

from .models import Direction, MinuteBar, PeriodSnapshot, ResonanceInterval, SignalValidation
from .resonance import evaluate_interval, interval_is_valid

LOGGER = logging.getLogger(__name__)


@dataclass
class ActiveSignalValidation:
    validation_id: int
    signal_time: datetime
    direction: Direction
    p_min: int
    p_max: int
    length: int
    trigger_period: int
    elapsed_in_min_period: int
    expected_minutes: int
    start_price: float
    start_trend_count: int
    start_trend_ratio: float
    observed_minutes: int = 0
    max_high: float = 0.0
    max_gain_time: datetime | None = None
    max_gain_observed_minute: int | None = None
    min_low: float = 0.0
    max_drawdown_time: datetime | None = None
    max_drawdown_observed_minute: int | None = None
    min_trend_count: int = 0
    max_trend_count: int = 0


class SignalValidator:
    def __init__(
        self,
        enabled: bool,
        min_expected_minutes: int,
        exit_min_interval_ratio: float,
        exit_min_trend_count: int,
        exit_min_consecutive_trend: int,
    ):
        self.enabled = enabled
        self.min_expected_minutes = max(1, min_expected_minutes)
        self.exit_min_interval_ratio = exit_min_interval_ratio
        self.exit_min_trend_count = exit_min_trend_count
        self.exit_min_consecutive_trend = exit_min_consecutive_trend
        self.next_id = 1
        self.active: list[ActiveSignalValidation] = []
        self.completed: list[SignalValidation] = []

    def create(
        self,
        bar: MinuteBar,
        interval: ResonanceInterval,
        snapshots: dict[int, PeriodSnapshot],
    ) -> None:
        if not self.enabled:
            return

        elapsed_in_min_period = bar.day_index % interval.p_min
        expected_minutes = interval.p_max - interval.p_min - elapsed_in_min_period
        if expected_minutes < self.min_expected_minutes:
            LOGGER.info(
                "跳过算法验证：时间=%s，区间=%s-%s，预期观察分钟=%s，小于最小值=%s",
                bar.trade_time,
                interval.p_min,
                interval.p_max,
                expected_minutes,
                self.min_expected_minutes,
            )
            return

        stats = evaluate_interval(snapshots, interval.direction, interval.p_min, interval.p_max)
        task = ActiveSignalValidation(
            validation_id=self.next_id,
            signal_time=bar.trade_time,
            direction=interval.direction,
            p_min=interval.p_min,
            p_max=interval.p_max,
            length=interval.length,
            trigger_period=interval.trigger_period,
            elapsed_in_min_period=elapsed_in_min_period,
            expected_minutes=expected_minutes,
            start_price=bar.close_price,
            start_trend_count=stats.trend_count,
            start_trend_ratio=stats.trend_ratio,
            max_high=bar.high_price,
            max_gain_time=bar.trade_time,
            max_gain_observed_minute=0,
            min_low=bar.low_price,
            max_drawdown_time=bar.trade_time,
            max_drawdown_observed_minute=0,
            min_trend_count=stats.trend_count,
            max_trend_count=stats.trend_count,
        )
        self.next_id += 1
        self.active.append(task)
        LOGGER.info(
            "创建算法验证：编号=%s，时间=%s，区间=%s-%s，已运行Min周期分钟=%s，预期观察=%s根有效1分钟线，起始价=%.4f，起始趋势数=%s，占比=%.4f",
            task.validation_id,
            task.signal_time,
            task.p_min,
            task.p_max,
            task.elapsed_in_min_period,
            task.expected_minutes,
            task.start_price,
            task.start_trend_count,
            task.start_trend_ratio,
        )

    def update(
        self,
        bar: MinuteBar,
        snapshots: dict[int, PeriodSnapshot],
    ) -> None:
        if not self.enabled or not self.active:
            return

        still_active: list[ActiveSignalValidation] = []
        for task in self.active:
            task.observed_minutes += 1
            if bar.high_price > task.max_high:
                task.max_high = bar.high_price
                task.max_gain_time = bar.trade_time
                task.max_gain_observed_minute = task.observed_minutes
            if bar.low_price < task.min_low:
                task.min_low = bar.low_price
                task.max_drawdown_time = bar.trade_time
                task.max_drawdown_observed_minute = task.observed_minutes

            interval = ResonanceInterval(
                direction=task.direction,
                p_min=task.p_min,
                p_max=task.p_max,
                length=task.length,
                trend_count=task.start_trend_count,
                max_consecutive_trend=0,
                trend_ratio=task.start_trend_ratio,
                trigger_period=task.trigger_period,
            )
            stats = evaluate_interval(snapshots, task.direction, task.p_min, task.p_max)
            task.min_trend_count = min(task.min_trend_count, stats.trend_count)
            task.max_trend_count = max(task.max_trend_count, stats.trend_count)

            if task.observed_minutes >= task.expected_minutes:
                self.completed.append(
                    self._finish(
                        task=task,
                        bar=bar,
                        end_trend_count=stats.trend_count,
                        end_trend_ratio=stats.trend_ratio,
                        interval_valid_at_end=interval_is_valid(
                            snapshots=snapshots,
                            interval=interval,
                            min_ratio=self.exit_min_interval_ratio,
                            min_trend_count=self.exit_min_trend_count,
                            min_consecutive_trend=self.exit_min_consecutive_trend,
                        ),
                        reason="completed_window",
                    )
                )
            else:
                still_active.append(task)

        self.active = still_active

    def finish_uncompleted(self, last_bar: MinuteBar, snapshots: dict[int, PeriodSnapshot]) -> None:
        if not self.enabled:
            return
        for task in self.active:
            stats = evaluate_interval(snapshots, task.direction, task.p_min, task.p_max)
            interval = ResonanceInterval(
                direction=task.direction,
                p_min=task.p_min,
                p_max=task.p_max,
                length=task.length,
                trend_count=task.start_trend_count,
                max_consecutive_trend=0,
                trend_ratio=task.start_trend_ratio,
                trigger_period=task.trigger_period,
            )
            self.completed.append(
                self._finish(
                    task=task,
                    bar=last_bar,
                    end_trend_count=stats.trend_count,
                    end_trend_ratio=stats.trend_ratio,
                    interval_valid_at_end=interval_is_valid(
                        snapshots=snapshots,
                        interval=interval,
                        min_ratio=self.exit_min_interval_ratio,
                        min_trend_count=self.exit_min_trend_count,
                        min_consecutive_trend=self.exit_min_consecutive_trend,
                    ),
                    reason="end_of_data",
                )
            )
        self.active = []

    def _finish(
        self,
        task: ActiveSignalValidation,
        bar: MinuteBar,
        end_trend_count: int,
        end_trend_ratio: float,
        interval_valid_at_end: bool,
        reason: str,
    ) -> SignalValidation:
        price_diff = bar.close_price - task.start_price
        return_pct = price_diff / task.start_price * 100.0 if task.start_price else 0.0
        max_gain_pct = (task.max_high - task.start_price) / task.start_price * 100.0 if task.start_price else 0.0
        max_drawdown_pct = (task.min_low - task.start_price) / task.start_price * 100.0 if task.start_price else 0.0
        is_expected_direction = price_diff > 0 if task.direction == Direction.LONG else price_diff < 0
        trend_count_change = end_trend_count - task.start_trend_count
        if trend_count_change > 0:
            trend_strength_change = "stronger"
        elif trend_count_change < 0:
            trend_strength_change = "weaker"
        else:
            trend_strength_change = "unchanged"

        LOGGER.info(
            "完成算法验证：编号=%s，信号时间=%s，结束时间=%s，观察=%s/%s，收益率=%.4f%%，最大浮盈=%.4f%%，最大回撤=%.4f%%，趋势变化=%s，区间结束有效=%s",
            task.validation_id,
            task.signal_time,
            bar.trade_time,
            task.observed_minutes,
            task.expected_minutes,
            return_pct,
            max_gain_pct,
            max_drawdown_pct,
            trend_strength_change,
            interval_valid_at_end,
        )
        return SignalValidation(
            validation_id=task.validation_id,
            signal_time=task.signal_time,
            direction=task.direction,
            p_min=task.p_min,
            p_max=task.p_max,
            length=task.length,
            trigger_period=task.trigger_period,
            elapsed_in_min_period=task.elapsed_in_min_period,
            expected_minutes=task.expected_minutes,
            observed_minutes=task.observed_minutes,
            start_price=task.start_price,
            end_time=bar.trade_time,
            end_price=bar.close_price,
            return_pct=return_pct,
            max_high=task.max_high,
            max_gain_time=task.max_gain_time,
            max_gain_observed_minute=task.max_gain_observed_minute,
            max_gain_pct=max_gain_pct,
            min_low=task.min_low,
            max_drawdown_time=task.max_drawdown_time,
            max_drawdown_observed_minute=task.max_drawdown_observed_minute,
            max_drawdown_pct=max_drawdown_pct,
            is_expected_direction=is_expected_direction,
            start_trend_count=task.start_trend_count,
            end_trend_count=end_trend_count,
            min_trend_count=task.min_trend_count,
            max_trend_count=task.max_trend_count,
            start_trend_ratio=task.start_trend_ratio,
            end_trend_ratio=end_trend_ratio,
            trend_count_change=trend_count_change,
            trend_strength_change=trend_strength_change,
            interval_valid_at_end=interval_valid_at_end,
            completed=reason == "completed_window",
            completion_reason=reason,
        )
