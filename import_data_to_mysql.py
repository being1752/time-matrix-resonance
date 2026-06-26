import argparse
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pymysql


DEFAULT_FILE = "001330.xls"
DEFAULT_HOST = "localhost"
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "zxc12345"
DEFAULT_DATABASE = "stock_data"
DEFAULT_TABLE = "stock_minute_quotes"


def read_lines(path: Path) -> tuple[list[str], str]:
    for encoding in ("gbk", "utf-8-sig", "utf-8"):
        try:
            return path.read_text(encoding=encoding).splitlines(), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, "cannot decode file as gbk or utf-8")


def clean_cell(value: str) -> str:
    return value.strip().replace("\u3000", "")


def parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(clean_cell(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def parse_int(value: str) -> int:
    return int(clean_cell(value))


def parse_stock_title(line: str) -> tuple[str, str]:
    match = re.search(r"(.+?)\s*\(([A-Za-z0-9._-]+)\)", line.strip())
    if not match:
        raise ValueError(f"cannot parse stock name/code from title: {line!r}")
    return match.group(1).strip(), match.group(2)


def parse_rows(path: Path) -> tuple[str, str, list[tuple]]:
    lines, encoding = read_lines(path)
    if not lines:
        raise ValueError(f"empty file: {path}")

    stock_name, stock_code = parse_stock_title(lines[0])
    rows = []

    for line_no, line in enumerate(lines[1:], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "\t" not in stripped:
            continue
        if "时间" in stripped and "开盘" in stripped:
            continue

        parts = [clean_cell(part) for part in line.split("\t")]
        parts = [part for part in parts if part != ""]
        if len(parts) < 6:
            continue

        try:
            trade_time = datetime.strptime(parts[0], "%Y/%m/%d-%H:%M:%S")
        except ValueError:
            try:
                trade_time = datetime.strptime(parts[0], "%Y/%m/%d-%H:%M")
            except ValueError as exc:
                raise ValueError(f"line {line_no}: invalid time value {parts[0]!r}") from exc

        macd_dif = parse_decimal(parts[6]) if len(parts) > 6 else Decimal("0")
        macd_dea = parse_decimal(parts[7]) if len(parts) > 7 else Decimal("0")
        macd_macd = parse_decimal(parts[8]) if len(parts) > 8 else Decimal("0")

        rows.append(
            (
                stock_code,
                stock_name,
                trade_time,
                parse_decimal(parts[1]),
                parse_decimal(parts[2]),
                parse_decimal(parts[3]),
                parse_decimal(parts[4]),
                parse_int(parts[5]),
                macd_dif,
                macd_dea,
                macd_macd,
                path.name,
            )
        )

    if not rows:
        raise ValueError(f"no data rows parsed from {path} using {encoding}")
    return stock_name, stock_code, rows


def connect_without_database(args: argparse.Namespace):
    return pymysql.connect(
        host=args.host,
        user=args.user,
        password=args.password,
        charset="utf8mb4",
        autocommit=True,
    )


def connect_database(args: argparse.Namespace):
    return pymysql.connect(
        host=args.host,
        user=args.user,
        password=args.password,
        database=args.database,
        charset="utf8mb4",
        autocommit=False,
    )


def ensure_schema(args: argparse.Namespace) -> None:
    create_database_sql = (
        f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    create_table_sql = f"""
CREATE TABLE IF NOT EXISTS `{args.table}` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `stock_code` VARCHAR(16) NOT NULL COMMENT '股票代码',
  `stock_name` VARCHAR(64) NOT NULL COMMENT '股票名称',
  `trade_time` DATETIME NOT NULL COMMENT '交易时间',
  `open_price` DECIMAL(12,4) NOT NULL COMMENT '开盘',
  `high_price` DECIMAL(12,4) NOT NULL COMMENT '最高',
  `low_price` DECIMAL(12,4) NOT NULL COMMENT '最低',
  `close_price` DECIMAL(12,4) NOT NULL COMMENT '收盘',
  `volume` BIGINT NOT NULL COMMENT '成交量',
  `macd_dif` DECIMAL(12,4) NOT NULL COMMENT 'MACD.DIF',
  `macd_dea` DECIMAL(12,4) NOT NULL COMMENT 'MACD.DEA',
  `macd_macd` DECIMAL(12,4) NOT NULL COMMENT 'MACD.MACD',
  `source_file` VARCHAR(255) NOT NULL COMMENT '来源文件',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_stock_time` (`stock_code`, `trade_time`),
  KEY `idx_trade_time` (`trade_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

    with connect_without_database(args) as conn:
        with conn.cursor() as cursor:
            cursor.execute(create_database_sql)

    with connect_database(args) as conn:
        with conn.cursor() as cursor:
            cursor.execute(create_table_sql)
        conn.commit()


def import_rows(args: argparse.Namespace, rows: list[tuple]) -> int:
    insert_sql = f"""
INSERT INTO `{args.table}` (
  `stock_code`, `stock_name`, `trade_time`,
  `open_price`, `high_price`, `low_price`, `close_price`,
  `volume`, `macd_dif`, `macd_dea`, `macd_macd`, `source_file`
) VALUES (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
  `stock_name` = VALUES(`stock_name`),
  `open_price` = VALUES(`open_price`),
  `high_price` = VALUES(`high_price`),
  `low_price` = VALUES(`low_price`),
  `close_price` = VALUES(`close_price`),
  `volume` = VALUES(`volume`),
  `macd_dif` = VALUES(`macd_dif`),
  `macd_dea` = VALUES(`macd_dea`),
  `macd_macd` = VALUES(`macd_macd`),
  `source_file` = VALUES(`source_file`);
"""
    with connect_database(args) as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(rows), args.batch_size):
                cursor.executemany(insert_sql, rows[start : start + args.batch_size])
        conn.commit()
    return len(rows)


def fetch_monthly_counts(args: argparse.Namespace, stock_code: str) -> list[tuple[str, int]]:
    with connect_database(args) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
SELECT LEFT(`trade_time`, 7) AS `month`, COUNT(*) AS `rows`
FROM `{args.table}`
WHERE `stock_code` = %s
GROUP BY `month`
ORDER BY `month`
""",
                (stock_code,),
            )
            return list(cursor.fetchall())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import minute quote data into local MySQL.")
    parser.add_argument("--file", default=DEFAULT_FILE, help="source xls/text file path")
    parser.add_argument("--host", default=DEFAULT_HOST, help="MySQL host")
    parser.add_argument("--user", default=DEFAULT_USER, help="MySQL user")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="MySQL password")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="database name")
    parser.add_argument("--table", default=DEFAULT_TABLE, help="table name")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per batch insert")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    file_path = Path(args.file)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    stock_name, stock_code, rows = parse_rows(file_path)
    ensure_schema(args)
    imported = import_rows(args, rows)
    print(
        f"Imported {imported} rows for {stock_name}({stock_code}) "
        f"into {args.database}.{args.table}"
    )
    print("Monthly row counts:")
    for month, count in fetch_monthly_counts(args, stock_code):
        print(f"  {month}: {count}")


if __name__ == "__main__":
    main()
