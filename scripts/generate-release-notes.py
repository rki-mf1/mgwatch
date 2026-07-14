import argparse
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"

CATEGORIES = OrderedDict(
    [
        (
            "Security",
            (
                "auth",
                "cookie",
                "credential",
                "ldap",
                "login",
                "secret",
                "security",
                "vulnerability",
            ),
        ),
        (
            "Operations",
            (
                "backup",
                "compose",
                "deploy",
                "digest",
                "docker",
                "health",
                "monitor",
                "restore",
                "retention",
            ),
        ),
        (
            "Tests/CI",
            (
                "ci",
                "coverage",
                "dependabot",
                "github actions",
                "smoke",
                "test",
                "trivy",
                "workflow",
            ),
        ),
        (
            "Documentation",
            (
                "changelog",
                "docs",
                "documentation",
                "readme",
                "release notes",
            ),
        ),
    ]
)


@dataclass(frozen=True)
class Commit:
    sha: str
    short_sha: str
    subject: str


def parse_git_log(output):
    commits = []
    for record in output.strip(RECORD_SEPARATOR).split(RECORD_SEPARATOR):
        record = record.strip()
        if not record:
            continue
        fields = record.split(FIELD_SEPARATOR)
        if len(fields) != 3:
            raise ValueError(f"Unexpected git log record: {record!r}")
        commits.append(Commit(sha=fields[0], short_sha=fields[1], subject=fields[2]))
    return commits


def collect_commits(from_ref, to_ref):
    result = subprocess.run(
        [
            "git",
            "log",
            "--reverse",
            f"--format=%H{FIELD_SEPARATOR}%h{FIELD_SEPARATOR}%s{RECORD_SEPARATOR}",
            f"{from_ref}..{to_ref}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_git_log(result.stdout)


def classify_subject(subject):
    normalized = subject.lower()
    for category, keywords in CATEGORIES.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Other changes"


def group_commits(commits):
    grouped = OrderedDict((category, []) for category in CATEGORIES)
    grouped["Other changes"] = []
    for commit in commits:
        grouped[classify_subject(commit.subject)].append(commit)
    return grouped


def render_release_notes(commits, *, from_ref, to_ref, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc)
    timestamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Release Notes",
        "",
        f"Generated: {timestamp}",
        f"Range: `{from_ref}..{to_ref}`",
        "",
    ]
    if not commits:
        lines.extend(["No commits found in this range.", ""])
        return "\n".join(lines)

    for category, category_commits in group_commits(commits).items():
        if not category_commits:
            continue
        lines.extend([f"## {category}", ""])
        for commit in category_commits:
            lines.append(f"- {commit.subject} (`{commit.short_sha}`)")
        lines.append("")
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate draft release notes from local git history."
    )
    parser.add_argument(
        "--from",
        dest="from_ref",
        required=True,
        help="Previous release tag or commit.",
    )
    parser.add_argument(
        "--to",
        dest="to_ref",
        default="HEAD",
        help="Target release tag, commit, or branch. Defaults to HEAD.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional Markdown output path. Defaults to stdout.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    notes = render_release_notes(
        collect_commits(args.from_ref, args.to_ref),
        from_ref=args.from_ref,
        to_ref=args.to_ref,
    )
    if args.output:
        args.output.write_text(notes, encoding="utf-8")
    else:
        print(notes, end="")


if __name__ == "__main__":
    main()
