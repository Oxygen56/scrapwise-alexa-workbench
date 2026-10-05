"""Create a package-local environment and install the declared Python dependencies."""
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required by the pinned NumPy distribution.")
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")])
    print("Python dependencies installed. Start an independently installed Ollama with qwen2.5:7b, then run:")
    print(str(python) + " " + str(root / "run.py") + " --port 8767")


if __name__ == "__main__":
    main()
