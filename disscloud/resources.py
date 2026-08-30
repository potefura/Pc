import os
import subprocess
from pathlib import Path

SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "target",
    "vendor",
    "dist",
    ".pip",
    ".gradle",
}


def dir_size(directory: Path, cap_bytes: float = float("inf")) -> int:
    total = 0
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            names = list(current.iterdir())
        except OSError:
            continue
        for item in names:
            if item.name in SKIP_DIRS:
                continue
            try:
                if item.is_dir():
                    stack.append(item)
                else:
                    total += item.stat().st_size
                    if total > cap_bytes:
                        return total
            except OSError:
                continue
    return total


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def rss_of(pid: int | None) -> int:
    if not pid:
        return 0
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            cols = line.split('","')
            cols = [c.strip('"') for c in cols]
            mem = cols[4] if len(cols) > 4 else ""
            kb = int("".join(c for c in mem if c.isdigit()) or "0")
            return kb * 1024
        except (IndexError, ValueError, OSError):
            return 0
    try:
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8")
        pages = int(statm.split()[1])
        return pages * 4096
    except (OSError, IndexError, ValueError):
        return 0
