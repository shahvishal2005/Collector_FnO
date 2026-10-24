# What: the quality gate: ruff, black, mypy (strict) and pytest. A change is done only if all pass.
# In: nothing. Out: exit code 0 when every step passes.
"""Run all checks."""

from __future__ import annotations

import subprocess
import sys

STEPS = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"]),
    ("black", [sys.executable, "-m", "black", "--check", "src", "scripts", "tests"]),
    ("mypy", [sys.executable, "-m", "mypy"]),
    ("pytest", [sys.executable, "-m", "pytest"]),
]


def main() -> int:
    """Run each step, stop at the first failure."""
    for name, command in STEPS:
        print(f"== {name}")
        if subprocess.run(command, check=False).returncode != 0:
            print(f"FAILED: {name}")
            return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
