class MediaError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class PeerError(Exception):
    """Safe boundary error: never contains URLs, response bodies or tokens."""

    def __init__(self, status_code: int = 503):
        self.status_code = status_code
        super().__init__("Processing request could not be confirmed")
