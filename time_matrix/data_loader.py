import logging
from datetime import datetime
from typing import Iterable

import pymysql

from .models import MinuteBar

LOGGER = logging.getLogger(__name__)


def load_minute_bars_from_mysql(
    host: str,
    user: str,
    password: str,
    database: str,
    table: str,
    stock_code: str = "",
    charset: str = "utf8mb4",
) -> list[MinuteBar]:
    # 算法只消费标准化后的 1 分钟 K 线。MySQL 是唯一数据源；
    # 这里故意不读取库里的 MACD 字段，因为所有周期都要用自己的收盘价序列重新计算 MACD。
    sql = f"""
SELECT `trade_time`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`
FROM `{table}`
{ "WHERE `stock_code` = %s" if stock_code else "" }
ORDER BY `trade_time`
"""
    params = (stock_code,) if stock_code else None
    bars: list[MinuteBar] = []
    day_counts: dict[str, int] = {}

    LOGGER.info(
        "开始从 MySQL 读取分钟线：host=%s，database=%s，table=%s，stock_code=%s",
        host,
        database,
        table,
        stock_code or "*",
    )
    with pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        charset=charset,
        cursorclass=pymysql.cursors.DictCursor,
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                trade_time = row["trade_time"]
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time)
                trading_day = trade_time.strftime("%Y/%m/%d")
                day_counts[trading_day] = day_counts.get(trading_day, 0) + 1
                # day_index 是当日有效交易分钟序号。
                # 它只统计数据库里真实存在的分钟 K 线，因此午休不会拉长周期窗口。
                bars.append(
                    MinuteBar(
                        trade_time=trade_time,
                        open_price=float(row["open_price"]),
                        high_price=float(row["high_price"]),
                        low_price=float(row["low_price"]),
                        close_price=float(row["close_price"]),
                        volume=int(row["volume"]),
                        trading_day=trading_day,
                        day_index=day_counts[trading_day],
                    )
                )

    if not bars:
        raise ValueError(f"MySQL 表 {database}.{table} 没有读取到分钟线数据")

    LOGGER.info("MySQL 分钟线读取完成：%s 根", len(bars))
    LOGGER.info("识别到交易日：%s 天", len(day_counts))
    return bars


def infer_max_period(bars: Iterable[MinuteBar]) -> int:
    # 最大周期来自单个交易日内观察到的最大有效分钟数，不写死市场交易时长。
    counts: dict[str, int] = {}
    for bar in bars:
        counts[bar.trading_day] = max(counts.get(bar.trading_day, 0), bar.day_index)
    max_period = max(counts.values())
    LOGGER.info("推断最大周期：%s", max_period)
    return max_period
