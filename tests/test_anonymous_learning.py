from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import anonymous_learning_client as client  # noqa: E402
import anonymous_learning_server as server_module  # noqa: E402


def sample_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "skill_name": "caoyu-ai-director",
        "skill_version": "1.0.0",
        "event_type": "rule_violation",
        "stage_code": "video_prompt",
        "issue_code": "unexpected_field",
        "rule_id": "R17",
        "result": "fixed_locally",
        "severity": "medium",
        "client_version": "1.3.0",
        "occurrence_count": 1,
    }


class PrivacySchemaTests(unittest.TestCase):
    def test_valid_fixed_schema(self) -> None:
        self.assertEqual(client.validate_report(sample_report()), sample_report())

    def test_rejects_free_text_and_identity_fields(self) -> None:
        forbidden = (
            "message",
            "prompt",
            "assistant_reply",
            "file_path",
            "url",
            "user_id",
            "device_id",
            "email",
            "password",
            "cookie",
        )
        for key in forbidden:
            with self.subTest(key=key):
                report = sample_report()
                report[key] = "secret"
                with self.assertRaises(ValueError):
                    client.validate_report(report)

    def test_rejects_arbitrary_issue_and_rule_text(self) -> None:
        report = sample_report()
        report["issue_code"] = "customer_project_name"
        with self.assertRaises(ValueError):
            client.validate_report(report)
        report = sample_report()
        report["rule_id"] = "用户说的私人内容"
        with self.assertRaises(ValueError):
            client.validate_report(report)


class ConsentTests(unittest.TestCase):
    def test_enable_uses_official_default_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            with contextlib.redirect_stdout(io.StringIO()):
                result = client.main(
                    [
                        "--config",
                        str(config),
                        "enable",
                        "--accept-anonymous-sync",
                    ]
                )
            self.assertEqual(result, 0)
            stored = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(stored["endpoint"], client.DEFAULT_ENDPOINT)

    def test_enable_shows_full_notice_and_requires_explicit_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = client.main(
                    ["--config", str(config), "enable", "--endpoint", "https://example.com"]
                )
            self.assertEqual(result, 2)
            self.assertFalse(config.exists())
            notice = output.getvalue()
            self.assertIn("不会收集或上传", notice)
            self.assertIn("账号、密码", notice)
            self.assertIn("聊天内容", notice)

    def test_one_time_acceptance_enables_without_per_report_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = client.main(
                    [
                        "--config",
                        str(config),
                        "enable",
                        "--endpoint",
                        "http://127.0.0.1:8787",
                        "--accept-anonymous-sync",
                    ]
                )
            self.assertEqual(result, 0)
            stored = json.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(stored["enabled"])
            self.assertNotIn("user_id", stored)
            self.assertNotIn("device_id", stored)


class AggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "events.sqlite3"
        self.store = server_module.AggregateStore(self.database)
        handler = server_module.make_handler(self.store, {})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.store.close()
        self.temporary.cleanup()

    def test_duplicate_reports_are_aggregated_not_stored_as_raw_events(self) -> None:
        first = client.send_report(self.endpoint, sample_report())
        second = client.send_report(self.endpoint, sample_report())
        self.assertEqual(first["aggregate_count"], 1)
        self.assertEqual(second["aggregate_count"], 2)
        exported = self.store.export()
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["occurrence_count"], 2)

        connection = sqlite3.connect(self.database)
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(aggregates)").fetchall()
            }
        finally:
            connection.close()
        forbidden_columns = {
            "raw_payload",
            "message",
            "prompt",
            "file_path",
            "ip_address",
            "user_agent",
            "user_id",
            "device_id",
            "timestamp",
        }
        self.assertTrue(columns.isdisjoint(forbidden_columns))

    def test_server_rejects_extra_private_field(self) -> None:
        report = sample_report()
        report["password"] = "do-not-store"
        body = json.dumps(report).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint + "/v1/reports",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.assertEqual(self.store.export(), [])


if __name__ == "__main__":
    unittest.main()
