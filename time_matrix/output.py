import json
import logging
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .indicators import MacdState, classify_color
from .models import ColorState, EventSnapshot, MinuteBar, Signal, SignalValidation

LOGGER = logging.getLogger(__name__)


def write_signals(path: Path, signals: list[Signal]) -> None:
    rows = [
        [
            signal.trade_time.isoformat(sep=" "),
            signal.action.value,
            signal.price,
            signal.reason,
            signal.p_min,
            signal.p_max,
            signal.trigger_period,
            signal.trigger_prev_color.value if signal.trigger_prev_color else "",
            signal.trigger_color.value if signal.trigger_color else "",
        ]
        for signal in signals
    ]
    write_sheet(
        path=path,
        title="开平仓信号",
        headers=[
            "时间",
            "动作",
            "价格",
            "原因",
            "区间最小周期",
            "区间最大周期",
            "触发周期",
            "触发前颜色",
            "触发后颜色",
        ],
        rows=rows,
    )
    LOGGER.info("信号文件已写入：%s 行 -> %s", len(signals), path)


def write_intervals(path: Path, intervals: list[dict[str, object]]) -> None:
    rows = [
        [
            item["time"],
            item["direction"],
            item["p_min"],
            item["p_max"],
            item["length"],
            item["trend_count"],
            item["max_consecutive_trend"],
            item["trend_ratio"],
            item["trigger_period"],
        ]
        for item in intervals
    ]
    write_sheet(
        path=path,
        title="共振区间变化",
        headers=[
            "时间",
            "方向",
            "区间最小周期",
            "区间最大周期",
            "区间长度",
            "趋势周期数",
            "最大连续趋势数",
            "趋势占比",
            "触发周期",
        ],
        rows=rows,
    )
    LOGGER.info("区间变化文件已写入：%s 行 -> %s", len(intervals), path)


def write_signal_validations(path: Path, validations: list[SignalValidation]) -> None:
    rows = [
        [
            item.validation_id,
            item.signal_time.isoformat(sep=" "),
            item.direction.value,
            item.p_min,
            item.p_max,
            item.length,
            item.trigger_period,
            item.elapsed_in_min_period,
            item.expected_minutes,
            item.observed_minutes,
            item.start_price,
            item.end_time.isoformat(sep=" ") if item.end_time else "",
            item.end_price if item.end_price is not None else "",
            item.return_pct if item.return_pct is not None else "",
            item.max_high,
            item.max_gain_time.isoformat(sep=" ") if item.max_gain_time else "",
            item.max_gain_observed_minute if item.max_gain_observed_minute is not None else "",
            item.max_gain_pct,
            item.min_low,
            item.max_drawdown_time.isoformat(sep=" ") if item.max_drawdown_time else "",
            item.max_drawdown_observed_minute if item.max_drawdown_observed_minute is not None else "",
            item.max_drawdown_pct,
            item.is_expected_direction,
            item.start_trend_count,
            item.end_trend_count if item.end_trend_count is not None else "",
            item.min_trend_count,
            item.max_trend_count,
            item.start_trend_ratio,
            item.end_trend_ratio if item.end_trend_ratio is not None else "",
            item.trend_count_change if item.trend_count_change is not None else "",
            item.trend_strength_change,
            item.interval_valid_at_end,
            item.completed,
            item.completion_reason,
        ]
        for item in validations
    ]
    write_sheet(
        path=path,
        title="算法验证",
        headers=[
            "验证编号",
            "信号时间",
            "方向",
            "区间最小周期",
            "区间最大周期",
            "区间长度",
            "触发周期",
            "最小周期已运行分钟",
            "预期观察分钟",
            "实际观察分钟",
            "起始价格",
            "结束时间",
            "结束价格",
            "结束涨跌幅百分比",
            "窗口最高价",
            "最高价出现时间",
            "最高价出现于第几根有效分钟",
            "最大浮盈百分比",
            "窗口最低价",
            "最低价出现时间",
            "最低价出现于第几根有效分钟",
            "最大回撤百分比",
            "是否符合预期方向",
            "起始趋势周期数",
            "结束趋势周期数",
            "窗口内最小趋势周期数",
            "窗口内最大趋势周期数",
            "起始趋势占比",
            "结束趋势占比",
            "趋势周期数变化",
            "趋势强弱变化",
            "结束时区间是否有效",
            "是否完整观察",
            "完成原因",
        ],
        rows=rows,
    )
    LOGGER.info("算法验证文件已写入：%s 行 -> %s", len(validations), path)


