from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_server.db import project_membership
from fastapi_server.errors import not_found, unauthorized


@dataclass(frozen=True)
class User:
    user_id: str
    email: str


def get_user(x_user_id: str | None = Header(default=None)) -> User:
    if not x_user_id:
        raise unauthorized()
    return User(user_id=x_user_id, email=x_user_id)


def project_role_or_404(session: Session, project_id: str, user_id: str) -> str:
    role = session.execute(
        select(project_membership.c.role).where(
            project_membership.c.project_id == project_id,
            project_membership.c.user_id == user_id,
        )
    ).scalar_one_or_none()
    if role is None:
        raise not_found()
    return role
