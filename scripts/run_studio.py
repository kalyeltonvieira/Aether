#!/usr/bin/env python3
"""Start AETHER API and/or Studio locally; Ctrl+C shuts down both children."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def stop_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    try:
        if os.name == "nt":
            child.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            child.send_signal(signal.SIGINT)
        child.wait(timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--api-only", action="store_true")
    group.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".aether-data")
    parser.add_argument("--seed-fixture", action="store_true", help="Load explicitly labelled test data only into an empty store")
    args = parser.parse_args()
    if not all(1024 <= port <= 65535 for port in (args.api_port, args.frontend_port)):
        parser.error("ports must be in 1024..65535")
    if args.api_port == args.frontend_port:
        parser.error("API and frontend ports must be different")

    pnpm = shutil.which("pnpm")
    if not args.api_only and pnpm is None:
        parser.error("pnpm is missing; install Node.js and the version pinned in frontend/package.json")
    if not args.api_only and not (ROOT / "frontend" / "node_modules").exists():
        parser.error("frontend dependencies are missing; run pnpm --dir frontend install --frozen-lockfile")
    environment = dict(os.environ)
    environment["AETHER_API_TARGET"] = f"http://127.0.0.1:{args.api_port}"
    children = []
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        if not args.frontend_only:
            command = [sys.executable, "-m", "aether.interfaces.api", "--host", "127.0.0.1", "--port", str(args.api_port), "--data-dir", str(args.data_dir), "--auth-mode", "token"]
            if args.seed_fixture:
                command.append("--seed-fixture")
            children.append(subprocess.Popen(command, cwd=ROOT, env=environment, creationflags=creationflags))
        if not args.api_only:
            command = [pnpm, "--dir", "frontend", "dev", "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"]
            # pnpm.cmd needs cmd.exe on Windows; shell receives only known literals/validated integers.
            children.append(subprocess.Popen(command, cwd=ROOT, env=environment, creationflags=creationflags, shell=os.name == "nt"))
        print(f"Studio local: http://localhost:{args.frontend_port} | API local: http://localhost:{args.api_port}", flush=True)
        print("Autenticação obrigatória; o token de operador é gerenciado pela API, nunca pelo frontend. Ctrl+C encerra os processos.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        return next((child.returncode for child in children if child.returncode is not None), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            stop_child(child)


if __name__ == "__main__":
    raise SystemExit(main())
