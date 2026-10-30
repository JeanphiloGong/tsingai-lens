from typing import Any

from exceptions.exceptions import ProjectException


class ServerException(ProjectException):
    def __init__(
        self,
        message: str = "The server could not complete the request.",
        data: Any = None,
    ) -> None:
        super().__init__(
            code=self.build_code(0, 0),
            message=message,
            data=data,
        )


class ResourceNotFoundException(ProjectException):
    def __init__(self, message: str = "Resource not found.", data: Any = None) -> None:
        super().__init__(code=self.build_code(2, 1), message=message, data=data)


class MethodNotAllowedException(ProjectException):
    def __init__(self) -> None:
        super().__init__(code=self.build_code(2, 2), message="Method not allowed.")


class PermissionDeniedException(ProjectException):
    def __init__(self) -> None:
        super().__init__(code=self.build_code(2, 3), message="Permission denied.")


class ResourceConflictException(ProjectException):
    def __init__(self, message: str, data: Any = None) -> None:
        super().__init__(code=self.build_code(2, 4), message=message, data=data)


class ServiceUnavailableException(ProjectException):
    def __init__(self, message: str, data: Any = None) -> None:
        super().__init__(code=self.build_code(2, 5), message=message, data=data)
