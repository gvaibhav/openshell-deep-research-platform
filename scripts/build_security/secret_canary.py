"""Fail CI unless Trivy rejects an ephemeral synthetic secret canary."""

from __future__ import annotations

import argparse
import json
import secrets
import string
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trivy", default="trivy")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="secret-canary-") as directory:
        root = Path(directory)
        target = root / "input"
        target.mkdir()
        fake = "ghp_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))
        (target / "canary.txt").write_text(f"github_token={fake}\n", encoding="utf-8")
        report = root / "result.json"
        try:
            result = subprocess.run(
                [args.trivy, "fs", "--scanners", "secret", "--ignorefile", "",
                 "--format", "json", "--output", str(report), "--exit-code", "1", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            print("secret canary blocked: Trivy unavailable", file=sys.stderr)
            return 1
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            findings = sum(len(item.get("Secrets") or []) for item in data.get("Results") or [])
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            findings = 0
        if result.returncode != 1 or findings < 1:
            print("secret canary blocked: scanner did not reject the synthetic token", file=sys.stderr)
            return 1
    print("synthetic secret canary rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
