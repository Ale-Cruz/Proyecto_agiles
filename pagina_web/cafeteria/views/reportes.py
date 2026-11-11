from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import F, Prefetch, Q, Sum
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers

from ..forms.reportes import FiltrosReporteForm
from ..models import Caja, DetallesPedido, MovimientosInventario, Pedidos, Productos, Ventas
from ..pos import cantidades_apartadas, dinero
from ..web import es_peticion_htmx, solo_empleados


REPORTES = {
    'ventas':('Ventas','sales','Ventas directas y cobros de pedidos.'),
    'pedidos':('Pedidos','clipboard','Pedidos enviados y su estado.'),
    'caja':('Caja','sales','Aperturas, cierres y diferencias de efectivo.'),
    'inventario':('Inventario actual','box','Existencias físicas, apartadas y disponibles.'),
    'movimientos':('Movimientos de inventario','box','Entradas y salidas de productos.'),
}


@solo_empleados
@require_GET
def inicio_reportes(request):
    tarjetas = [{'tipo':tipo,'titulo':titulo,'icono':icono,'descripcion':descripcion,
        'url':reverse('reportes_tabla', kwargs={'tipo':tipo})} for tipo,(titulo,icono,descripcion) in REPORTES.items()]
    return render(request, 'cafeteria/reportes/inicio.html', {'tarjetas_reportes':tarjetas})


def filtrar_fechas(registros, campo, filtros):
    zona = timezone.get_current_timezone()
    if filtros.get('desde'):
        inicio = timezone.make_aware(datetime.combine(filtros['desde'], time.min), zona)
        registros = registros.filter(**{campo+'__gte':inicio})
    if filtros.get('hasta'):
        fin = timezone.make_aware(datetime.combine(filtros['hasta']+timedelta(days=1), time.min), zona)
        registros = registros.filter(**{campo+'__lt':fin})
    return registros


def registros_reporte(tipo, filtros):
    q, estado, responsable = filtros.get('q',''), filtros.get('estado',''), filtros.get('responsable','')
    if tipo == 'ventas':
        registros = Ventas.objects.select_related('cajero','pedido__estudiante').order_by('-creada_en','-pk')
        if q:
            criterio = Q(numero__icontains=q) | Q(pedido__estudiante__nombre__icontains=q)
            if q.casefold() in 'cliente general':
                criterio |= Q(pedido__isnull=True)
            registros = registros.filter(criterio)
        if responsable:
            registros = registros.filter(cajero__nombre__icontains=responsable)
        if filtros.get('origen'):
            registros = registros.filter(pedido__isnull=filtros['origen']=='presencial')
        campo_fecha = 'creada_en'
    elif tipo == 'pedidos':
        lineas = Prefetch('detallespedido_set', queryset=DetallesPedido.objects.select_related('producto').order_by('pk'), to_attr='lineas_reporte')
        registros = Pedidos.objects.select_related('estudiante','anulado_por').prefetch_related(lineas).order_by('-creado_en','-pk')
        if q:
            registros = registros.filter(Q(numero__icontains=q) | Q(estudiante__nombre__icontains=q))
        campo_fecha = 'creado_en'
    elif tipo == 'caja':
        registros = Caja.objects.select_related('abierta_por','cerrada_por').annotate(
            ventas_periodo=Sum('movimientoscaja__monto', filter=Q(movimientoscaja__tipo='ingreso_venta')),
            ingresos_extra=Sum('movimientoscaja__monto', filter=Q(movimientoscaja__tipo='ingreso_adicional')),
            salidas_efectivo=Sum('movimientoscaja__monto', filter=Q(movimientoscaja__tipo__in=['retiro','devolucion'])),
        ).order_by('-abierta_en','-pk')
        if responsable:
            registros = registros.filter(abierta_por__nombre__icontains=responsable)
        campo_fecha = 'abierta_en'
    elif tipo == 'inventario':
        registros = Productos.objects.select_related('categoria').order_by('nombre','pk')
        if q:
            registros = registros.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))
        if estado == 'agotado':
            registros = registros.filter(stock__lte=0)
        elif estado == 'bajo':
            registros = registros.filter(stock__gt=0, stock__lte=F('stock_minimo'))
        elif estado == 'normal':
            registros = registros.filter(stock__gt=F('stock_minimo'))
        if filtros.get('venta') == 'habilitado':
            registros = registros.filter(activo=True, disponible_para_venta=True, categoria__activo=True)
        elif filtros.get('venta') == 'deshabilitado':
            registros = registros.filter(Q(activo=False) | Q(disponible_para_venta=False) | Q(categoria__activo=False))
        campo_fecha = None
    else:
        registros = MovimientosInventario.objects.select_related('producto__categoria','usuario','detalle_venta__venta').order_by('-creado_en','-pk')
        if q:
            registros = registros.filter(Q(producto__nombre__icontains=q) | Q(producto__codigo__icontains=q) | Q(motivo__icontains=q))
        if responsable:
            registros = registros.filter(usuario__nombre__icontains=responsable)
        if filtros.get('tipo'):
            registros = registros.filter(tipo=filtros['tipo'])
        campo_fecha = 'creado_en'
    if filtros.get('categoria'):
        categoria = 'categoria' if tipo == 'inventario' else 'producto__categoria'
        registros = registros.filter(**{categoria:filtros['categoria']})
    if estado and tipo != 'inventario':
        registros = registros.filter(estado=estado)
    return filtrar_fechas(registros, campo_fecha, filtros) if campo_fecha else registros


