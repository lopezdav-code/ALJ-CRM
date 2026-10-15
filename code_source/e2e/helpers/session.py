"""
The e2e session: throwaway stack, seed, fake HelloAsso and server, started once per run.

With pytest-xdist, the controller process owns it (e2e/conftest.py) and hands the server's URL and
environment to the workers: the emulator is seeded once, and the ports are bound once.
"""
import os
import shutil
import tempfile
from pathlib import Path

from helpers import helloasso, stack
from helpers.data import TestData
from helpers.mailpit import Mailpit


class E2ESession:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.stack_log = logs_dir / "stack.log"
        self.server_log = logs_dir / "server.log"
        self.url = None
        self.env = None
        self._temp_dirs = []
        self._stack_started = False
        self._processes = []

    def start(self) -> None:
        """Fresh emulator + Mailpit for the run (the emulator's memory grows with use, and a run must not
        reset the developer's dev data), seeded; then the fake HelloAsso and the server in dev mode."""
        stack.start_stack(self.stack_log)
        self._stack_started = True
        Mailpit().clear()   # once per run: tests then search their own e-mails (recipient + subject)

        fake_env = stack.dev_environment(self._temp_dir("alj-e2e-fake-"))
        self._spawn(stack.ServerProcess(fake_env, helloasso.FAKE_PORT, self.logs_dir / "fake-helloasso.log",
                                        app="helloasso_fake:app", app_dir="e2e/fakes", health_path="/docs",
                                        check_env=False))

        env = stack.dev_environment(self._temp_dir("alj-e2e-data-"), **helloasso.SERVER_ENV)
        stack.seed(env, self.server_log)
        data = TestData(env)
        try:
            data.save_setting("HELLOASSO_ANNUAL_CAMPAIGN", f"Event:{helloasso.COMPETITION_FORM}")
            data.fill_geocache()
        finally:
            data.close()   # before the server starts: fill_geocache used its SQLite file
        server = self._spawn(stack.ServerProcess(env, int(os.environ.get("E2E_PORT", "8090")), self.server_log))
        self.url, self.env = server.url, env

    def _temp_dir(self, prefix: str) -> Path:
        """Private ALJ_DATA_DIR (SQLite cache) of a subprocess, removed by stop()."""
        folder = Path(tempfile.mkdtemp(prefix=prefix))
        self._temp_dirs.append(folder)
        return folder

    def _spawn(self, process: stack.ServerProcess) -> stack.ServerProcess:
        process.start()
        self._processes.append(process)
        return process

    def stop(self, failed: bool) -> None:
        """Stops the servers, removes the stack (unless E2E_KEEP_STACK=1); on failure, prints the server log tail."""
        for process in reversed(self._processes):
            process.stop()
        if self._stack_started and os.environ.get("E2E_KEEP_STACK") != "1":
            stack.stop_stack(self.stack_log)
        for folder in self._temp_dirs:
            shutil.rmtree(folder, ignore_errors=True)
        if failed:
            print(f"\n--- server log (tail, full log: {self.server_log}) ---\n{stack.tail(self.server_log)}")
