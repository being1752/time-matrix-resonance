import csv
import logging
from pathlib import Path

from .models import Signal

LOGGER = logging.getLogger(__name__)


def write_signals(path: Path, signals: list[Signal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "time",
                "action",
                "price",
                "reason",
                "p_min",
                "p_max",
                "trigger_period",
                "trigger_prev_color",
                "trigger_color",
            ]
        )
        for signal in signals:
            writer.writerow(
                [
                    signal.trade_time.isoformat(sep=" "),
                    signal.action.value,
                    f"{signal.price:.4f}",
                    signal.reason,
                    signal.p_min,
                    signal.p_max,
                    signal.trigger_period,
                    signal.trigger_prev_color.value if signal.trigger_prev_color else "",
                    signal.trigger_color.value if signal.trigger_color else "",
                ]
            )
    LOGGER.info("信号文件已写入：%s 行 -> %s", len(signals), path)


def write_intervals(path: Path, intervals: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        fieldnames = [
            "time",
            "direction",
            "p_min",
            "p_max",
            "length",
            "trend_count",
            "max_consecutive_trend",
            "trend_ratio",
            "trigger_period",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(intervals)
    LOGGER.info("区间变化文件已写入：%s 行 -> %s", len(intervals), path)


def write_summary(path: Path, summary: dict[str, object]) -> None:
    labels = {
        "minute_bars": "分钟线数量",
        "signal_count": "信号数量",
        "interval_change_count": "区间变化数量",
        "closed_trade_count": "完整交易笔数",
        "win_count": "盈利笔数",
        "loss_count": "亏损笔数",
        "win_rate": "胜率百分比",
        "total_pnl": "总盈亏",
        "average_pnl": "平均每笔盈亏",
        "open_position": "是否有未平仓",
        "warmup_end_time": "预热结束时间",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["项目", "值"])
        for key, value in summary.items():
            writer.writerow([labels.get(key, key), value])
    LOGGER.info("回测总结文件已写入：%s", path)
