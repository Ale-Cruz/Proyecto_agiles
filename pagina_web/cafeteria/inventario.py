from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .auditoria import registrar_evento
from .forms.catalogo import MAX_STOCK
from .models import Auditoria, MovimientosInventario, Productos, Usuarios


def productos_vendibles():
    """Regla compartida para el futuro POS y los endpoints de pedidos."""
    return Productos.objects.filter(activo=True, disponible_para_venta=True, categoria__activo=True, stock__gt=0)


@transaction.atomic
def registrar_movimiento(*, usuario, producto_id, operacion, cantidad, motivo, operacion_id):
    if not Usuarios.objects.filter(pk=usuario.pk, rol='administrador', habilitado=True).exists():
        raise PermissionDenied
    if operacion not in ('entrada', 'salida') or type(cantidad) is not int or cantidad <= 0 or not motivo.strip():
        raise ValidationError('Revisa la operación, la cantidad y el motivo.')
    if operacion_id is None:
        raise ValidationError('Abre un formulario nuevo para registrar el movimiento.')
    producto = Productos.objects.select_for_update().get(pk=producto_id)
    anterior_movimiento = MovimientosInventario.objects.filter(operacion_id=operacion_id).first()
    if anterior_movimiento:
        if anterior_movimiento.producto_id != producto.pk or anterior_movimiento.usuario_id != usuario.pk:
            raise ValidationError('Esta solicitud ya fue utilizada. Abre un movimiento nuevo.')
        return anterior_movimiento, False
    anterior = producto.stock
    diferencia = cantidad if operacion == 'entrada' else -cantidad
    tipo = 'entrada' if operacion == 'entrada' else 'salida_manual'
    resultado = anterior + diferencia
    if resultado < 0:
        raise ValidationError('La salida supera el stock actual del producto.')
    if resultado > MAX_STOCK or abs(diferencia) > MAX_STOCK:
        raise ValidationError('La cantidad supera el límite permitido.')
    producto.stock = resultado
    producto.save(update_fields=['stock'])
    movimiento = MovimientosInventario.objects.create(producto=producto, usuario=usuario,
        tipo=tipo, cantidad=abs(diferencia), motivo=motivo.strip(), operacion_id=operacion_id)
    registrar_evento(usuario=usuario, accion=Auditoria.Accion.ANADIDO, modulo=Auditoria.Modulo.INVENTARIO,
        entidad='movimientos_inventario', registro_id=movimiento.pk,
        descripcion='Se registró un movimiento de inventario.', anterior={'stock':anterior},
        nuevo={'stock':resultado, 'producto_id':producto.pk, 'tipo':tipo, 'cantidad':movimiento.cantidad})
    return movimiento, True
