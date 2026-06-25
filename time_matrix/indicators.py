from dataclasses import dataclass

from .models import ColorState, TrendState


def sign(value: float, epsilon: float) -> int:
    if value > epsilon:
        return 1
    if value < -epsilon:
        return -1
    return 0


def classify_color(hist: list[float], previous_color: ColorState, epsilon: float) -> ColorState:
    # 颜色是单根 K 线级别的局部状态，用于触发开平仓事件。
    # 它和趋势状态分开：趋势看的是最后一次过零点之后的整段形态。
    if not hist or sign(hist[-1], epsilon) == 0:
        return ColorState.NON
    if len(hist) < 2:
        return ColorState.NON

    current = hist[-1]
    delta = current - hist[-2]
    delta_sign = sign(delta, epsilon)
    if delta_sign == 0:
        if previous_color in {ColorState.RED, ColorState.YELLOW, ColorState.BLUE, ColorState.GREEN}:
            return previous_color
        return ColorState.NON

    if current > epsilon and delta_sign > 0:
        return ColorState.RED
    if current > epsilon and delta_sign < 0:
        return ColorState.YELLOW
    if current < -epsilon and delta_sign < 0:
        return ColorState.BLUE
    if current < -epsilon and delta_sign > 0:
        return ColorState.GREEN
    return ColorState.NON


@dataclass
class MacdState:
    # 单个周期的增量 MACD 状态。每个周期都有自己的实例，
    # 所以 7 分钟 MACD 和 72 分钟 MACD 会分别基于各自的收盘价序列计算，
    # 不会复用导入数据里的 1 分钟指标。
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    fast_ema: float | None = None
    slow_ema: float | None = None
    dea: float | None = None
    hist: list[float] | None = None
    last_nonzero_sign: int = 0
    crossing_seen: bool = False
    segment_len: int = 0
    segment_last_value: float | None = None
    segment_increasing: bool = True
    segment_decreasing: bool = True
    trend: TrendState = TrendState.NON

    def update(self, close: float, epsilon: float) -> list[float]:
        if self.hist is None:
            self.hist = []

        # 使用通达信常见的 MACD 柱体口径：MACD = 2 * (DIF - DEA)。
        if self.fast_ema is None or self.slow_ema is None or self.dea is None:
            self.fast_ema = close
            self.slow_ema = close
            dif = 0.0
            self.dea = dif
        else:
            fast_alpha = 2.0 / (self.fast_period + 1.0)
            slow_alpha = 2.0 / (self.slow_period + 1.0)
            signal_alpha = 2.0 / (self.signal_period + 1.0)
            self.fast_ema = fast_alpha * close + (1.0 - fast_alpha) * self.fast_ema
            self.slow_ema = slow_alpha * close + (1.0 - slow_alpha) * self.slow_ema
            dif = self.fast_ema - self.slow_ema
            self.dea = signal_alpha * dif + (1.0 - signal_alpha) * self.dea

        self.hist.append(2.0 * (dif - self.dea))
        self.update_trend(self.hist[-1], epsilon)
        return self.hist

    def update_trend(self, value: float, epsilon: float) -> None:
        # 趋势判定保持严格：最后一次过零点之后，柱体必须严格单调。
        # 只要中间出现波浪式变化，就判为 non。
        current_sign = sign(value, epsilon)
        if current_sign == 0:
            self.trend = TrendState.NON
            return

        if self.last_nonzero_sign != 0 and current_sign != self.last_nonzero_sign:
            self.crossing_seen = True
            self.segment_len = 1
            self.segment_last_value = value
            self.segment_increasing = True
            self.segment_decreasing = True
            self.trend = TrendState.NON
        elif self.crossing_seen and self.segment_last_value is not None:
            delta = value - self.segment_last_value
            self.segment_len += 1
            if delta <= epsilon:
                self.segment_increasing = False
            if delta >= -epsilon:
                self.segment_decreasing = False
            self.segment_last_value = value
            if self.segment_len <= 1:
                self.trend = TrendState.NON
            elif self.segment_increasing:
                self.trend = TrendState.UP
            elif self.segment_decreasing:
                self.trend = TrendState.DOWN
            else:
                self.trend = TrendState.NON
        else:
            self.trend = TrendState.NON

        self.last_nonzero_sign = current_sign
