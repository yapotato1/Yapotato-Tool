"""Build script: clean old builds and run PyInstaller"""
import shutil, subprocess, sys
from pathlib import Path

BASE = Path(__file__).parent

# Clean old dist and build folders
for d in BASE.glob("dist/*"):
    if d.is_dir():
        print(f"Removing {d}...")
        shutil.rmtree(d, ignore_errors=True)
for d in [BASE / "build"]:
    if d.exists():
        print(f"Removing {d}...")
        shutil.rmtree(d, ignore_errors=True)

# Run PyInstaller
spec = BASE / "YapotatoTool.spec"
python = BASE / ".venv" / "Scripts" / "python.exe"
print(f"Building with {python}...")
result = subprocess.run([str(python), "-m", "PyInstaller", str(spec)], cwd=str(BASE))
sys.exit(result.returncode)
