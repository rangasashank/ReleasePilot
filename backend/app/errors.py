class IntegrationError(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class LeaseLost(Exception):
    pass
