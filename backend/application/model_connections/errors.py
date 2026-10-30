class ModelConnectionError(ValueError):
    """A model configuration failure with a public error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
