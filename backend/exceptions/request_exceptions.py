from typing import Any

from exceptions.exceptions import ProjectException


class RequestInvalidException(ProjectException):
    def __init__(
        self, message: str = "Invalid request parameters.", data: Any = None
    ) -> None:
        super().__init__(code=self.build_code(1, 0), message=message, data=data)
