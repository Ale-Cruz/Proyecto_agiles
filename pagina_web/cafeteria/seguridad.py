from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import unicodedata
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import IntentosAcceso


@dataclass
class ControlIntentos:
    bloqueado: bool
    correcto: bool = False


@contextmanager
def controlar_intentos(usuario, direccion):
    normalizado = ''.join(c for c in unicodedata.normalize('NFKD', usuario.strip().casefold())
                          if not unicodedata.combining(c))
    claves = {
        salted_hmac('cafeteria.login', 'usuario:' + normalizado, algorithm='sha256').hexdigest(): settings.LOGIN_MAX_ATTEMPTS,
        salted_hmac('cafeteria.login', 'ip:' + direccion, algorithm='sha256').hexdigest(): settings.LOGIN_IP_MAX_ATTEMPTS,
    }
    clave_usuario = salted_hmac('cafeteria.login', 'usuario:' + normalizado, algorithm='sha256').hexdigest()
    ahora = timezone.now()
    with transaction.atomic():
        registros = []
        for clave in sorted(claves):
            registro, _ = IntentosAcceso.objects.select_for_update().get_or_create(clave=clave)
            if ahora >= registro.inicio_ventana + timedelta(seconds=settings.LOGIN_WINDOW_SECONDS):
                registro.fallos = 0
                registro.inicio_ventana = ahora
            registros.append(registro)
        control = ControlIntentos(any(r.fallos >= claves[r.pk] for r in registros))
        yield control
        if control.bloqueado:
            return
        for registro in registros:
            if control.correcto:
                if registro.pk == clave_usuario:
                    registro.fallos = 0
                    registro.inicio_ventana = ahora
            else:
                registro.fallos += 1
            registro.save(update_fields=['fallos', 'inicio_ventana'])


class SeguridadEmpleadosMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Deshabilitar un empleado o quitarle su rol invalida su sesion al consultar.
        if request.session.get(SESSION_KEY) and not request.user.is_authenticated:
            request.session.flush()
        response = self.get_response(request)
        # Una sesion vencida debe llevar al acceso, no insertarlo dentro del modal.
        if (request.headers.get('HX-Request') == 'true' and response.status_code in (301, 302, 303, 307, 308)
                and not request.user.is_authenticated
                and urlsplit(response.get('Location', '')).path == reverse('login')):
            response['HX-Redirect'] = response['Location']
            del response['Location']
            response.status_code = 200
            response.content = b''
        if request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store, max-age=0, must-revalidate'
        response['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response
