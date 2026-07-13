class JobConflictError(Exception):
    """Raised when an active job already exists for the requested resource."""


class LockTimeoutError(Exception):
    """Raised when a distributed lock could not be acquired in time."""


class ExternalCommandError(Exception):
    """Raised when an external command fails."""

    def __init__(self, command, returncode, stdout="", stderr=""):
        self.command = command
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""
        self.stdout_length = len(stdout or "")
        self.stderr_length = len(stderr or "")
        executable = command[0] if command else "<empty>"
        output = self._summarize_output(stdout, stderr)
        message = (
            f"Command failed with exit code {returncode}: executable={executable}. "
            f"{output}".strip()
        )
        super().__init__(message)

    def _summarize_output(self, stdout, stderr):
        output = stderr or stdout
        if output is None or output == "":
            return "No command output captured."
        stream = "stderr" if stderr else "stdout"
        return (
            f"{stream} captured {len(output)} characters; "
            "content redacted from stored error details."
        )
