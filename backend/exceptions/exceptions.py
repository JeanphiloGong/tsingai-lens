from typing import Any


class ProjectException(Exception):
    PROJECT_NUMBER = 20

    @classmethod
    def build_code(cls, module_number: int, sequence: int) -> int:
        return cls.PROJECT_NUMBER * 10000 + module_number * 100 + sequence

    def __init__(self, *, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data
