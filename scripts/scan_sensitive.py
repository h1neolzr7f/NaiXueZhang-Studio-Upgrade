from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


# Patterns deliberately match values, but findings never print those values.
PATTERN_RULES = (
    ("openai-or-generic-sk-token", r"(?-i:\bsk-[A-Za-z0-9_-]{32,}\b)"),
    ("novelai-token", r"(?-i:\bpst-[A-Za-z0-9_-]{48,}\b)"),
    ("github-classic-token", r"(?-i:\bgh[pousr]_[A-Za-z0-9]{36,255}\b)"),
    (
        "github-fine-grained-token",
        r"(?-i:\bgithub_pat_[A-Za-z0-9_]{20,255}\b)",
    ),
    ("aws-access-key", r"(?-i:\bAKIA[0-9A-Z]{16}\b)"),
    ("google-api-key", r"(?-i:\bAIza[0-9A-Za-z_-]{35}\b)"),
    ("slack-token", r"(?-i:\bxox[baprs]-[0-9A-Za-z-]{10,}\b)"),
    (
        "credential-field",
        r"[\"'](?:refresh_token|access_token|api_key|client_secret|password)[\"']"
        r"\s*[:=]\s*[\"'][^\"'\r\n]{16,}[\"']",
    ),
    (
        "authorization-bearer",
        r"\bBearer\s+(?:eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}"
        r"\.[A-Za-z0-9_-]{8,}|[A-Za-z0-9._~-]{32,})\b",
    ),
    (
        "cookie-or-session",
        r"[\"']?(?:cookie|sessionid|cf_clearance)[\"']?\s*[:=]\s*"
        r"[\"'][^\"'\r\n]{16,}[\"']",
    ),
    (
        "private-key",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    ),
    (
        "credential-in-url",
        r"\b(?:https?|postgres(?:ql)?|mysql|redis)://[^\s/:@]+:[^\s/@]+@[^\s]+",
    ),
    (
        "absolute-user-path",
        r"(?:[A-Z]:\\Users\\[^\\\r\n]+|"
        r"(?<![A-Za-z0-9:/])/(?:Users|home)/[^/\r\n]+)",
    ),
    (
        "email-account-identifier",
        r"\b[A-Z0-9._%+-]+@(?!(?:example\.(?:com|org|net)|users\.noreply\.github\.com)\b)"
        r"[A-Z0-9.-]+\.[A-Z]{2,}\b",
    ),
)
DEFAULT_PATTERNS = tuple(pattern for _, pattern in PATTERN_RULES)
PATTERN_LABELS = {pattern: label for label, pattern in PATTERN_RULES}

KNOWN_TEST_PLACEHOLDERS = (
    "sk-abcdefghijklmnopqrstuvwxyz123456",
)

PUBLIC_DATA_FILES = {
    ".gitkeep",
    "ai.local.example.json",
    "ark_char_library.json",
    "char_presets.json",
    "char_tag_groups.json",
    "char_tag_index.json",
    "danbooru_arknights.json",
    "danbooru_creature.json",
    "danbooru_recognition.json",
    "danbooru_style_tags.json",
    "nai_token.local.example.json",
    "pixiv_accounts.local.example.json",
    "pixiv_launch.sample.json",
    "post_pipeline.sample.json",
    "sanitize_blocklist.json",
    "seed_manifest.json",
    "tag_dict.json",
}