def write_event_snapshots(path: Path, snapshots: list[EventSnapshot]) -> None:
    rows = [
        [
            item.event_time.isoformat(sep=" "),
            item.event_type,
            item.reason,
            item.price,
            item.minute_open,
            item.minute_high,
            item.minute_low,
            item.minute_close,
            item.minute_volume,
            item.trading_day,
            item.day_index,
            item.position_state,
            item.position_open_time.isoformat(sep=" ") if item.position_open_time else "",
            item.position_open_price if item.position_open_price is not None else "",
            item.position_pnl if item.position_pnl is not None else "",
            item.position_high if item.position_high is not None else "",
            item.position_low if item.position_low is not None else "",
            item.old_p_min if item.old_p_min is not None else "",
            item.old_p_max if item.old_p_max is not None else "",
            item.old_length if item.old_length is not None else "",
            item.old_trend_count if item.old_trend_count is not None else "",
            item.old_trend_ratio if item.old_trend_ratio is not None else "",
            item.new_p_min if item.new_p_min is not None else "",
            item.new_p_max if item.new_p_max is not None else "",
            item.new_length if item.new_length is not None else "",
            item.new_trend_count if item.new_trend_count is not None else "",
            item.new_max_consecutive_trend if item.new_max_consecutive_trend is not None else "",
            item.new_trend_ratio if item.new_trend_ratio is not None else "",
            item.trigger_period if item.trigger_period is not None else "",
            item.trigger_macd if item.trigger_macd is not None else "",
            item.trigger_prev_color.value if item.trigger_prev_color else "",
            item.trigger_color.value if item.trigger_color else "",
            item.trigger_trend.value if item.trigger_trend else "",
            item.p_min_macd if item.p_min_macd is not None else "",
            item.p_min_color.value if item.p_min_color else "",
            item.p_min_trend.value if item.p_min_trend else "",
            item.p_max_macd if item.p_max_macd is not None else "",
            item.p_max_color.value if item.p_max_color else "",
            item.p_max_trend.value if item.p_max_trend else "",
            item.interval_change_type,
        ]
        for item in snapshots
    ]
    write_sheet(
        path=path,
        title="事件快照",
        headers=[
            "事件时间",
            "事件类型",
            "原因",
            "价格",
            "1分钟开盘价",
            "1分钟最高价",
            "1分钟最低价",
            "1分钟收盘价",
            "1分钟成交量",
            "交易日",
            "当日有效分钟序号",
            "持仓状态",
            "持仓开仓时间",
            "持仓开仓价",
            "持仓浮盈亏",
            "持仓最高价",
            "持仓最低价",
            "旧区间最小周期",
            "旧区间最大周期",
            "旧区间长度",
            "旧趋势周期数",
            "旧趋势占比",
            "新区间最小周期",
            "新区间最大周期",
            "新区间长度",
            "新趋势周期数",
            "新最大连续趋势数",
            "新趋势占比",
            "触发周期",
            "触发周期MACD",
            "触发前颜色",
            "触发后颜色",
            "触发周期趋势",
            "最小周期MACD",
            "最小周期颜色",
            "最小周期趋势",
            "最大周期MACD",
            "最大周期颜色",
            "最大周期趋势",
            "区间变化类型",
        ],
        rows=rows,
    )
    LOGGER.info("事件快照文件已写入：%s 行 -> %s", len(snapshots), path)


def write_summary(path: Path, summary: dict[str, object]) -> None:
    labels = {
        "minute_bars": "分钟线数量",
        "signal_count": "信号数量",
        "interval_change_count": "区间变化数量",
        "event_snapshot_count": "事件快照数量",
        "signal_validation_count": "算法验证数量",
        "signal_validation_success_count": "算法验证成功数量",
        "signal_validation_success_rate": "算法验证成功率百分比",
        "closed_trade_count": "完整交易笔数",
        "win_count": "盈利笔数",
        "loss_count": "亏损笔数",
        "win_rate": "胜率百分比",
        "total_pnl": "总盈亏",
        "average_pnl": "平均每笔盈亏",
        "open_position": "是否有未平仓",
        "warmup_end_time": "预热结束时间",
    }
    rows = [[labels.get(key, key), value] for key, value in summary.items()]
    write_sheet(path=path, title="回测总结", headers=["项目", "值"], rows=rows)
    LOGGER.info("回测总结文件已写入：%s", path)


