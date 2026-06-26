import logging
from dataclasses import dataclass
from datetime import datetime

from .indicators import MacdState, classify_color
from .models import (
    BacktestResult,
    ColorState,
    Direction,
    EventSnapshot,
    MinuteBar,
    PeriodSnapshot,
    ResonanceInterval,
    Signal,
    SignalAction,
)
from .resonance import interval_is_valid, interval_key, scan_best_interval
from .validation import SignalValidator

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    # 入场、触发、离场阈值分开配置，分别对应找共振、映射小周期、判断结构瓦解。
    max_period: int
    entry_min_interval_length: int = 10
    entry_min_interval_ratio: float = 0.8
    entry_min_consecutive_trend: int = 8
    trigger_divisor: int = 10
    exit_min_interval_ratio: float = 0.8
    exit_min_trend_count: int = 0
    exit_min_consecutive_trend: int = 8
    warmup_months: int = 3
    epsilon: float = 1e-10
    progress_every: int = 5000
    validation_enabled: bool = True
    validation_min_expected_minutes: int = 1


class TimeMatrixBacktester:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.macd_states: dict[int, MacdState] = {
            period: MacdState() for period in range(1, config.max_period + 1)
        }
        self.snapshots: dict[int, PeriodSnapshot] = {}
        self.previous_colors: dict[int, ColorState] = {
            period: ColorState.NON for period in range(1, config.max_period + 1)
        }
        self.latest_colors: dict[int, ColorState] = {
            period: ColorState.NON for period in range(1, config.max_period + 1)
        }
        self.previous_latest_colors: dict[int, ColorState] = {
            period: ColorState.NON for period in range(1, config.max_period + 1)
        }
        self.signals: list[Signal] = []
        self.intervals: list[dict[str, object]] = []
        self.event_snapshots: list[EventSnapshot] = []
        self.current_position: ResonanceInterval | None = None
        self.current_open_signal: Signal | None = None
        self.position_high: float | None = None
        self.position_low: float | None = None
        self.last_interval_key: tuple | None = None
        self.last_interval: ResonanceInterval | None = None
        self.warmup_end_time: datetime | None = None
        self.validator = SignalValidator(
            enabled=config.validation_enabled,
            min_expected_minutes=config.validation_min_expected_minutes,
            exit_min_interval_ratio=config.exit_min_interval_ratio,
            exit_min_trend_count=config.exit_min_trend_count,
            exit_min_consecutive_trend=config.exit_min_consecutive_trend,
        )

    def run(self, bars: list[MinuteBar]) -> BacktestResult:
        if not bars:
            raise ValueError("没有可回测的分钟数据")

        self.warmup_end_time = add_months(bars[0].trade_time, self.config.warmup_months)
        LOGGER.info(
            "回测开始：分钟线=%s，最大周期=%s，入场区间最小长度=%s，入场比例=%.4f，入场最小连续趋势数=%s，触发周期除数=%s，离场比例=%.4f，离场最小趋势数=%s，离场最小连续趋势数=%s，预热月数=%s，正式判断开始时间=%s",
            len(bars),
            self.config.max_period,
            self.config.entry_min_interval_length,
            self.config.entry_min_interval_ratio,
            self.config.entry_min_consecutive_trend,
            self.config.trigger_divisor,
            self.config.exit_min_interval_ratio,
            self.config.exit_min_trend_count,
            self.config.exit_min_consecutive_trend,
            self.config.warmup_months,
            self.warmup_end_time,
        )

        for index, bar in enumerate(bars, start=1):
            self._process_bar(bar, index)
            if self.config.progress_every and index % self.config.progress_every == 0:
                LOGGER.info(
                    "回放进度：%s/%s，当前时间=%s，信号数=%s，区间变化数=%s",
                    index,
                    len(bars),
                    bar.trade_time,
                    len(self.signals),
                    len(self.intervals),
                )

        self.validator.finish_uncompleted(bars[-1], self.snapshots)
        summary = self._build_summary(len(bars))
        LOGGER.info(
            "回测结束：分钟线=%s，信号=%s，区间变化=%s，完整交易=%s，胜率=%.2f%%，总盈亏=%.4f，平均每笔=%.4f，未平仓=%s",
            summary["minute_bars"],
            summary["signal_count"],
            summary["interval_change_count"],
            summary["closed_trade_count"],
            summary["win_rate"],
            summary["total_pnl"],
            summary["average_pnl"],
            summary["open_position"],
        )
        return BacktestResult(
            signals=self.signals,
            intervals=self.intervals,
            signal_validations=self.validator.completed,
            event_snapshots=self.event_snapshots,
            summary=summary,
        )

    def _process_bar(self, bar: MinuteBar, index: int) -> None:
        LOGGER.debug(
            "读取第 %s 根 1分钟线：时间=%s，收盘价=%.4f，当日有效分钟序号=%s",
            index,
            bar.trade_time,
            bar.close_price,
            bar.day_index,
        )
        completed_periods = self._update_completed_periods(bar)
        self._update_position_range(bar)
        if self._is_warmup_bar(bar):
            LOGGER.debug(
                "预热阶段：只更新周期数据，不判断区间和交易。时间=%s，已更新周期数=%s",
                bar.trade_time,
                len(completed_periods),
            )
            return

        best_long = scan_best_interval(
            snapshots=self.snapshots,
            direction=Direction.LONG,
            min_length=self.config.entry_min_interval_length,
            min_consecutive_trend=self.config.entry_min_consecutive_trend,
            min_ratio=self.config.entry_min_interval_ratio,
            trigger_divisor=self.config.trigger_divisor,
        )
        self.validator.update(bar, self.snapshots)
        interval_changed = self._record_interval_change(bar, best_long)
        if interval_changed and best_long is not None:
            self.validator.create(bar, best_long, self.snapshots)

        # 当前分钟如果先触发平仓，就不在同一分钟重新开仓，保证信号顺序确定。
        if self._process_close_signal(bar, completed_periods):
            return
        opened = self._process_open_signal(bar, completed_periods, best_long)
        if not opened and self.current_position is not None:
            self._record_event_snapshot(
                bar=bar,
                event_type="position_tick",
                reason="holding_minute_snapshot",
                old_interval=None,
                new_interval=self.current_position,
                trigger_period=self.current_position.trigger_period,
                interval_change_type="none",
            )

    def _is_warmup_bar(self, bar: MinuteBar) -> bool:
        return self.warmup_end_time is not None and bar.trade_time < self.warmup_end_time

    def _update_completed_periods(self, bar: MinuteBar) -> set[int]:
        completed_periods: set[int] = set()
        for period in range(1, self.config.max_period + 1):
            # 只在该周期 K 线完成时更新。未完成周期不参与 MACD、趋势和共振判断。
            if bar.day_index % period != 0:
                continue
            hist = self.macd_states[period].update(bar.close_price, self.config.epsilon)
            color = classify_color(hist, self.previous_colors[period], self.config.epsilon)
            trend = self.macd_states[period].trend
            self.previous_latest_colors[period] = self.latest_colors[period]
            self.latest_colors[period] = color
            self.previous_colors[period] = color
            self.snapshots[period] = PeriodSnapshot(
                period=period,
                macd=hist[-1] if hist else None,
                color=color,
                trend=trend,
            )
            completed_periods.add(period)
            LOGGER.debug(
                "周期更新：时间=%s，周期=%s，MACD=%s，颜色=%s，趋势=%s",
                bar.trade_time,
                period,
                f"{hist[-1]:.8f}" if hist else "无",
                color.value,
                trend.value,
            )
        return completed_periods

    def _record_interval_change(
        self,
        bar: MinuteBar,
        best_long: ResonanceInterval | None,
    ) -> bool:
        current_interval_key = interval_key(best_long)
        if current_interval_key == self.last_interval_key:
            return False

        previous_interval = self.last_interval
        if best_long is not None:
            self.intervals.append(
                {
                    "time": bar.trade_time.isoformat(sep=" "),
                    "direction": best_long.direction.value,
                    "p_min": best_long.p_min,
                    "p_max": best_long.p_max,
                    "length": best_long.length,
                    "trend_count": best_long.trend_count,
                    "max_consecutive_trend": best_long.max_consecutive_trend,
                    "trend_ratio": f"{best_long.trend_ratio:.6f}",
                    "trigger_period": best_long.trigger_period,
                }
            )
            LOGGER.info(
                "共振区间变化：时间=%s，区间=%s-%s，长度=%s，趋势周期数=%s，最大连续趋势数=%s，占比=%.4f，触发周期=%s",
                bar.trade_time,
                best_long.p_min,
                best_long.p_max,
                best_long.length,
                best_long.trend_count,
                best_long.max_consecutive_trend,
                best_long.trend_ratio,
                best_long.trigger_period,
            )
        else:
            LOGGER.info("共振区间消失：时间=%s", bar.trade_time)
        self._record_event_snapshot(
            bar=bar,
            event_type="interval_change",
            reason="resonance_interval_changed",
            old_interval=previous_interval,
            new_interval=best_long,
            trigger_period=(
                best_long.trigger_period
                if best_long
                else previous_interval.trigger_period
                if previous_interval
                else None
            ),
        )
        self.last_interval = best_long
        self.last_interval_key = current_interval_key
        return True

    def _process_close_signal(self, bar: MinuteBar, completed_periods: set[int]) -> bool:
        if self.current_position is None:
            return False

        trigger = self.current_position.trigger_period
        prev_color = self.previous_latest_colors.get(trigger, ColorState.NON)
        color = self.latest_colors.get(trigger, ColorState.NON)
        close_by_trigger = (
            trigger in completed_periods
            and (
                (prev_color == ColorState.RED and color == ColorState.YELLOW)
                or (prev_color == ColorState.GREEN and color == ColorState.BLUE)
            )
        )
        close_by_interval = not interval_is_valid(
            self.snapshots,
            self.current_position,
            self.config.exit_min_interval_ratio,
            self.config.exit_min_trend_count,
            self.config.exit_min_consecutive_trend,
        )
        if not close_by_trigger and not close_by_interval:
            return False

        reason = "trigger_color_reversal" if close_by_trigger else "resonance_interval_broken"
        signal = Signal(
            trade_time=bar.trade_time,
            action=SignalAction.CLOSE_LONG,
            price=bar.close_price,
            reason=reason,
            p_min=self.current_position.p_min,
            p_max=self.current_position.p_max,
            trigger_period=trigger,
            trigger_prev_color=prev_color,
            trigger_color=color,
        )
        self._append_signal(signal)
        self._record_event_snapshot(
            bar=bar,
            event_type=signal.action.value,
            reason=signal.reason,
            old_interval=self.current_position,
            new_interval=None,
            trigger_period=trigger,
            trigger_prev_color=prev_color,
            trigger_color=color,
        )
        self.current_position = None
        self.current_open_signal = None
        self.position_high = None
        self.position_low = None
        return True

    def _process_open_signal(
        self,
        bar: MinuteBar,
        completed_periods: set[int],
        best_long: ResonanceInterval | None,
    ) -> bool:
        if self.current_position is not None or best_long is None:
            return False

        trigger = best_long.trigger_period
        prev_color = self.previous_latest_colors.get(trigger, ColorState.NON)
        color = self.latest_colors.get(trigger, ColorState.NON)
        if trigger not in completed_periods or prev_color != ColorState.BLUE or color != ColorState.GREEN:
            return False

        signal = Signal(
            trade_time=bar.trade_time,
            action=SignalAction.OPEN_LONG,
            price=bar.close_price,
            reason="trigger_blue_to_green",
            p_min=best_long.p_min,
            p_max=best_long.p_max,
            trigger_period=trigger,
            trigger_prev_color=prev_color,
            trigger_color=color,
        )
        self._append_signal(signal)
        self.current_position = best_long
        self.current_open_signal = signal
        self.position_high = bar.high_price
        self.position_low = bar.low_price
        self._record_event_snapshot(
            bar=bar,
            event_type=signal.action.value,
            reason=signal.reason,
            old_interval=None,
            new_interval=best_long,
            trigger_period=trigger,
            trigger_prev_color=prev_color,
            trigger_color=color,
        )
        return True

    def _append_signal(self, signal: Signal) -> None:
        self.signals.append(signal)
        action_text = "开多" if signal.action == SignalAction.OPEN_LONG else "平多"
        LOGGER.info(
            "%s信号：时间=%s，价格=%.4f，原因=%s，区间=%s-%s，触发周期=%s，颜色=%s->%s",
            action_text,
            signal.trade_time,
            signal.price,
            signal.reason,
            signal.p_min,
            signal.p_max,
            signal.trigger_period,
            signal.trigger_prev_color.value if signal.trigger_prev_color else "",
            signal.trigger_color.value if signal.trigger_color else "",
        )

    def _update_position_range(self, bar: MinuteBar) -> None:
        if self.current_position is None:
            return
        self.position_high = (
            bar.high_price if self.position_high is None else max(self.position_high, bar.high_price)
        )
        self.position_low = (
            bar.low_price if self.position_low is None else min(self.position_low, bar.low_price)
        )

    def _record_event_snapshot(
        self,
        bar: MinuteBar,
        event_type: str,
        reason: str,
        old_interval: ResonanceInterval | None,
        new_interval: ResonanceInterval | None,
        trigger_period: int | None,
        trigger_prev_color: ColorState | None = None,
        trigger_color: ColorState | None = None,
        interval_change_type: str | None = None,
    ) -> None:
        trigger_snapshot = self.snapshots.get(trigger_period) if trigger_period is not None else None
        calculation_interval = new_interval or old_interval
        p_min_snapshot = self.snapshots.get(calculation_interval.p_min) if calculation_interval else None
        p_max_snapshot = self.snapshots.get(calculation_interval.p_max) if calculation_interval else None
        open_signal = self.current_open_signal
        position_pnl = bar.close_price - open_signal.price if open_signal else None
        snapshot = EventSnapshot(
            event_time=bar.trade_time,
            event_type=event_type,
            reason=reason,
            price=bar.close_price,
            minute_open=bar.open_price,
            minute_high=bar.high_price,
            minute_low=bar.low_price,
            minute_close=bar.close_price,
            minute_volume=bar.volume,
            trading_day=bar.trading_day,
            day_index=bar.day_index,
            position_state="long" if self.current_position is not None else "flat",
            position_open_time=open_signal.trade_time if open_signal else None,
            position_open_price=open_signal.price if open_signal else None,
            position_pnl=position_pnl,
            position_high=self.position_high,
            position_low=self.position_low,
            old_p_min=old_interval.p_min if old_interval else None,
            old_p_max=old_interval.p_max if old_interval else None,
            old_length=old_interval.length if old_interval else None,
            old_trend_count=old_interval.trend_count if old_interval else None,
            old_trend_ratio=old_interval.trend_ratio if old_interval else None,
            new_p_min=new_interval.p_min if new_interval else None,
            new_p_max=new_interval.p_max if new_interval else None,
            new_length=new_interval.length if new_interval else None,
            new_trend_count=new_interval.trend_count if new_interval else None,
            new_max_consecutive_trend=new_interval.max_consecutive_trend if new_interval else None,
            new_trend_ratio=new_interval.trend_ratio if new_interval else None,
            trigger_period=trigger_period,
            trigger_macd=trigger_snapshot.macd if trigger_snapshot else None,
            trigger_prev_color=trigger_prev_color,
            trigger_color=trigger_color if trigger_color is not None else (trigger_snapshot.color if trigger_snapshot else None),
            trigger_trend=trigger_snapshot.trend if trigger_snapshot else None,
            p_min_macd=p_min_snapshot.macd if p_min_snapshot else None,
            p_min_color=p_min_snapshot.color if p_min_snapshot else None,
            p_min_trend=p_min_snapshot.trend if p_min_snapshot else None,
            p_max_macd=p_max_snapshot.macd if p_max_snapshot else None,
            p_max_color=p_max_snapshot.color if p_max_snapshot else None,
            p_max_trend=p_max_snapshot.trend if p_max_snapshot else None,
            interval_change_type=interval_change_type
            if interval_change_type is not None
            else self._classify_interval_change(old_interval, new_interval),
        )
        self.event_snapshots.append(snapshot)
        LOGGER.info(
            "事件快照：时间=%s，类型=%s，原因=%s，持仓=%s，旧区间=%s-%s，新区间=%s-%s，触发周期=%s",
            snapshot.event_time,
            snapshot.event_type,
            snapshot.reason,
            snapshot.position_state,
            snapshot.old_p_min or "",
            snapshot.old_p_max or "",
            snapshot.new_p_min or "",
            snapshot.new_p_max or "",
            snapshot.trigger_period or "",
        )

    def _classify_interval_change(
        self,
        old_interval: ResonanceInterval | None,
        new_interval: ResonanceInterval | None,
    ) -> str:
        if old_interval is None and new_interval is None:
            return "none"
        if old_interval is None:
            return "created"
        if new_interval is None:
            return "removed"
        if old_interval.p_min == new_interval.p_min and old_interval.p_max == new_interval.p_max:
            return "metrics_changed"
        return "range_changed"

    def _build_summary(self, minute_bars: int) -> dict[str, object]:
        open_signal: Signal | None = None
        closed_trade_count = 0
        win_count = 0
        loss_count = 0
        total_pnl = 0.0

        for signal in self.signals:
            if signal.action == SignalAction.OPEN_LONG:
                open_signal = signal
                continue
            if signal.action != SignalAction.CLOSE_LONG or open_signal is None:
                continue

            pnl = signal.price - open_signal.price
            total_pnl += pnl
            closed_trade_count += 1
            if pnl > 0:
                win_count += 1
            elif pnl < 0:
                loss_count += 1
            open_signal = None

        win_rate = (win_count / closed_trade_count * 100.0) if closed_trade_count else 0.0
        average_pnl = (total_pnl / closed_trade_count) if closed_trade_count else 0.0
        return {
            "minute_bars": minute_bars,
            "signal_count": len(self.signals),
            "interval_change_count": len(self.intervals),
            "event_snapshot_count": len(self.event_snapshots),
            "signal_validation_count": len(self.validator.completed),
            "signal_validation_success_count": sum(
                1 for item in self.validator.completed if item.is_expected_direction
            ),
            "signal_validation_success_rate": (
                sum(1 for item in self.validator.completed if item.is_expected_direction)
                / len(self.validator.completed)
                * 100.0
                if self.validator.completed
                else 0.0
            ),
            "closed_trade_count": closed_trade_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "average_pnl": average_pnl,
            "open_position": open_signal is not None,
            "warmup_end_time": self.warmup_end_time.isoformat(sep=" ") if self.warmup_end_time else "",
        }


def add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, days_in_month(year, month))
    return value.replace(year=year, month=month, day=day)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
            return 29
        return 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31
