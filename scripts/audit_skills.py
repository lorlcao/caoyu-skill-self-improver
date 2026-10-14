#!/usr/bin/env python3
"""Read-only structural audit for personal Codex skill directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", re.DOTALL)
NAME_RE = re.compile(r"(?m)^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$")
DESCRIPTION_RE = re.compile(r"(?m)^description:\s*(.*)$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|(?<![\w.])/(?:Users|home)/[^\s`'\"<>]+)")
TODO_RE = re.compile(r"(?mi)^\s*\[?TODO(?::|\])")


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    match = FRONTMATTER_RE.search(text.replace("\r\n", "\n"))
    if not match:
        return {}, ["missing_or_invalid_frontmatter"]
    block = match.group(1)
    name_match = NAME_RE.search(block)
    description_match = DESCRIPTION_RE.search(block)
    result: dict[str, str] = {}
    if name_match:
        result["name"] = name_match.group(1).strip()
    else:
        errors.append("missing_name")
    if description_match:
        raw = description_match.group(1).strip()
        if raw in {">", "|", ">-", "|-", ">+", "|+"}:
            lines = block[description_match.end() :].splitlines()
            folded = []
            for line in lines:
                if line.startswith((" ", "\t")):
                    folded.append(line.strip())
                elif line.strip():
                    break
            raw = " ".join(folded)
        result["description"] = raw.strip("\"'")
        if not result["description"]:
            errors.append("empty_description")
    else:
        errors.append("missing_description")
    return result, errors


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(file.read_bytes())
        except OSError as exc:
            digest.update(f"READ_ERROR:{exc}".encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def markdown_issues(skill_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for file in skill_dir.rglob("*.md"):
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"unreadable:{file.relative_to(skill_dir)}:{exc}")
            continue
        if TODO_RE.search(text):
            warnings.append(f"todo_placeholder:{file.relative_to(skill_dir)}")
        for match in ABSOLUTE_PATH_RE.finditer(text):
            warnings.append(
                f"absolute_path:{file.relative_to(skill_dir)}:{match.group(0)}"
            )
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0].strip()
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            if target.startswith(("$", "{{", "~")):
                continue
            resolved = (file.parent / target).resolve()
            if not resolved.exists() and re.fullmatch(r"[A-Za-z0-9_-]+", target):
                # Markdown frequently uses symbolic placeholders such as
                # (URL) or numeric annotations such as (2000). They are not
                # intended to be local file links.
                continue
            if not resolved.exists():
                errors.append(
                    f"broken_link:{file.relative_to(skill_dir)}:{raw_target}"
                )
    return sorted(set(errors)), sorted(set(warnings))


def discover(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    found = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name == ".system":
            continue
        candidates = [p for p in child.iterdir() if p.is_file() and p.name.lower() == "skill.md"]
        if candidates:
            found.append(child)
    return found


def audit_skill(skill_dir: Path, source_root: Path) -> dict[str, Any]:
    manifest = next(
        p for p in skill_dir.iterdir() if p.is_file() and p.name.lower() == "skill.md"
    )
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        text = ""
        errors.append(f"unreadable_skill_md:{exc}")
    frontmatter, frontmatter_errors = parse_frontmatter(text)
    errors.extend(frontmatter_errors)
    name = frontmatter.get("name", skill_dir.name)
    if name != skill_dir.name:
        warnings.append(f"folder_name_mismatch:{skill_dir.name}!={name}")
    nested_manifests = [
        p for p in skill_dir.rglob("*") if p.is_file() and p.name.lower() == "skill.md"
    ]
    if len(nested_manifests) != 1:
        errors.append(f"skill_manifest_count:{len(nested_manifests)}")
    md_errors, md_warnings = markdown_issues(skill_dir)
    errors.extend(md_errors)
    warnings.extend(md_warnings)
    version_path = skill_dir / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None
    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if openai_yaml.exists():
        try:
            yaml_text = openai_yaml.read_text(encoding="utf-8")
            if "short_description:" not in yaml_text:
                warnings.append("openai_yaml_missing_short_description")
            if "default_prompt:" in yaml_text and f"${name}" not in yaml_text:
                warnings.append("default_prompt_missing_skill_name")
        except (OSError, UnicodeError) as exc:
            errors.append(f"unreadable_openai_yaml:{exc}")
    return {
        "name": name,
        "folder": skill_dir.name,
        "path": str(skill_dir),
        "source_root": str(source_root),
        "version": version,
        "description": frontmatter.get("description", ""),
        "tree_hash": tree_hash(skill_dir),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def default_roots() -> list[Path]:
    home = Path.home()
    cwd = Path.cwd()
    return [
        home / ".codex" / "skills",
        home / ".agents" / "skills",
        cwd / ".codex" / "skills",
        cwd / ".agents" / "skills",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Skill Audit",
        "",
        f"- Roots checked: {len(report['roots'])}",
        f"- Skills found: {report['summary']['skills']}",
        f"- Errors: {report['summary']['errors']}",
        f"- Warnings: {report['summary']['warnings']}",
        "",
        "| Skill | Version | Errors | Warnings | Path |",
        "|---|---:|---:|---:|---|",
    ]
    for item in report["skills"]:
        lines.append(
            f"| `{item['name']}` | {item['version'] or '-'} | "
            f"{len(item['errors'])} | {len(item['warnings'])} | `{item['path']}` |"
        )
    if report["duplicates"]:
        lines.extend(["", "## Duplicate names", ""])
        for duplicate in report["duplicates"]:
            lines.append(f"- `{duplicate['name']}`: " + ", ".join(duplicate["paths"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Skill parent directory; may be supplied more than once.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", help="Optional output file; stdout is the default.")
    args = parser.parse_args()

    roots = [Path(p).expanduser().resolve() for p in args.roots] if args.roots else default_roots()
    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root.resolve()))
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(root)

    skills: list[dict[str, Any]] = []
    for root in unique_roots:
        for skill_dir in discover(root):
            skills.append(audit_skill(skill_dir, root))

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in skills:
        by_name[item["name"]].append(item)
    duplicates = []
    for name, items in sorted(by_name.items()):
        if len(items) > 1:
            duplicates.append(
                {
                    "name": name,
                    "identical": len({item["tree_hash"] for item in items}) == 1,
                    "paths": [item["path"] for item in items],
                }
            )

    report = {
        "roots": [str(root) for root in unique_roots],
        "summary": {
            "skills": len(skills),
            "errors": sum(len(item["errors"]) for item in skills),
            "warnings": sum(len(item["warnings"]) for item in skills),
            "duplicate_names": len(duplicates),
        },
        "duplicates": duplicates,
        "skills": sorted(skills, key=lambda item: (item["name"], item["path"])),
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_markdown(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
