from __future__ import annotations

from fastapi import HTTPException, status


def error(status_code: int, code: str, message: str, details: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": details or {}}},
    )


def unauthorized() -> HTTPException:
    return error(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Authentication required")


def forbidden() -> HTTPException:
    return error(
        status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission for this action"
    )


def not_found() -> HTTPException:
    return error(status.HTTP_404_NOT_FOUND, "not_found", "Resource not found")


def bad_request(code: str, message: str, details: dict | None = None) -> HTTPException:
    return error(status.HTTP_400_BAD_REQUEST, code, message, details)


def validation_error(code: str, message: str, details: dict | None = None) -> HTTPException:
    return error(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message, details)


def conflict(code: str, message: str, details: dict | None = None) -> HTTPException:
    return error(status.HTTP_409_CONFLICT, code, message, details)


def gone(code: str, message: str, details: dict | None = None) -> HTTPException:
    return error(status.HTTP_410_GONE, code, message, details)
