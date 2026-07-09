class JobConflictError(Exception):
    """Raised when an active job already exists for the requested resource."""


class LockTimeoutError(Exception):
    """Raised when a distributed lock could not be acquired in time."""


class ExternalCommandError(Exception):
    """Raised when an external command fails."""

    max_output_length = 1000

    def __init__(self, command, returncode, stdout="", stderr=""):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        executable = command[0] if command else "<empty>"
        output = self._summarize_output(stderr or stdout)
        message = (
            f"Command failed with exit code {returncode}: executable={executable}. "
            f"{output}".strip()
        )
        super().__init__(message)

    def _summarize_output(self, output):
        if not output:
            return "No command output captured."
        if len(output) <= self.max_output_length:
            return output
        return output[: self.max_output_length] + "... [truncated]"
