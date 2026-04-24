"""Capture host environment for docs/evidence/env.md.

Outputs a markdown block with:
    - OS / kernel
    - Python version
    - Docker version
    - CPU cores and RAM
    - Git commit of the working tree
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        return f"(not available: {e})"


def main() -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    cpu_count = ""
    memory = ""
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                cpu_count = str(f.read().count("processor"))
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        memory = f"{kb / (1024**2):.1f} GB"
                        break
        except Exception:
            pass
    else:
        import os
        cpu_count = str(os.cpu_count() or "unknown")
        if platform.system() == "Darwin":
            memory = run(["sysctl", "-n", "hw.memsize"])
            if memory.isdigit():
                memory = f"{int(memory) / (1024**3):.1f} GB"

    print(f"# Environment snapshot")
    print()
    print(f"Captured: {now}")
    print()
    print(f"| Field | Value |")
    print(f"|---|---|")
    print(f"| OS | {platform.system()} {platform.release()} |")
    print(f"| Machine | {platform.machine()} |")
    print(f"| Python | {sys.version.split()[0]} |")
    print(f"| CPU cores | {cpu_count} |")
    print(f"| RAM | {memory} |")
    print(f"| Docker | {run(['docker', '--version'])} |")
    print(f"| Docker Compose | {run(['docker', 'compose', 'version'])} |")
    print(f"| Git commit | {run(['git', 'rev-parse', 'HEAD'])} |")
    print(f"| Git status | {run(['git', 'status', '--short']) or 'clean'} |")
    print()
    print(f"## Running containers")
    print()
    print("```")
    print(run(["docker", "compose", "ps"]))
    print("```")


if __name__ == "__main__":
    main()
