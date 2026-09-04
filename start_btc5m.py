import os
import subprocess
import sys
import time
import urllib.request
import webbrowser


ROOT = os.path.dirname(os.path.abspath(__file__))
HEALTH_URL = "http://127.0.0.1:8787/api/status"
DASHBOARD_URL = "http://127.0.0.1:8787"


def service_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2):
            return True
    except Exception:
        return False


def main() -> None:
    if not service_ready():
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        python_executable = sys.executable
        if os.path.basename(python_executable).lower() == "pythonw.exe":
            python_executable = os.path.join(
                os.path.dirname(python_executable), "python.exe"
            )
        subprocess.Popen(
            [python_executable, "-u", "-m", "btc5m.main", "serve"],
            cwd=ROOT,
            env=os.environ.copy(),
            creationflags=creation_flags,
        )
        for _ in range(30):
            time.sleep(0.5)
            if service_ready():
                break
        else:
            raise RuntimeError("BTC 5m service did not become ready on port 8787.")
    if os.getenv("BTC5M_NO_BROWSER") != "1":
        webbrowser.open(DASHBOARD_URL)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Unable to start BTC 5m service: {error}")
        input("Press Enter to close...")
