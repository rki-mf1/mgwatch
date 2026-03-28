class JobConflictError(Exception):
    """Raised when an active job already exists for the requested resource."""


class LockTimeoutError(Exception):
    """Raised when a distributed lock could not be acquired in time."""


class ExternalCommandError(Exception):
    """Raised when an external command fails."""

    def __init__(self, command, returncode, stdout="", stderr=""):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        message = (
            f"Command failed with exit code {returncode}: {' '.join(command)}. "
            f"{stderr or stdout}".strip()
        )
        super().__init__(message)
