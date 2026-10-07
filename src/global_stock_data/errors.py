"""Stable, redacted machine-readable failures."""

from typing import Any


class DataError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "error": {"code": self.code, "message": str(self), "status": self.status},
        }


def require(condition: bool, message: str, code: str = "schema") -> None:
    if not condition:
        raise DataError(code, message)
