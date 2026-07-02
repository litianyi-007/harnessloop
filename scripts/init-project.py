#!/usr/bin/env python3
"""Thin wrapper: initialize Harnessloop files in a target project."""

import runpy
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "plugins" / "harnessloop" / "skills" / "harnessloop-loop" / "scripts" / "init_project.py"
)

if not SCRIPT.exists():
    sys.exit(f"Missing Harnessloop init script: {SCRIPT}")

sys.argv[0] = str(SCRIPT)
runpy.run_path(str(SCRIPT), run_name="__main__")
