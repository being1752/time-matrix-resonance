import argparse
import logging
from pathlib import Path

from .backtester import BacktestConfig, TimeMatrixBacktester
from .config import load_config, nested_section, section
from .data_loader import infer_max_period, load_minute_bars_from_mysql
from .output import (
    write_chart_data,
    write_event_snapshots,
    write_intervals,
    write_signal_validations,
    write_signals,
    write_summary,
)

DEFAULT_CONFIG = "config.toml"

LOGGER = logging.getLogger(__name__)


def configure_logging(level: str, log_file: str | None) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest the time matrix resonance algorithm.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="config file path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config)
    app_config = load_config(config_path)
    logging_config = section(app_config, "logging")
    configure_logging(
        str(logging_config.get("level", "INFO")),
        str(logging_config.get("file", "")) or None,
    )
    LOGGER.info("时间矩阵共振回测启动：配置文件=%s", config_path)

    # 运行时数据从 MySQL 读取。
    mysql_config = nested_section(app_config, "data", "mysql")
    bars = load_minute_bars_from_mysql(
        host=str(mysql_config.get("host", "localhost")),
        user=str(mysql_config.get("user", "root")),
        password=str(mysql_config.get("password", "")),
        database=str(mysql_config.get("database", "stock_data")),
        table=str(mysql_config.get("table", "stock_minute_quotes")),
        stock_code=str(mysql_config.get("stock_code", "")),
    )

    backtest_config = section(app_config, "backtest")
    max_bars = int(backtest_config.get("max_bars", 0))
    if max_bars > 0 and len(bars) > max_bars:
        original_count = len(bars)
        bars = bars[:max_bars]
        LOGGER.info(
            "回测数量限制已启用：原始分钟线=%s，限制=%s，实际参与回测=%s，结束时间=%s",
            original_count,
            max_bars,
            len(bars),
            bars[-1].trade_time,
        )
    entry_config = nested_section(app_config, "resonance", "entry")
    trigger_config = nested_section(app_config, "resonance", "trigger")
    exit_config = nested_section(app_config, "resonance", "exit")
    validation_config = section(app_config, "validation")
    configured_max_period = int(backtest_config.get("max_period", 0))
    max_period = configured_max_period if configured_max_period > 0 else infer_max_period(bars)
    trigger_divisor = max(1, int(trigger_config.get("divisor", 10)))
    backtest_runtime_config = BacktestConfig(
        max_period=max_period,
        entry_min_interval_length=int(entry_config.get("min_length", 10)),
        entry_min_interval_ratio=float(entry_config.get("min_ratio", 0.8)),
        entry_min_consecutive_trend=int(entry_config.get("min_consecutive_trend", 8)),
        trigger_divisor=trigger_divisor,
        exit_min_interval_ratio=float(exit_config.get("min_ratio", 0.8)),
        exit_min_trend_count=int(exit_config.get("min_trend_count", 0)),
        exit_min_consecutive_trend=int(exit_config.get("min_consecutive_trend", 8)),
        warmup_months=int(backtest_config.get("warmup_months", 3)),
        epsilon=float(backtest_config.get("epsilon", 1e-10)),
        progress_every=int(backtest_config.get("progress_every", 5000)),
        validation_enabled=bool(validation_config.get("enabled", True)),
        validation_min_expected_minutes=int(validation_config.get("min_expected_minutes", 1)),
    )
    result = TimeMatrixBacktester(backtest_runtime_config).run(bars)

    output_config = section(app_config, "output")
    output_dir = Path(str(output_config.get("dir", "backtest_output")))
    signals_path = output_dir / "signals.xlsx"
    intervals_path = output_dir / "intervals.xlsx"
    validations_path = output_dir / "signal_validation.xlsx"
    event_snapshots_path = output_dir / "event_snapshots.xlsx"
    summary_path = output_dir / "summary.xlsx"
    chart_data_path = output_dir / "chart_data.json"
    write_signals(signals_path, result.signals)
    write_intervals(intervals_path, result.intervals)
    write_signal_validations(validations_path, result.signal_validations)
    write_event_snapshots(event_snapshots_path, result.event_snapshots)
    write_summary(summary_path, result.summary)
    write_chart_data(
        chart_data_path,
        bars,
        result.signals,
        result.signal_validations,
        result.intervals,
        backtest_runtime_config.epsilon,
        result.event_snapshots,
    )
    chart_data_copy_to = str(output_config.get("chart_data_copy_to", "")).strip()
    if chart_data_copy_to:
        write_chart_data(
            Path(chart_data_copy_to),
            bars,
            result.signals,
            result.signal_validations,
            result.intervals,
            backtest_runtime_config.epsilon,
            result.event_snapshots,
        )

    LOGGER.info("时间矩阵共振回测完成")
    print(f"分钟线数量：{len(bars)}")
    print(f"最大周期：{max_period}")
    print(f"信号数量：{len(result.signals)} -> {signals_path}")
    print(f"区间变化数量：{len(result.intervals)} -> {intervals_path}")
    print(f"算法验证数量：{len(result.signal_validations)} -> {validations_path}")
    print(f"事件快照数量：{len(result.event_snapshots)} -> {event_snapshots_path}")
    print(f"回测总结：{summary_path}")
    print(f"图表数据：{chart_data_path}")
    if chart_data_copy_to:
        print(f"前端图表数据：{chart_data_copy_to}")
