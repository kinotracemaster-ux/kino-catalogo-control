"""Crea los grupos de roles: Operador, Supervisor, Administrador, Auditor."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from core.permissions import ROLES


class Command(BaseCommand):
    help = "Crea los grupos de roles del panel"

    def handle(self, *args, **opts):
        for role in ROLES:
            Group.objects.get_or_create(name=role)
        self.stdout.write("Roles listos: " + ", ".join(ROLES))