def write_chart_data(
    path: Path,
    bars: list[MinuteBar],
    signals: list[Signal],
    validations: list[SignalValidation],
    intervals: list[dict[str, object]],
    epsilon: float,
    event_snapshots: list[EventSnapshot] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    macd_state = MacdState()
    previous_color = ColorState.NON
    macd_rows = []
    for bar in bars:
        hist = macd_state.update(bar.close_price, epsilon)
        color = classify_color(hist, previous_color, epsilon)
        previous_color = color
        macd_rows.append(
            {
                "time": bar.trade_time.isoformat(sep=" "),
                "value": hist[-1] if hist else None,
                "color": color.value,
            }
        )

    payload = {
        "bars": [
            {
                "time": bar.trade_time.isoformat(sep=" "),
                "open": bar.open_price,
                "close": bar.close_price,
                "low": bar.low_price,
                "high": bar.high_price,
                "volume": bar.volume,
                "trading_day": bar.trading_day,
                "day_index": bar.day_index,
            }
            for bar in bars
        ],
        "macd": macd_rows,
        "signals": [
            {
                "time": signal.trade_time.isoformat(sep=" "),
                "action": signal.action.value,
                "price": signal.price,
                "reason": signal.reason,
                "p_min": signal.p_min,
                "p_max": signal.p_max,
                "trigger_period": signal.trigger_period,
                "trigger_prev_color": signal.trigger_prev_color.value if signal.trigger_prev_color else "",
                "trigger_color": signal.trigger_color.value if signal.trigger_color else "",
            }
            for signal in signals
        ],
        "validations": [
            {
                "validation_id": item.validation_id,
                "signal_time": item.signal_time.isoformat(sep=" "),
                "direction": item.direction.value,
                "p_min": item.p_min,
                "p_max": item.p_max,
                "length": item.length,
                "trigger_period": item.trigger_period,
                "elapsed_in_min_period": item.elapsed_in_min_period,
                "expected_minutes": item.expected_minutes,
                "observed_minutes": item.observed_minutes,
                "start_price": item.start_price,
                "end_time": item.end_time.isoformat(sep=" ") if item.end_time else "",
                "end_price": item.end_price,
                "return_pct": item.return_pct,
                "max_high": item.max_high,
                "max_gain_time": item.max_gain_time.isoformat(sep=" ") if item.max_gain_time else "",
                "max_gain_observed_minute": item.max_gain_observed_minute,
                "max_gain_pct": item.max_gain_pct,
                "min_low": item.min_low,
                "max_drawdown_time": item.max_drawdown_time.isoformat(sep=" ") if item.max_drawdown_time else "",
                "max_drawdown_observed_minute": item.max_drawdown_observed_minute,
                "max_drawdown_pct": item.max_drawdown_pct,
                "is_expected_direction": item.is_expected_direction,
                "trend_strength_change": item.trend_strength_change,
                "interval_valid_at_end": item.interval_valid_at_end,
                "completed": item.completed,
                "completion_reason": item.completion_reason,
            }
            for item in validations
        ],
        "intervals": intervals,
        "event_snapshots": [
            {
                "event_time": item.event_time.isoformat(sep=" "),
                "event_type": item.event_type,
                "reason": item.reason,
                "price": item.price,
                "minute_open": item.minute_open,
                "minute_high": item.minute_high,
                "minute_low": item.minute_low,
                "minute_close": item.minute_close,
                "minute_volume": item.minute_volume,
                "trading_day": item.trading_day,
                "day_index": item.day_index,
                "position_state": item.position_state,
                "position_open_time": item.position_open_time.isoformat(sep=" ") if item.position_open_time else "",
                "position_open_price": item.position_open_price,
                "position_pnl": item.position_pnl,
                "position_high": item.position_high,
                "position_low": item.position_low,
                "old_p_min": item.old_p_min,
                "old_p_max": item.old_p_max,
                "old_length": item.old_length,
                "old_trend_count": item.old_trend_count,
                "old_trend_ratio": item.old_trend_ratio,
                "new_p_min": item.new_p_min,
                "new_p_max": item.new_p_max,
                "new_length": item.new_length,
                "new_trend_count": item.new_trend_count,
                "new_max_consecutive_trend": item.new_max_consecutive_trend,
                "new_trend_ratio": item.new_trend_ratio,
                "trigger_period": item.trigger_period,
                "trigger_macd": item.trigger_macd,
                "trigger_prev_color": item.trigger_prev_color.value if item.trigger_prev_color else "",
                "trigger_color": item.trigger_color.value if item.trigger_color else "",
                "trigger_trend": item.trigger_trend.value if item.trigger_trend else "",
                "p_min_macd": item.p_min_macd,
                "p_min_color": item.p_min_color.value if item.p_min_color else "",
                "p_min_trend": item.p_min_trend.value if item.p_min_trend else "",
                "p_max_macd": item.p_max_macd,
                "p_max_color": item.p_max_color.value if item.p_max_color else "",
                "p_max_trend": item.p_max_trend.value if item.p_max_trend else "",
                "interval_change_type": item.interval_change_type,
            }
            for item in (event_snapshots or [])
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("图表数据文件已写入：K线=%s，信号=%s，验证=%s -> %s", len(bars), len(signals), len(validations), path)


def write_sheet(path: Path, title: str, headers: list[str], rows: Iterable[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    format_sheet(sheet)
    workbook.save(path)


def format_sheet(sheet: Worksheet) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 40)
