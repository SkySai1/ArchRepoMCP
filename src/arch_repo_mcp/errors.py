"""Normalized public errors for ArchRepoMCP."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable error identifiers exposed by the domain and MCP layers."""

    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    INVALID_REPOSITORY = "INVALID_REPOSITORY"
    DIRTY_WORKTREE = "DIRTY_WORKTREE"
    NON_FAST_FORWARD = "NON_FAST_FORWARD"
    GIT_ERROR = "GIT_ERROR"
    REMOTE_ERROR = "REMOTE_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    TLS_ERROR = "TLS_ERROR"


class ArchRepoError(Exception):
    """An expected failure with a stable machine-readable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        """Return an MCP-safe representation of the error."""

        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }

