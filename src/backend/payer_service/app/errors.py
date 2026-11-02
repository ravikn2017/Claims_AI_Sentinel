class PermanentError(Exception):
    pass


class TransientError(Exception):
    pass


class DuplicateClaim(Exception):
    pass


class Conflict(Exception):
    def __init__(self, status: str | None):
        self.status = status
        super().__init__(status or "missing")


class FieldRejected(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotAllowed(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
