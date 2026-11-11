from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import make_password

from .models import Usuarios


class EmpleadosBackend(BaseBackend):
    """Solo personal habilitado; el formulario no acepta correos ni roles."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password or '@' in username:
            make_password(password or '')
            return None
        candidatos = list(Usuarios.objects.filter(
            nombre__iexact=username.strip(),
            habilitado=True,
            rol__in=('administrador', 'cajero'),
        )[:2])
        # Si hubiera nombres repetidos, nunca elegir una cuenta arbitrariamente.
        if len(candidatos) != 1:
            make_password(password)
            return None
        empleado = candidatos[0]
        return empleado if empleado.check_password(password) else None

    def get_user(self, user_id):
        return Usuarios.objects.filter(
            pk=user_id, habilitado=True, rol__in=('administrador', 'cajero'),
        ).first()
