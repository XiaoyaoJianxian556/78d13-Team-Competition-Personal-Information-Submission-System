#!/usr/bin/env python3
"""把 MySQL 成员表同步到 members.csv（基于 PyMySQL）。

数据库地址、端口、账号、密码、库名全部通过命令行参数指定；目标表默认 members，
字段与 CSV 表头保持一致（gaijin_id / name / state / join_date / landforce / airforce / navy），
数据库是唯一数据来源，导出结果会覆盖 CSV；数据库中已不存在的成员会从 CSV 移除。

用法：

    pip install pymysql
    python script/update_member.py --host 127.0.0.1 --port 3306 --user root --database team
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from pymysql.cursors import DictCursor

import pymysql


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "config" / "teammate_info" / "members.csv"
DEFAULT_TABLE = "members"
KEY_FIELD = "gaijin_id"
CSV_HEADERS = [KEY_FIELD, "name", "state", "join_date", "landforce", "airforce", "navy"]
DATE_FIELDS = {"join_date"}
DATE_PATTERNS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")
ENCODING_CANDIDATES = ("utf-8-sig", "gb18030", "big5")
DATE_TYPES = ("date", "datetime", "timestamp")
TEXT_LIMIT = 64 if False else 255


def decode_text(raw: bytes, encoding: str | None) -> str:
    """按指定或自动探测的编码解码 CSV 字节。"""
    if encoding:
        return raw.decode(encoding)
    for candidate in ENCODING_CANDIDATES:
        try:
            return raw.decode(candidate)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 CSV 编码，请用 --encoding 指定（members.csv 通常是 GB18030）")


def read_rows(csv_path: Path, encoding: str | None = None) -> tuple[list[str], list[dict[str, str]]]:
    """读取 members.csv，返回 (表头, 行数据)。"""
    if not csv_path.is_file():
        raise FileNotFoundError(f"找不到 CSV 文件：{csv_path}")

    reader = csv.DictReader(decode_text(csv_path.read_bytes(), encoding).splitlines())
    if not reader.fieldnames:
        raise ValueError(f"{csv_path} 没有表头")

    headers = [name.strip() for name in reader.fieldnames if name and name.strip()]
    if KEY_FIELD not in headers:
        raise ValueError(f"{csv_path} 表头缺少主键字段 {KEY_FIELD}")

    rows: list[dict[str, str]] = []
    for line_no, row in enumerate(reader, 2):
        item = {
            (key or "").strip(): ("" if value is None else str(value).strip())
            for key, value in row.items()
            if key
        }
        if not any(item.values()):
            continue
        if not item.get(KEY_FIELD):
            raise ValueError(f"{csv_path} 第 {line_no} 行的 {KEY_FIELD} 为空")
        rows.append(item)
    return headers, rows


def parse_date(text: str) -> str | None:
    """把 2026/6/5 之类的日期统一成 2026-06-05，空值返回 None。"""
    value = text.strip()
    if not value:
        return None
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def parse_number(text: str) -> Any:
    value = text.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def column_type(field: str) -> str:
    """CSV 表头对应的建表类型（表不存在时使用）。"""
    if field == KEY_FIELD:
        return "VARCHAR(64)"
    if field in DATE_FIELDS:
        return "DATE"
    return f"VARCHAR({TEXT_LIMIT})"


def connect(args: argparse.Namespace) -> pymysql.connections.Connection:
    password = args.password
    if password is None:
        password = args.password_env or ""
    return pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        database=args.database,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=DictCursor
    )


def fetch_columns(cursor: Any, database: str, table: str) -> dict[str, str]:
    """读取数据库中已存在的字段及其类型。"""
    cursor.execute(
        "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (database, table),
    )
    return {row["COLUMN_NAME"]: row["COLUMN_TYPE"].lower() for row in cursor.fetchall()}


def fetch_members(cursor: Any, table: str) -> list[dict[str, Any]]:
    """按 CSV 字段顺序读取数据库中的全部成员。"""
    column_list = ", ".join(f"`{field}`" for field in CSV_HEADERS)
    cursor.execute(f"SELECT {column_list} FROM `{table}` ORDER BY `{KEY_FIELD}`")
    return list(cursor.fetchall())


def write_members(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    """用数据库内容覆盖 CSV，并保持网页可识别的 UTF-8 编码。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    field: "" if row[field] is None else str(row[field])
                    for field in CSV_HEADERS
                })
        temporary_path.replace(csv_path)
    except OSError:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def ensure_key_constraint(cursor: Any, database: str, table: str, create: bool) -> None:
    """确保 gaijin_id 有独立的唯一索引，供 upsert 按玩家 ID 判定冲突。"""
    cursor.execute(
        "SELECT INDEX_NAME, NON_UNIQUE, COUNT(*) AS column_count, "
        "SUM(COLUMN_NAME = %s) AS key_column_count "
        "FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "GROUP BY INDEX_NAME, NON_UNIQUE",
        (KEY_FIELD, database, table),
    )
    has_unique_key = any(
        row["NON_UNIQUE"] == 0
        and row["column_count"] == 1
        and row["key_column_count"] == 1
        for row in cursor.fetchall()
    )
    if has_unique_key:
        return
    if not create:
        raise ValueError(
            f"数据表 {table} 的 {KEY_FIELD} 不是唯一键，"
            "无法按玩家 ID 更新（可用 --create-table 自动补充唯一索引）"
        )
    cursor.execute(f"ALTER TABLE `{table}` ADD UNIQUE (`{KEY_FIELD}`)")


