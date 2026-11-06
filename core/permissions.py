"""Roles (sección 12). Cada rol incluye los permisos de los anteriores."""
from functools import wraps

from django.core.exceptions import PermissionDenied

ROLES = ["Auditor", "Operador", "Supervisor", "Administrador"]
LEVEL = {"Auditor": 0, "Operador": 1, "Supervisor": 2, "Administrador": 3}


def user_level(user):
    if not user.is_authenticated:
        return -1
    if user.is_superuser:
        return 3
    return max((LEVEL.get(g.name, -1) for g in user.groups.all()), default=-1)


def has_role(user, role):
    return user_level(user) >= LEVEL[role]


def role_required(role):
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, role):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return deco