PRIVATE_ROOTS = {
    "backups": "backup-data",
    "cases": "case-state",
    "logs": "logs",
    "output": "generated-output",
    "release": "release-artifact",
    "reports": "local-reports",
    "runtime": "bundled-runtime",
    "update": "update-state",
    "work": "work-state",
}
PRIVATE_DATA_DIRS = {
    ".cache",
    "_trash",
    "cache",
    "char_swap_audit",
    "galleries",
    "generated",
    "images",
    "pixiv_chrome_profile",
    "pixiv_chrome_profiles",
    "pixiv_nai_staging",
    "studio_drafts",
}
BACKUP_NAME_RE = re.compile(
    r"(?:\.bak(?:[-.].*)?|\.backup(?:[-.].*)?|\.old|\.orig|~)$", re.IGNORECASE
)

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
}
TEXT_SUFFIXES = {
    "",
    ".bat",
    ".cfg",
    ".conf",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".txt",
    ".vbs",
    ".xml",
    ".yaml",
    ".yml",
}
MAX_TEXT_BYTES = 20 * 1024 * 1024
NO_CONTENT_PREFIXES = (
    "runtime/",
    "data/.cache/",
    "data/cache/",
    "data/galleries/",
    "data/generated/",
    "data/images/",
    "data/pixiv_chrome_profile/",
    "data/pixiv_chrome_profiles/",
    "data/pixiv_nai_staging/",
    "data/studio_drafts/",
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def _canonical(path: Path) -> Path:
    return Path(os.path.normcase(os.path.realpath(os.fspath(path))))


def _relative(path: Path, root: Path) -> str:
    return _canonical(path).relative_to(_canonical(root)).as_posix()


def _path_policy(relative: str) -> tuple[str, str] | None:
    parts = relative.split("/")
    first = parts[0].casefold()

    if first in PRIVATE_ROOTS:
        return f"{parts[0]}/", PRIVATE_ROOTS[first]
    if first == "scripts" and len(parts) > 1 and parts[1].casefold() == "logs":
        return "scripts/logs/", "logs"
    if first.startswith("web.backup"):
        return f"{parts[0]}/", "backup-source"
    if relative.casefold() in {"config.json", ".pixiv-nai-release-stage"}:
        return relative, "local-configuration"
    if relative.casefold() == "progress.md":
        return relative, "local-work-state"
    if BACKUP_NAME_RE.search(parts[-1]):
        return relative, "backup-source"

    if first == "data":
        if len(parts) == 2 and parts[1] in PUBLIC_DATA_FILES:
            return None
        if len(parts) > 1 and parts[1].casefold() in PRIVATE_DATA_DIRS:
            return f"data/{parts[1]}/", "private-runtime-data"
        return relative, "private-runtime-data"
    return None


def should_skip(path: Path) -> bool:
    if set(path.parts) & SKIP_DIR_NAMES:
        return True
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return True
    except OSError:
        return True
    return path.suffix.casefold() not in TEXT_SUFFIXES


def git_candidate_paths(root: Path) -> list[Path]:
    """Return tracked plus non-ignored untracked files, preserving NUL-safe names."""
    worktree = Path(root)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError("--git-candidates requires a valid Git worktree")
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = worktree / relative
        try:
            _canonical(path).relative_to(_canonical(worktree))
        except ValueError as exc:
            raise RuntimeError("Git candidate escaped the worktree") from exc
        if path.is_file():
            paths.append(path)
    return paths


def scan(
    root: Path,
    patterns: tuple[str, ...] = DEFAULT_PATTERNS,
    *,
    include_path_policy: bool = True,
    candidate_paths: Iterable[Path] | None = None,
) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    path_inventory: dict[tuple[str, str], list[str]] = defaultdict(list)

    paths = root.rglob("*") if candidate_paths is None else candidate_paths
    for path in paths:
        if not path.is_file():
            continue
        relative = _relative(path, root)
        if set(Path(relative).parts) & SKIP_DIR_NAMES:
            continue

        policy = _path_policy(relative) if include_path_policy else None
        if policy is not None:
            display_path, label = policy
            try:
                size = path.stat().st_size
            except OSError:
                size = -1
            path_inventory[(display_path, label)].append(f"{relative}:{size}")
            # The path itself is already forbidden; do not open private data.
            continue
        if relative == "scripts/scan_sensitive.py":
            # Avoid treating this detector's pattern definitions as evidence.
            continue
        if relative.casefold().startswith(NO_CONTENT_PREFIXES):
            # These trees are rejected wholesale by publication policy. Opening
            # user images, browser profiles or a bundled runtime adds no value.
            continue
        if should_skip(path):
            continue

        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        for placeholder in KNOWN_TEST_PLACEHOLDERS:
            text = text.replace(placeholder, "known-test-placeholder")
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is None:
                continue
            line = text.count("\n", 0, match.start()) + 1
            label = PATTERN_LABELS.get(pattern, "custom-sensitive-pattern")
            findings.append(
                f"{relative} | type={label} | line={line} | "
                f"fingerprint=sha256:{_fingerprint(match.group(0))}"
            )

    for (display_path, label), inventory in sorted(path_inventory.items()):
        digest_input = "\n".join(sorted(inventory))
        findings.append(
            f"{display_path} | type={label} | files={len(inventory)} | "
            f"fingerprint=sha256:{_fingerprint(digest_input)}"
        )
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed on private paths and sensitive-looking literals."
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--content-only",
        action="store_true",
        help="scan text content only; publication checks should not use this option",
    )
    parser.add_argument(
        "--git-candidates",
        action="store_true",
        help="scan tracked and non-ignored untracked Git publication candidates",
    )
    parser.add_argument("--max-findings", type=int, default=200)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        candidates = git_candidate_paths(root) if args.git_candidates else None
        findings = scan(
            root,
            include_path_policy=not args.content_only,
            candidate_paths=candidates,
        )
    except RuntimeError as exc:
        print(f"Sensitive scan could not start: {exc}")
        return 2
    if findings:
        print(f"Sensitive/private publication findings: {len(findings)}")
        for finding in findings[: max(0, args.max_findings)]:
            print(finding)
        if len(findings) > args.max_findings:
            print(f"... {len(findings) - args.max_findings} additional findings omitted")
        return 1
    print("No sensitive literals or private publication paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