@solo_empleados
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_GET
def tabla_reporte(request, tipo):
    if tipo not in REPORTES:
        raise Http404
    form = FiltrosReporteForm(request.GET, tipo=tipo)
    valido = form.is_valid()
    registros = registros_reporte(tipo, form.cleaned_data if valido else {})
    if not valido:
        registros = registros.none()
    total_cobrado = None
    if tipo == 'ventas':
        total_cobrado = dinero(registros.filter(estado='completada').aggregate(total=Sum('total'))['total'] or 0)
    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))
    filas = list(pagina.object_list)
    if tipo == 'inventario':
        apartadas = cantidades_apartadas(p.pk for p in filas)
        for producto in filas:
            producto.apartado_reporte = apartadas.get(producto.pk, 0)
            producto.disponible_reporte = max(0, producto.stock-producto.apartado_reporte)
    elif tipo == 'caja':
        for apertura in filas:
            apertura.ventas_reporte = apertura.ventas_periodo or Decimal('0')
            calculado = apertura.monto_inicial+apertura.ventas_reporte+(apertura.ingresos_extra or 0)-(apertura.salidas_efectivo or 0)
            apertura.esperado_reporte = apertura.efectivo_esperado if apertura.estado == 'cerrada' and apertura.efectivo_esperado is not None else calculado
            apertura.diferencia_reporte = apertura.efectivo_contado-apertura.esperado_reporte if apertura.efectivo_contado is not None else None
    elif tipo == 'ventas':
        for venta in filas:
            venta.cambio_reporte = venta.efectivo_recibido-venta.total
    elif tipo == 'movimientos':
        for movimiento in filas:
            movimiento.es_entrada = movimiento.tipo in ('entrada','ajuste_entrada','reversion_venta')
    pagina.object_list = filas
    contexto = {'tipo_reporte':tipo,'titulo_reporte':REPORTES[tipo][0], 'form':form,
        'page_obj':pagina, 'total_cobrado':total_cobrado,
        'url_reporte':reverse('reportes_tabla', kwargs={'tipo':tipo}),
        'tabla_reporte':'cafeteria/reportes/_'+tipo+'.html'}
    plantilla = 'cafeteria/reportes/_listado.html' if es_peticion_htmx(request) else 'cafeteria/reportes/tabla.html'
    return render(request, plantilla, contexto)
