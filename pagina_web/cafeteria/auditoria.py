"""Registro comun de operaciones para los modulos del sistema."""
from .models import Auditoria


CAMPOS_SECRETOS = frozenset({
    'password', 'password1', 'password2', 'password_hash', 'clave', 'contrasena', 'contraseña',
    'token', 'token_sesion_hash', 'access_token', 'refresh_token', 'csrfmiddlewaretoken',
})


def sin_secretos(valor):
    if isinstance(valor, dict):
        return {clave: sin_secretos(dato) for clave, dato in valor.items()
                if str(clave).casefold() not in CAMPOS_SECRETOS}
    if isinstance(valor, (list, tuple)):
        return [sin_secretos(dato) for dato in valor]
    return valor


def registrar_evento(*, usuario, accion, modulo, entidad, registro_id, descripcion, anterior=None, nuevo=None):
    if accion not in Auditoria.Accion.values or modulo not in Auditoria.Modulo.values:
        raise ValueError('La accion y el modulo deben pertenecer al catalogo de auditoria.')
    return Auditoria.objects.create(
        usuario=usuario, accion=accion, modulo=modulo, entidad_afectada=entidad,
        registro_afectado_id=registro_id, descripcion=descripcion,
        valor_anterior=sin_secretos(anterior), valor_nuevo=sin_secretos(nuevo),
    )
