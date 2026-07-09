import subprocess
import time

from mgw.settings import LOGGER

from .exceptions import ExternalCommandError


def run_command(command, *, timeout=None, cwd=None):
    start = time.monotonic()
    LOGGER.info("Running external command: %s", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )
    duration = time.monotonic() - start
    LOGGER.info(
        "Finished external command rc=%s duration=%.2fs: %s",
        result.returncode,
        duration,
        " ".join(command),
    )
    if result.returncode != 0:
        raise ExternalCommandError(
            command,
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result
