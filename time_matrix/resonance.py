from dataclasses import dataclass

from .models import Direction, PeriodSnapshot, ResonanceInterval, TrendState


@dataclass(frozen=True)
class IntervalStats:
    total: int
    trend_count: int
    max_consecutive_trend: int
    trend_ratio: float
    missing_count: int


def scan_best_interval(
    snapshots: dict[int, PeriodSnapshot],
    direction: Direction,
    min_length: int,
    min_consecutive_trend: int,
    min_ratio: float,
    trigger_divisor: int,
) -> ResonanceInterval | None:
    wanted_trend = TrendState.UP if direction == Direction.LONG else TrendState.DOWN
    if not snapshots:
        return None

    # 把每个周期的趋势状态转成 0/1 标记，再用前缀和加速区间计数。
    # 这样每个候选区间都可以 O(1) 算出趋势周期数量。
    max_period = max(snapshots)
    trend_flags = [0] * (max_period + 1)
    for period, snapshot in snapshots.items():
        if snapshot.trend == wanted_trend:
            trend_flags[period] = 1

    prefix = [0] * (max_period + 1)
    for period in range(1, max_period + 1):
        prefix[period] = prefix[period - 1] + trend_flags[period]

    # 从最长区间开始扫描。只要某个长度有合格候选，就不再看更短区间；
    # 同长度下优先取趋势占比更高的，再取 P_min 更小的。
    for length in range(max_period, min_length - 1, -1):
        best_for_length: ResonanceInterval | None = None
        for p_min in range(1, max_period - length + 2):
            p_max = p_min + length - 1
            trend_count = prefix[p_max] - prefix[p_min - 1]
            ratio = trend_count / length
            if ratio < min_ratio:
                continue
            max_consecutive_trend = max_consecutive_in_range(
                trend_flags,
                p_min,
                p_max,
            )
            if max_consecutive_trend < min_consecutive_trend:
                continue
            candidate = ResonanceInterval(
                direction=direction,
                p_min=p_min,
                p_max=p_max,
                length=length,
                trend_count=trend_count,
                max_consecutive_trend=max_consecutive_trend,
                trend_ratio=ratio,
                trigger_period=max(1, p_min // trigger_divisor),
            )
            if best_for_length is None:
                best_for_length = candidate
            elif candidate.trend_ratio > best_for_length.trend_ratio:
                best_for_length = candidate
            elif candidate.trend_ratio == best_for_length.trend_ratio and candidate.p_min < best_for_length.p_min:
                best_for_length = candidate
        if best_for_length is not None:
            return best_for_length

    return None


def interval_is_valid(
    snapshots: dict[int, PeriodSnapshot],
    interval: ResonanceInterval,
    min_ratio: float,
    min_trend_count: int,
    min_consecutive_trend: int,
) -> bool:
    # 持仓期间只校验开仓时锁定的原始区间。
    # 不用最新最优区间替换它，确保整个持仓周期内 P_min/P_max/P_trigger 稳定。
    stats = evaluate_interval(snapshots, interval.direction, interval.p_min, interval.p_max)
    if stats.total <= 0 or stats.missing_count > 0:
        return False
    if stats.trend_ratio < min_ratio:
        return False
    if min_trend_count > 0 and stats.trend_count < min_trend_count:
        return False
    if stats.max_consecutive_trend < min_consecutive_trend:
        return False
    return True


def evaluate_interval(
    snapshots: dict[int, PeriodSnapshot],
    direction: Direction,
    p_min: int,
    p_max: int,
) -> IntervalStats:
    wanted_trend = TrendState.UP if direction == Direction.LONG else TrendState.DOWN
    trend_count = 0
    consecutive_trend = 0
    max_consecutive_trend = 0
    total = 0
    missing_count = 0

    for period in range(p_min, p_max + 1):
        total += 1
        snapshot = snapshots.get(period)
        if snapshot is None:
            missing_count += 1
            consecutive_trend = 0
            continue
        if snapshot.trend == wanted_trend:
            trend_count += 1
            consecutive_trend += 1
            max_consecutive_trend = max(max_consecutive_trend, consecutive_trend)
        else:
            consecutive_trend = 0

    trend_ratio = trend_count / total if total else 0.0
    return IntervalStats(
        total=total,
        trend_count=trend_count,
        max_consecutive_trend=max_consecutive_trend,
        trend_ratio=trend_ratio,
        missing_count=missing_count,
    )


def interval_key(interval: ResonanceInterval | None) -> tuple | None:
    if interval is None:
        return None
    return (
        interval.direction,
        interval.p_min,
        interval.p_max,
        interval.length,
        interval.trend_count,
        interval.max_consecutive_trend,
        round(interval.trend_ratio, 6),
        interval.trigger_period,
    )


def max_consecutive_in_range(flags: list[int], start: int, end: int) -> int:
    current = 0
    best = 0
    for period in range(start, end + 1):
        if flags[period]:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
