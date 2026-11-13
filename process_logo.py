"""Prepare Modish Enterprises brand logo assets for the HRMS app."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run([sys.executable, os.path.join(ROOT, "make_logo_assets.py")], cwd=ROOT)
if r.returncode != 0:
    raise SystemExit(f"make_logo_assets failed with code {r.returncode}")
print("process_logo completed successfully.")
