from exceptions.exceptions import ProjectException


class TokenInvalidException(ProjectException):
    def __init__(self) -> None:
        super().__init__(
            code=self.build_code(3, 1),
            message="Authentication is required.",
            data={"code": "authentication_required"},
        )
