"""Runs every test file and prints a summary. Exit code 1 if anything failed.

    python tests/run_all.py

Needs only numpy and Pillow (`pip install numpy pillow`); no pwnagotchi and no Raspberry Pi.
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
results = []
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    name = os.path.basename(path)
    start = time.time()
    run = subprocess.run([sys.executable, path], capture_output=True, text=True)
    last = [line for line in run.stdout.strip().splitlines() if "checks" in line]
    failed = [line for line in run.stdout.splitlines() if line.startswith("FAIL") or "FAILED:" in line]
    results.append((name, run.returncode, last[-1] if last else "no summary", time.time() - start))
    if run.returncode:
        print(run.stdout[-3000:])
        print(run.stderr[-2000:])
print()
for name, code, summary, took in results:
    print("%-4s %-22s %-24s %.1fs" % ("ok" if code == 0 else "FAIL", name, summary, took))
sys.exit(1 if any(code for _, code, _, _ in results) else 0)
