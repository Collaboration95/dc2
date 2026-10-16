class ProcessingError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class TaskBindingError(ValueError):
    """The worker itself is unusable (reused or missing task name), whatever the message."""
