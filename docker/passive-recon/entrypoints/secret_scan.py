"""secret_scan entrypoint — regex-scan stdin/file paths for credentials.

Reads input from --paths (newline-separated file list) or stdin and emits
JSONL findings on stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import yaml

_PATTERNS_FILE = Path("/app/lib/secret_patterns.yaml")


def _load_patterns(path: Path = _PATTERNS_FILE) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    patterns = data.get("patterns", [])
    compiled = []
    for p in patterns:
        compiled.append({
            "name": p["name"],
            "severity": p.get("severity", "medium"),
            "regex": re.compile(p["pattern"]),
        })
    return compiled


def scan_text(text: str, source: str, patterns: list[dict]) -> Iterable[dict]:
    for p in patterns:
        for m in p["regex"].finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            yield {
                "source": source,
                "pattern": p["name"],
                "severity": p["severity"],
                "line": line_no,
                "snippet": text[max(0, m.start() - 12):m.end() + 12][:120],
            }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", help="newline-separated list of files to scan")
    ap.add_argument("--patterns-file", default=str(_PATTERNS_FILE))
    args = ap.parse_args()

    patterns = _load_patterns(Path(args.patterns_file))

    if args.paths:
        files = Path(args.paths).read_text().splitlines()
    else:
        files = ["<stdin>"]

    for src in files:
        try:
            if src == "<stdin>":
                text = sys.stdin.read()
            else:
                text = Path(src).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(json.dumps({"source": src, "error": str(exc)}), flush=True)
            continue
        for finding in scan_text(text, src, patterns):
            print(json.dumps(finding), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
