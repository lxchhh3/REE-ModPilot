"""Run pytest INSIDE headless Blender: one Blender process per test file per version, each in its
own isolated profile (tools-5.2 compat.runtime) with the pinned add-ons and the modpilot package
linked in, so a crash loses one file and two runs never share state.

    python -m modpilot_host.bpytest [--blender 5.2.2] [-k EXPR] tests/bl/test_x.py ...

Exit code 0 when every file passed in every version. Logs: tools-5.2/runtime/logs/bpytest/<version>/.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from modpilot_host import tools52

BOOT = tools52.MODPILOT / "tests" / "bl" / "_boot.py"
INI = tools52.MODPILOT / "tests" / "bl" / "pytest.ini"
# Blender 5.2 only: 4.3 is out of scope (kevin, 2026-10-20)
VERSIONS = ("5.2.2",)


@dataclass
class Result:
    version: str
    file: str
    rc: int
    seconds: float
    log: Path
    summary: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def tail(self, n: int = 4000) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")[-n:]


def run_file(file: Path, version: str, extra: list[str] = (), timeout: float = 1800) -> Result:
    compat = tools52.compat()
    pins = compat.config.load_pins()
    if not tools52.BLDEPS.is_dir():
        raise FileNotFoundError(f"{tools52.BLDEPS} missing: uv pip install --target {tools52.BLDEPS} "
                                f"--python-version 3.11 pytest")
    file = Path(file).resolve()
    logs = compat.runtime.RUNTIME / "logs" / "bpytest" / version
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{file.stem}.log"
    session = compat.runtime.build_runtime(pins, modpilot_src=tools52.SRC)
    t0 = time.perf_counter()
    try:
        env = compat.runtime.blender_env(session)
        env["MODPILOT_BLDEPS"] = str(tools52.BLDEPS)
        env["MODPILOT_ADDONS"] = json.dumps([a.module for a in pins.addons])
        cmd = [str(pins.blenders[version]), "--background", "--factory-startup", "--python-exit-code", "2",
               "--python", str(BOOT), "--",
               str(file), "-c", str(INI), "--rootdir", str(file.parent), "-q", "-rfE", *extra]
        with open(log, "w", encoding="utf-8", errors="replace") as out:
            try:
                rc = subprocess.run(cmd, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=timeout,
                                    cwd=str(tools52.MODPILOT)).returncode
            except subprocess.TimeoutExpired:
                out.write(f"\nBPYTEST: timed out after {timeout} s\n")
                rc = 124
    finally:
        compat.runtime.remove_session(session)
    text = log.read_text(encoding="utf-8", errors="replace")
    summary = next((ln.strip() for ln in reversed(text.splitlines())
                    if (" passed" in ln or " failed" in ln or " error" in ln or "no tests ran" in ln)
                    and (" in " in ln)), f"no pytest summary (exit {rc})")
    return Result(version, file.as_posix(), rc, round(time.perf_counter() - t0, 1), log, summary)


def run(files, versions=VERSIONS, extra: list[str] = ()) -> list[Result]:
    return [run_file(Path(f), v, extra) for v in versions for f in files]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m modpilot_host.bpytest")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--blender", action="append", choices=VERSIONS)
    ap.add_argument("-k", dest="k")
    a = ap.parse_args(argv)
    extra = ["-k", a.k] if a.k else []
    results = run(a.files, tuple(a.blender or VERSIONS), extra)
    for r in results:
        print(f"{'OK  ' if r.ok else 'FAIL'} {r.version} {Path(r.file).name}: {r.summary} ({r.seconds} s)  log {r.log}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
