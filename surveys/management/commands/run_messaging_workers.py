from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the local forms messaging workers required for orders integration"

    def handle(self, *args, **options):
        python_bin = Path(sys.executable)
        manage_py = Path.cwd() / "manage.py"

        workers = [
            ("order-consumer", [str(python_bin), str(manage_py), "consume_order_events"]),
            ("outbox-relay", [str(python_bin), str(manage_py), "outbox_relay"]),
        ]

        processes: list[tuple[str, subprocess.Popen[str]]] = []
        stopping = False

        def _stop_all() -> None:
            nonlocal stopping
            if stopping:
                return
            stopping = True
            for _name, proc in processes:
                if proc.poll() is None:
                    proc.terminate()

        def _handle_signal(signum, frame) -> None:
            _stop_all()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            for name, cmd in workers:
                proc = subprocess.Popen(cmd)
                processes.append((name, proc))
                self.stdout.write(self.style.SUCCESS(f"Started {name} (pid={proc.pid})"))

            while True:
                for name, proc in processes:
                    code = proc.poll()
                    if code is not None:
                        self.stderr.write(self.style.ERROR(f"{name} exited with code {code}"))
                        _stop_all()
                        for other_name, other_proc in processes:
                            if other_proc is proc:
                                continue
                            if other_proc.poll() is None:
                                other_proc.wait(timeout=5)
                        raise SystemExit(code)
                time.sleep(0.5)
        finally:
            _stop_all()
            for _name, proc in processes:
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
