"""Run the distributed executable from a clean directory without Python on PATH."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from companion import VERSION
parser = argparse.ArgumentParser()
parser.add_argument("--exe-path", type=Path, default=root / "dist" / "自律伴侣.exe")
args = parser.parse_args()
run_dir = root / "artifacts" / ("packaged-" + uuid.uuid4().hex[:8])
portable = run_dir / "portable"
portable.mkdir(parents=True)
exe = portable / "自律伴侣.exe"
shutil.copy2(args.exe_path.resolve(), exe)
env = os.environ.copy()
env["PATH"] = os.path.join(env.get("WINDIR", "C:\\Windows"), "System32")
for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
    env.pop(key, None)
startup = subprocess.STARTUPINFO()
startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = subprocess.SW_HIDE
options = {"cwd": portable, "env": env, "startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}
checks = []


def check(name, value):
    if not value:
        raise AssertionError(name)
    checks.append(name)


def wait_for(path, condition=lambda obj: True, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                if condition(result):
                    return result
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.1)
    raise TimeoutError(f"Waited for {path}")


def run(*args, timeout=90):
    result = subprocess.run([str(exe), *map(str, args)], timeout=timeout, **options)
    if result.returncode:
        raise RuntimeError(f"Executable exited {result.returncode}: {args}")


try:
    # A clean single-file distribution must be a 64-bit GUI PE executable.
    binary = exe.read_bytes()
    offset = struct.unpack_from("<I", binary, 0x3C)[0]
    check("Windows x64 executable", struct.unpack_from("<H", binary, offset + 4)[0] == 0x8664)
    check("GUI subsystem (no console)", struct.unpack_from("<H", binary, offset + 24 + 68)[0] == 2)
    check("Portable folder contains exe only", list(portable.iterdir()) == [exe])
    smoke = run_dir / "smoke"
    env["QT_QPA_PLATFORM"] = "offscreen"
    run("--smoke-test", "--background", "--data-dir", smoke, "--screenshot-dir", run_dir / "screenshots")
    report = json.loads((smoke / "smoke-report.json").read_text(encoding="utf-8"))
    check("Standalone UI checks without Python on PATH", report["passed"] and report["frozen"])
    # Exercise the real Windows platform plugin, with no visible helper windows.
    native = run_dir / "native-smoke"
    env["QT_QPA_PLATFORM"] = "windows"
    run("--smoke-test", "--background", "--data-dir", native, "--screenshot-dir", run_dir / "native-screenshots")
    report_native = json.loads((native / "smoke-report.json").read_text(encoding="utf-8"))
    check("Native Windows Qt UI checks", report_native["passed"] and report_native["frozen"])
    # Real inter-process locking and activation, with an independent data directory.
    instance_dir = run_dir / "single-instance"
    ready = run_dir / "primary-ready.json"
    primary = subprocess.Popen([str(exe), "--data-dir", str(instance_dir), "--background", "--quit-after", "18", "--ready-file", str(ready)], **options)
    try:
        state = wait_for(ready)
        check("Primary instance initialized", state["frozen"])
        check("Executable version matches source", state["version"] == VERSION)
        run("--data-dir", instance_dir, "--background", "--quit-after", "4", timeout=30)
        state = wait_for(ready, lambda obj: obj["activations"] >= 1)
        check("Repeated launch activates existing instance", state["activations"] == 1 and primary.poll() is None)
        check("Primary instance exits cleanly", primary.wait(timeout=30) == 0)
    finally:
        if primary.poll() is None:
            primary.terminate()
            primary.wait(timeout=10)
    # Start after the lock has been released and verify that data survive reopening.
    run("--data-dir", instance_dir, "--background", "--quit-after", "2", "--ready-file", run_dir / "reopened.json", timeout=40)
    check("Restart after exit succeeds", (run_dir / "reopened.json").exists())
    final = {"passed": True, "version": VERSION, "checks": checks, "ui_checks": len(report["checks"]), "native_ui_checks": len(report_native["checks"]),
             "exe_bytes": len(binary), "sha256": hashlib.sha256(binary).hexdigest(), "artifacts": str(run_dir)}
except Exception as exc:
    final = {"passed": False, "checks": checks, "error": str(exc), "artifacts": str(run_dir)}
    raise
finally:
    (root / "artifacts" / "packaged-report.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, indent=2))
