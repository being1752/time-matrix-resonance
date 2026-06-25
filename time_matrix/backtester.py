import logging
from dataclasses import dataclass
from datetime import datetime

from .indicators import MacdState, classify_color
from .models import (
    BacktestResult,
    ColorState,
    Direction,
    MinuteBar,
    PeriodSnapshot,
    ResonanceInterval,
    Signal,
    SignalAction,
)
from .resonance import interval_is_valid, interval_key, scan_best_interval

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
        self.current_position: ResonanceInterval | None = None
        self.last_interval_key: tuple | None = None
        self.warmup_end_time: datetime | None = None

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
        return BacktestResult(signals=self.signals, intervals=self.intervals, summary=summary)

    def _process_bar(self, bar: MinuteBar, index: int) -> None:
        LOGGER.debug(
            "读取第 %s 根 1分钟线：时间=%s，收盘价=%.4f，当日有效分钟序号=%s",
            index,
            bar.trade_time,
            bar.close_price,
            bar.day_index,
        )
        completed_periods = self._update_completed_periods(bar)
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
        self._record_interval_change(bar, best_long)

        # 当前分钟如果先触发平仓，就不在同一分钟重新开仓，保证信号顺序确定。
        if self._process_close_signal(bar, completed_periods):
            return
        self._process_open_signal(bar, completed_periods, best_long)

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
    ) -> None:
        current_interval_key = interval_key(best_long)
        if current_interval_key == self.last_interval_key:
            return

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
        self.last_interval_key = current_interval_key

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
        self._append_signal(
            Signal(
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
        )
        self.current_position = None
        return True

    def _process_open_signal(
        self,
        bar: MinuteBar,
        completed_periods: set[int],
        best_long: ResonanceInterval | None,
    ) -> None:
        if self.current_position is not None or best_long is None:
            return

        trigger = best_long.trigger_period
        prev_color = self.previous_latest_colors.get(trigger, ColorState.NON)
        color = self.latest_colors.get(trigger, ColorState.NON)
        if trigger not in completed_periods or prev_color != ColorState.BLUE or color != ColorState.GREEN:
            return

        self._append_signal(
            Signal(
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
        )
        self.current_position = best_long

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
