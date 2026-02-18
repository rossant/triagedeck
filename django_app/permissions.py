from __future__ import annotations

from dataclasses import dataclass

from django.http import Http404

from django_app.models import ProjectMembership, Role


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    email: str


def require_auth(request) -> AuthContext:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionError("unauthorized")
    return AuthContext(user_id=user.id, email=getattr(user, "email", ""))


def project_role_or_404(project_id, user_id: int) -> str:
    role = (
        ProjectMembership.objects.filter(project_id=project_id, user_id=user_id)
        .values_list("role", flat=True)
        .first()
    )
    if role is None:
        raise Http404
    return role


def can_write_events(role: str) -> bool:
    return role in {Role.ADMIN, Role.REVIEWER}
