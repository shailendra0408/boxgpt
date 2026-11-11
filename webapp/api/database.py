"""Database helpers isolated from the existing ingestion and RAG scripts."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg2


def connect():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return psycopg2.connect(database_url)

    config_path = Path(os.getenv("BOXGPT_CONFIG", "config.json"))
    if not config_path.exists():
        raise RuntimeError(
            "Set DATABASE_URL or provide config.json for local development."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    database = config["database"]["default"]
    return psycopg2.connect(
        host=database["host"],
        port=database["port"],
        user=database["user"],
        password=database["password"],
        dbname=database.get("database", database.get("dbname")),
    )


@contextmanager
def transaction():
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_web_schema() -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema)


def fetchone(sql: str, params: tuple[Any, ...] = ()):
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()


def fetchall(sql: str, params: tuple[Any, ...] = ()):
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
