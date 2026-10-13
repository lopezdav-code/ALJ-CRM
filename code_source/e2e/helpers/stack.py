"""
Local dev stack used by the e2e tests: Firebase emulator + Mailpit (dev/docker-compose.yml),
fake data (dev/seed/seed_emulator.py) and the FastAPI server started as a subprocess.

The server always runs in its own process with an explicit environment built from dev/dev.env:
the pytest process is never in dev mode, and nothing here can reach a real service
(dev/check_env.py runs first, as in dev/run_server.sh).
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CODE_SOURCE = Path(__file__).resolve().parents[2]
DEV_ENV_FILE = CODE_SOURCE / "dev" / "dev.env"

FIRESTORE_URL = "http://localhost:8081/"
AUTH_URL = "http://localhost:9099/"
MAILPIT_URL = "http://localhost:8025"
STACK_SERVICES = {"Firestore emulator": FIRESTORE_URL, "Auth emulator": AUTH_URL, "Mailpit": MAILPIT_URL + "/"}


def is_up(url: str, timeout: float = 2) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True   # the service answers, even with an error status
    except (urllib.error.URLError, OSError):
        return False


def missing_services() -> list:
    return [name for name, url in STACK_SERVICES.items() if not is_up(url)]


def wait_until_up(url: str, timeout: float, process: subprocess.Popen = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"process exited with code {process.returncode} before {url} answered")
        if is_up(url, timeout=1):
            return
        time.sleep(0.25)
    raise TimeoutError(f"{url} did not answer within {timeout:.0f} s")


def read_env_file(path: Path) -> dict:
    """KEY=VALUE lines of a dev.env-style file (comments and blank lines ignored)."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def dev_environment(data_dir: Path, **overrides: str) -> dict:
    """Environment of the dev subprocesses (seed, server): dev/dev.env + a private SQLite cache.

    PYTEST_* variables are dropped: with PYTEST_CURRENT_TEST set, the server would fall back
    to MEMBER_BACKEND=drive."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.update(read_env_file(DEV_ENV_FILE))
    env.update({"ALJ_DATA_DIR": str(data_dir), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(overrides)
    return env


def run_python(args: list, env: dict, log_path: Path, timeout: float) -> None:
    """Runs a dev script from code_source/; its output goes to log_path, and to the error on failure."""
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n$ python {' '.join(args)}\n")
        log.flush()
        result = subprocess.run([sys.executable, *args], cwd=CODE_SOURCE, env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"python {' '.join(args)} failed (exit {result.returncode}):\n{tail(log_path)}")


def seed(env: dict, log_path: Path) -> None:
    """Resets the emulator (Firestore + Auth) and loads the fake data. The server must be stopped:
    the seed also deletes its SQLite cache (ALJ_DATA_DIR)."""
    run_python(["dev/seed/seed_emulator.py"], env, log_path, timeout=180)


def tail(path: Path, lines: int = 60) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


class ServerProcess:
    """uvicorn server:app in dev mode, bound to 127.0.0.1 (local_guard_middleware only accepts
    loopback Host headers, so tests use http://localhost:<port>). Also runs the fake services
    (app="helloasso_fake:app", app_dir="e2e/fakes", check_env=False)."""

    def __init__(self, env: dict, port: int, log_path: Path, app: str = "server:app", app_dir: str = "src",
                 health_path: str = "/health", check_env: bool = True):
        self.env = env
        self.port = port
        self.log_path = log_path
        self.url = f"http://localhost:{port}"
        self.app, self.app_dir, self.health_path, self.check_env = app, app_dir, health_path, check_env
        self._process = None
        self._log = None

    def start(self) -> None:
        if self.check_env:
            run_python(["dev/check_env.py"], self.env, self.log_path, timeout=60)
        self._log = open(self.log_path, "a", encoding="utf-8")
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", self.app, "--app-dir", self.app_dir,
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=CODE_SOURCE, env=self.env, stdout=self._log, stderr=subprocess.STDOUT)
        try:
            wait_until_up(self.url + self.health_path, timeout=60, process=self._process)
        except (RuntimeError, TimeoutError) as e:
            self.stop()
            raise RuntimeError(f"server did not start: {e}\n{tail(self.log_path)}") from e

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._process = None
        if self._log is not None:
            self._log.close()
            self._log = None
