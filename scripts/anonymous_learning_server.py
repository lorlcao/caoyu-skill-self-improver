#!/usr/bin/env python3
"""Content-free anonymous learning aggregation service prototype."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from anonymous_learning_client import REPORT_KEYS, validate_report


MAX_BODY_BYTES = 4096


class AggregateStore:
    def __init__(self, database: Path):
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS aggregates (
                fingerprint TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                skill_name TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                event_type TEXT NOT NULL,
                stage_code TEXT NOT NULL,
                issue_code TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                result TEXT NOT NULL,
                severity TEXT NOT NULL,
                client_version TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1)
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def fingerprint(report: dict[str, Any]) -> str:
        normalized = dict(report)
        normalized["occurrence_count"] = 0
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def add(self, report: dict[str, Any]) -> int:
        validate_report(report)
        fingerprint = self.fingerprint(report)
        columns = sorted(REPORT_KEYS - {"occurrence_count"})
        values = [report[column] for column in columns]
        with self.lock:
            self.connection.execute(
                f"""
                INSERT INTO aggregates (fingerprint, {', '.join(columns)}, occurrence_count)
                VALUES (?, {', '.join('?' for _ in columns)}, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    occurrence_count = occurrence_count + excluded.occurrence_count
                """,
                [fingerprint, *values, report["occurrence_count"]],
            )
            row = self.connection.execute(
                "SELECT occurrence_count FROM aggregates WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            self.connection.commit()
        return int(row[0])

    def export(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT schema_version, skill_name, skill_version, event_type,
                       stage_code, issue_code, rule_id, result, severity,
                       client_version, occurrence_count
                FROM aggregates
                ORDER BY occurrence_count DESC, skill_name, rule_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()


def load_releases(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("发布信息必须是对象。")
    clean: dict[str, Any] = {}
    for skill, release in data.items():
        if not isinstance(skill, str) or not isinstance(release, dict):
            raise ValueError("发布信息格式无效。")
        if set(release) != {"version", "download_url"}:
            raise ValueError("每项发布信息只能包含version与download_url。")
        clean[skill] = release
    return clean


def make_handler(store: AggregateStore, releases: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AnonymousLearning/1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/health":
                self.send_json(HTTPStatus.OK, {"ok": True, "schema_version": 1})
                return
            if parsed.path == "/v1/releases/latest":
                query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
                skill_name = query.get("skill_name", [""])[0]
                release = releases.get(skill_name)
                self.send_json(HTTPStatus.OK, {"skill_name": skill_name, "release": release})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/reports":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if length < 2 or length > MAX_BODY_BYTES:
                    raise ValueError("请求体大小无效。")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("只接受application/json。")
                raw = self.rfile.read(length)
                report = json.loads(raw.decode("utf-8"))
                if not isinstance(report, dict):
                    raise ValueError("匿名事件必须是对象。")
                validate_report(report)
                aggregate_count = store.add(report)
                self.send_json(
                    HTTPStatus.ACCEPTED,
                    {"accepted": True, "aggregate_count": aggregate_count},
                )
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"accepted": False, "error": str(exc)})

    return Handler


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="匿名Skill学习事件聚合服务")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--database", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--releases", type=Path)
    export = commands.add_parser("export")
    export.add_argument("--database", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = AggregateStore(args.database)
    try:
        if args.command == "export":
            print(json.dumps(store.export(), ensure_ascii=False, indent=2))
            return 0
        releases = load_releases(args.releases)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(store, releases))
        print(f"Anonymous learning server: http://{args.host}:{server.server_port}", file=sys.stderr)
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
