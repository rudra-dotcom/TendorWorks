"""Audit measurements, render Mermaid and compile the canonical LaTeX report."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def executable(name, local):
    value = os.environ.get(name.upper()) or shutil.which(name)
    if value:
        return value
    path = ROOT / local
    if path.exists():
        return str(path)
    raise SystemExit(f"Missing {name}; see report/BUILD.md")


def main():
    subprocess.run([sys.executable, "scripts/report_assets.py"], cwd=ROOT, check=True)
    mmdc = executable("mmdc", ".cache/report-tools/node_modules/.bin/mmdc")
    tectonic = executable("tectonic", ".cache/report-tools/bin/tectonic")
    config = os.environ.get("PUPPETEER_CONFIG")
    local_config = ROOT / ".cache/report-tools/puppeteer.json"
    if not config and local_config.exists():
        config = str(local_config)
    for source in sorted((ROOT / "report/diagrams").glob("*.mmd")):
        command = [
            mmdc,
            "-i",
            str(source),
            "-o",
            str(ROOT / "report/figures" / f"{source.stem}.pdf"),
            "-b",
            "white",
        ]
        if config:
            command += ["-p", config]
        subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([tectonic, "--keep-logs", "report/FINAL_REPORT.tex"], cwd=ROOT, check=True)
    print("Compiled report/FINAL_REPORT.pdf from LaTeX; audit in report/evaluation_audit.json")


if __name__ == "__main__":
    main()
