from datetime import datetime, timezone

class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status

def now():
    """Naive UTC timestamp used for all stored datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