def ensure_columns(cursor: Any, database: str, table: str, headers: list[str], create: bool) -> dict[str, str]:
    """表不存在则建表；缺少的 CSV 字段则补齐，返回最终的字段类型表。"""
    columns = fetch_columns(cursor, database, table)
    if not columns:
        if not create:
            raise ValueError(f"数据表 {database}.{table} 不存在（可用 --create-table 自动建表）")
        definitions = [f"`{field}` {column_type(field)}" for field in headers]
        definitions.append(f"PRIMARY KEY (`{KEY_FIELD}`)")
        cursor.execute(
            f"CREATE TABLE `{table}` ({', '.join(definitions)}) "
            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        )
        return fetch_columns(cursor, database, table)

    for field in headers:
        if field not in columns:
            if not create:
                raise ValueError(f"数据表 {table} 缺少字段 {field}（可用 --create-table 补齐）")
            cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{field}` {column_type(field)}")
    ensure_key_constraint(cursor, database, table, create)
    return fetch_columns(cursor, database, table)


def build_payload(headers: list[str], rows: list[dict[str, str]], columns: dict[str, str]) -> list[tuple]:
    payload: list[tuple] = []
    for row in rows:
        values = []
        for field in headers:
            column = columns.get(field, column_type(field))
            value = row.get(field, "")
            if not value:
                values.append(None)
            elif any(column.startswith(kind) for kind in DATE_TYPES):
                values.append(parse_date(value))
            elif column.startswith(("int", "bigint", "smallint", "tinyint", "decimal", "float", "double")):
                values.append(parse_number(value))
            else:
                values.append(value)
        payload.append(tuple(values))
    return payload


def upsert(cursor: Any, table: str, headers: list[str], rows: list[dict[str, str]], columns: dict[str, str]) -> int:
    column_list = ", ".join(f"`{field}`" for field in headers)
    placeholders = ", ".join(["%s"] * len(headers))
    updates = ", ".join(f"`{field}` = VALUES(`{field}`)" for field in headers if field != KEY_FIELD)
    sql = (
        f"INSERT INTO `{table}` ({column_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    return cursor.executemany(sql, build_payload(headers, rows, columns))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 MySQL 成员表同步到 members.csv")
    parser.add_argument("--host", default="127.0.0.1", help="数据库地址，默认 127.0.0.1")
    parser.add_argument("-P","--port", type=int, default=3306, help="数据库端口，默认 3306")
    parser.add_argument("-u","--user", required=True, help="数据库用户名")
    parser.add_argument("-p","--password", default=None, help="数据库密码，默认读取环境变量 MEMBER_DB_PASSWORD")
    parser.add_argument("-db","--database", required=True, help="数据库名")
    parser.add_argument("-tb","--table", default=DEFAULT_TABLE, help=f"数据表名，默认 {DEFAULT_TABLE}")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help=f"CSV 路径，默认 {DEFAULT_CSV}")
    parser.add_argument("--encoding", default=None, help="CSV 编码，默认自动探测（UTF-8/GB18030/BIG5）")
    parser.add_argument("--dry-run", action="store_true", help="只读取并统计，不覆盖 CSV")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.password_env = os_environ_password()
    try:
        connection = connect(args)
    except (OSError, ValueError, pymysql.err.Error) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    try:
        with connection:
            with connection.cursor() as cursor:
                columns = fetch_columns(cursor, args.database, args.table)
                missing = [field for field in CSV_HEADERS if field not in columns]
                if missing:
                    raise ValueError(f"数据表 {args.table} 缺少字段：{', '.join(missing)}")
                rows = fetch_members(cursor, args.table)
        if not args.dry_run:
            write_members(args.csv, rows)
    except (OSError, ValueError, pymysql.err.Error) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"CSV：{args.csv}（{len(rows)} 行，字段：{', '.join(CSV_HEADERS)}）")
    print(f"目标：{args.user}@{args.host}:{args.port}/{args.database}.{args.table}")
    if args.dry_run:
        print(f"读取完成：数据库中有 {len(rows)} 行（--dry-run 未修改 CSV）")
    else:
        print(f"同步完成：已用数据库内容覆盖 {args.csv}")
    return 0


def os_environ_password() -> str:
    import os

    return os.environ.get("MEMBER_DB_PASSWORD", "")


if __name__ == "__main__":
    raise SystemExit(main())