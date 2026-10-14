#!/usr/bin/env python3
"""Anonymous, content-free learning-event client.

The client has a strict allowlist. It cannot transmit arbitrary text, chat
content, paths, URLs, credentials, device identifiers, or persistent user IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CONSENT_VERSION = 1
MAX_RESPONSE_BYTES = 16_384
DEFAULT_ENDPOINT = "https://caoyu-anonymous-learning.caoyu6059777.workers.dev"

EVENT_TYPES = (
    "rule_violation",
    "tool_failure",
    "workflow_break",
    "regression",
    "fix_verified",
)
STAGE_CODES = (
    "routing",
    "input_validation",
    "asset_generation",
    "script_generation",
    "storyboard",
    "image_generation",
    "video_prompt",
    "spreadsheet",
    "tool_execution",
    "packaging",
    "other",
)
ISSUE_CODES = (
    "rule_not_followed",
    "missing_required_output",
    "unexpected_field",
    "wrong_stage_order",
    "tool_error",
    "format_error",
    "continuity_error",
    "permission_blocked",
    "regression",
    "other_categorized",
)
RESULTS = ("observed", "fixed_locally", "verified_pass", "unresolved")
SEVERITIES = ("low", "medium", "high")

REPORT_KEYS = frozenset(
    {
        "schema_version",
        "skill_name",
        "skill_version",
        "event_type",
        "stage_code",
        "issue_code",
        "rule_id",
        "result",
        "severity",
        "client_version",
        "occurrence_count",
    }
)

CONSENT_NOTICE = """匿名共享学习说明

不会收集或上传：聊天内容、提示词、助手回复、小说/脚本/图片等作品内容、附件或文件内容、文件路径、网址、姓名、账号、密码、手机号、邮箱、密钥、Cookie、设备标识、持久用户标识。

只会上传：Skill名称和版本、预先定义的问题分类、流程阶段、公开规则编号、修复状态、严重程度及聚合次数。所有字段均为固定枚举或受限代码，不允许自由文本。

提交后只做匿名聚合，用于发现Skill的共性问题；不会根据这些数据直接修改Skill。你可以随时关闭匿名共享学习。"""


def default_config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "caoyu-skill-self-improver" / "anonymous-sync.json"
    return Path(tempfile.gettempdir()) / "caoyu-skill-self-improver" / "anonymous-sync.json"


def validate_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
        raise ValueError("公网同步地址必须使用HTTPS；HTTP仅允许localhost或回环地址。")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("同步地址必须是无账号、密码、查询参数或片段的服务根地址。")
    return endpoint.rstrip("/")


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    if set(report) != REPORT_KEYS:
        missing = sorted(REPORT_KEYS - set(report))
        extra = sorted(set(report) - REPORT_KEYS)
        raise ValueError(f"匿名事件字段不符合白名单；缺少={missing}，额外={extra}")
    if report["schema_version"] != SCHEMA_VERSION:
        raise ValueError("不支持的schema_version。")
    if not isinstance(report["skill_name"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,63}", report["skill_name"]
    ):
        raise ValueError("skill_name格式无效。")
    for key in ("skill_version", "client_version"):
        if not isinstance(report[key], str) or not re.fullmatch(
            r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", report[key]
        ):
            raise ValueError(f"{key}必须是X.Y.Z格式。")
    enum_fields = {
        "event_type": EVENT_TYPES,
        "stage_code": STAGE_CODES,
        "issue_code": ISSUE_CODES,
        "result": RESULTS,
        "severity": SEVERITIES,
    }
    for key, allowed in enum_fields.items():
        if report[key] not in allowed:
            raise ValueError(f"{key}不是允许的固定枚举。")
    if not isinstance(report["rule_id"], str) or not re.fullmatch(
        r"[A-Z0-9][A-Z0-9_-]{0,23}", report["rule_id"]
    ):
        raise ValueError("rule_id必须是最多24字符的公开规则代码。")
    count = report["occurrence_count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("occurrence_count必须是1至100的整数。")
    return report


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"enabled": False, "consent_version": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"enabled", "consent_version", "endpoint"}
    if not isinstance(data, dict) or not set(data).issubset(allowed):
        raise ValueError("本机配置文件格式无效。")
    return data


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def send_report(endpoint: str, report: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    validate_report(report)
    body = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/reports",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"同步服务拒绝请求：HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"匿名同步失败：{exc.reason}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("同步服务响应过大，已拒绝处理。")
    result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise RuntimeError("同步服务未确认接收。")
    return result


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    return validate_report(
        {
            "schema_version": SCHEMA_VERSION,
            "skill_name": args.skill_name,
            "skill_version": args.skill_version,
            "event_type": args.event_type,
            "stage_code": args.stage_code,
            "issue_code": args.issue_code,
            "rule_id": args.rule_id,
            "result": args.result,
            "severity": args.severity,
            "client_version": args.client_version,
            "occurrence_count": args.occurrence_count,
        }
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="匿名、无内容的Skill学习事件客户端")
    root.add_argument("--config", type=Path, default=default_config_path())
    commands = root.add_subparsers(dest="command", required=True)

    enable = commands.add_parser("enable", help="显示隐私说明并启用自动匿名同步")
    enable.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"匿名同步服务根地址（默认：{DEFAULT_ENDPOINT}）",
    )
    enable.add_argument("--accept-anonymous-sync", action="store_true")
    commands.add_parser("disable", help="关闭自动匿名同步")
    commands.add_parser("status", help="查看本机同步状态")

    submit = commands.add_parser("submit", help="提交一个严格白名单事件")
    submit.add_argument("--skill-name", required=True)
    submit.add_argument("--skill-version", required=True)
    submit.add_argument("--event-type", required=True, choices=EVENT_TYPES)
    submit.add_argument("--stage-code", required=True, choices=STAGE_CODES)
    submit.add_argument("--issue-code", required=True, choices=ISSUE_CODES)
    submit.add_argument("--rule-id", required=True)
    submit.add_argument("--result", required=True, choices=RESULTS)
    submit.add_argument("--severity", required=True, choices=SEVERITIES)
    submit.add_argument("--client-version", required=True)
    submit.add_argument("--occurrence-count", type=int, default=1)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "enable":
            print(CONSENT_NOTICE)
            if not args.accept_anonymous_sync:
                print("\n尚未启用：如接受以上说明，请再次执行并加入 --accept-anonymous-sync。")
                return 2
            endpoint = validate_endpoint(args.endpoint)
            save_config(
                args.config,
                {
                    "enabled": True,
                    "consent_version": CONSENT_VERSION,
                    "endpoint": endpoint,
                },
            )
            print("已启用匿名自动同步；后续仅提交固定白名单事件。")
            return 0
        if args.command == "disable":
            config["enabled"] = False
            save_config(args.config, config)
            print("已关闭匿名自动同步。")
            return 0
        if args.command == "status":
            enabled = config.get("enabled") is True and config.get("consent_version") == CONSENT_VERSION
            print(json.dumps({"enabled": enabled, "endpoint": config.get("endpoint")}, ensure_ascii=False))
            return 0
        if config.get("enabled") is not True or config.get("consent_version") != CONSENT_VERSION:
            raise RuntimeError("匿名同步尚未经过当前版本的一次性授权。")
        endpoint = validate_endpoint(str(config.get("endpoint", "")))
        result = send_report(endpoint, build_report(args))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
