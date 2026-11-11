import io
import json
import re
import uuid

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers

from ..auditoria import registrar_evento
from ..forms.catalogo import CategoriaForm, MovimientoForm, ProductoForm
from ..inventario import registrar_movimiento
from ..models import Auditoria, Categorias, MovimientosInventario, Productos, Usuarios
from ..web import es_peticion_htmx, solo_administradores


CATALOGOS = {
    'productos': ('Productos', 'Administra los productos y su disponibilidad.', 'Nuevo producto'),
    'categorias': ('Categorías', 'Organiza los productos de tu cafetería.', 'Nueva categoría'),
    'inventario': ('Inventario', 'Consulta existencias y registra entradas o salidas.', 'Registrar movimiento'),
}


def contexto_catalogo(tipo):
    titulo, descripcion, boton = CATALOGOS[tipo]
    return {'tipo_modulo':tipo, 'titulo':titulo, 'descripcion_pagina':descripcion, 'boton_nuevo':boton,
            'url_lista':reverse(f'{tipo}_lista'), 'url_nuevo':reverse(f'{tipo}_crear')}


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_GET
def lista_catalogo(request, tipo):
    if tipo not in CATALOGOS:
        raise Http404
    datos = contexto_catalogo(tipo)
    consulta = request.GET.get('q', '').strip()[:150]
    estado = request.GET.get('estado', '')
    categoria = request.GET.get('categoria', '')
    categoria = categoria if categoria.isascii() and categoria.isdigit() and len(categoria) <= 10 else ''
    vista = 'movimientos' if tipo == 'inventario' and request.GET.get('vista') == 'movimientos' else 'stock'
    if tipo == 'categorias':
        registros = Categorias.objects.annotate(total_productos=Count('productos')).order_by('nombre', 'id')
        if consulta:
            registros = registros.filter(nombre__icontains=consulta)
    elif vista == 'movimientos':
        registros = MovimientosInventario.objects.select_related('producto', 'usuario').order_by('-creado_en', '-id')
        if consulta:
            registros = registros.filter(Q(producto__nombre__icontains=consulta) | Q(producto__codigo__icontains=consulta) | Q(usuario__nombre__icontains=consulta))
        clases = dict(MovimientosInventario._meta.get_field('tipo').choices)
        if estado in clases:
            registros = registros.filter(tipo=estado)
        datos['tipos_movimiento'] = clases.items()
    else:
        registros = Productos.objects.select_related('categoria').order_by('nombre', 'id')
        if consulta:
            registros = registros.filter(Q(nombre__icontains=consulta) | Q(codigo__icontains=consulta))
        if categoria:
            registros = registros.filter(categoria_id=int(categoria))
        if tipo == 'inventario':
            if estado == 'bajo':
                registros = registros.filter(stock__lte=F('stock_minimo'))
            elif estado == 'agotado':
                registros = registros.filter(stock=0)
        else:
            venta = request.GET.get('venta', '')
            if venta == 'habilitado':
                registros = registros.filter(activo=True, disponible_para_venta=True, categoria__activo=True)
            elif venta == 'pausado':
                registros = registros.filter(Q(activo=False) | Q(disponible_para_venta=False) | Q(categoria__activo=False))
            datos['filtro_venta'] = venta
    if tipo in ('productos', 'categorias') and estado in ('activo', 'inactivo'):
        registros = registros.filter(activo=estado == 'activo')
    datos.update(page_obj=Paginator(registros, 15).get_page(request.GET.get('page')), consulta=consulta,
        filtro_estado=estado, filtro_categoria=categoria, vista=vista,
        categorias=Categorias.objects.order_by('nombre'),
        hay_filtros=bool(consulta or estado or categoria or datos.get('filtro_venta')))
    plantilla = 'cafeteria/catalogo/_listado.html' if es_peticion_htmx(request) else 'cafeteria/catalogo/lista.html'
    return render(request, plantilla, datos)


def validar_actor(usuario):
    if not Usuarios.objects.filter(pk=usuario.pk, rol='administrador', habilitado=True).exists():
        raise PermissionDenied


def exito(request, tipo, mensaje):
    if es_peticion_htmx(request):
        return HttpResponse(status=204, headers={'HX-Trigger':json.dumps({'catalogoGuardado':{'mensaje':mensaje}})})
    messages.success(request, mensaje)
    return redirect(f'{tipo}_lista')


def mostrar_formulario(request, tipo, form, objeto=None, producto=None):
    datos = contexto_catalogo(tipo)
    es_nuevo = request.resolver_match.kwargs.get('pk') is None
    titulo = datos['boton_nuevo'] if es_nuevo else ('Editar producto' if tipo == 'productos' else 'Editar categoría')
    datos.update(form=form, objeto=objeto, es_nuevo=es_nuevo, titulo_formulario=titulo,
                 es_modal=es_peticion_htmx(request), producto_seleccionado=producto)
    plantilla = 'cafeteria/catalogo/_formulario.html' if datos['es_modal'] else 'cafeteria/catalogo/formulario.html'
    return render(request, plantilla, datos)


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_http_methods(['GET', 'POST'])
def guardar_categoria(request, pk=None):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                validar_actor(request.user)
                objeto = get_object_or_404(Categorias.objects.select_for_update(), pk=pk) if pk else Categorias()
                anterior = {'nombre':objeto.nombre, 'activo':objeto.activo} if pk else None
                form = CategoriaForm(request.POST, instance=objeto)
                if form.is_valid():
                    objeto = form.save()
                    nuevo = {'nombre':objeto.nombre, 'activo':objeto.activo}
                    if anterior != nuevo:
                        baja = anterior and anterior['activo'] and not nuevo['activo']
                        accion = Auditoria.Accion.ANADIDO if not pk else Auditoria.Accion.ELIMINADO_DESACTIVADO if baja else Auditoria.Accion.EDITADO
                        descripcion = 'Se añadió una categoría.' if not pk else 'Se desactivó una categoría.' if baja else 'Se cambió información de una categoría.'
                        registrar_evento(usuario=request.user, accion=accion, modulo=Auditoria.Modulo.CATEGORIAS,
                            entidad='categorias', registro_id=objeto.pk, descripcion=descripcion, anterior=anterior, nuevo=nuevo)
                    return exito(request, 'categorias', 'Categoría guardada correctamente.')
        except IntegrityError:
            form.add_error('nombre', 'Ya existe una categoría con ese nombre.')
    else:
        objeto = get_object_or_404(Categorias, pk=pk) if pk else Categorias()
        form = CategoriaForm(instance=objeto)
    return mostrar_formulario(request, 'categorias', form, objeto)


def datos_producto(producto):
    return {**{campo:getattr(producto, campo) for campo in (
        'nombre','codigo','categoria_id','fotografia','stock_minimo','disponible_para_venta','activo')},
        'descripcion':producto.descripcion or '', 'precio':str(producto.precio)}


def guardar_foto(imagen):
    from PIL import Image, ImageOps
    imagen.seek(0)
    with Image.open(imagen) as original:
        foto = ImageOps.exif_transpose(original)
        foto.thumbnail((1200, 1200))
        foto = foto.convert('RGBA' if 'A' in foto.getbands() else 'RGB')
        contenido = io.BytesIO()
        foto.save(contenido, format='WEBP', quality=85)
    nombre = default_storage.save(f'productos/{uuid.uuid4().hex}.webp', ContentFile(contenido.getvalue()))
    return settings.MEDIA_URL + nombre


def quitar_foto(ruta):
    nombre = ruta.removeprefix(settings.MEDIA_URL)
    if re.fullmatch(r'productos/[a-f0-9]{32}\.webp', nombre):
        default_storage.delete(nombre)


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_http_methods(['GET', 'POST'])
def guardar_producto(request, pk=None):
    archivo_nuevo = None
    if request.method == 'POST':
        try:
            with transaction.atomic():
                validar_actor(request.user)
                # Mismo orden de bloqueos para editar categorías y productos.
                list(Categorias.objects.select_for_update().order_by('pk'))
                objeto = get_object_or_404(Productos.objects.select_for_update(), pk=pk) if pk else Productos(stock=0, fotografia='')
                anterior = datos_producto(objeto) if pk else None
                foto_anterior = objeto.fotografia
                form = ProductoForm(request.POST, request.FILES, instance=objeto)
                if form.is_valid():
                    objeto = form.save(commit=False)
                    if form.cleaned_data.get('imagen'):
                        archivo_nuevo = guardar_foto(form.cleaned_data['imagen'])
                        objeto.fotografia = archivo_nuevo
                    elif form.cleaned_data.get('quitar_imagen'):
                        objeto.fotografia = ''
                    objeto.save()
                    nuevo = datos_producto(objeto)
                    if anterior != nuevo:
                        baja = anterior and ((anterior['activo'] and not nuevo['activo']) or
                            (anterior['disponible_para_venta'] and not nuevo['disponible_para_venta']))
                        accion = Auditoria.Accion.ANADIDO if not pk else Auditoria.Accion.ELIMINADO_DESACTIVADO if baja else Auditoria.Accion.EDITADO
                        descripcion = 'Se añadió un producto.' if not pk else 'Se deshabilitó un producto.' if baja else 'Se cambió información de un producto.'
                        registrar_evento(usuario=request.user, accion=accion, modulo=Auditoria.Modulo.PRODUCTOS,
                            entidad='productos', registro_id=objeto.pk, descripcion=descripcion, anterior=anterior, nuevo=nuevo)
                    if foto_anterior and foto_anterior != objeto.fotografia:
                        transaction.on_commit(lambda ruta=foto_anterior: quitar_foto(ruta), robust=True)
                    return exito(request, 'productos', 'Producto guardado correctamente.')
        except (IntegrityError, OSError, ValueError) as error:
            if archivo_nuevo:
                quitar_foto(archivo_nuevo)
            form.add_error(None, 'El código ya está en uso.' if isinstance(error, IntegrityError) else 'No se pudo guardar la fotografía. Prueba con otra imagen.')
        except Exception:
            if archivo_nuevo:
                quitar_foto(archivo_nuevo)
            raise
    else:
        objeto = get_object_or_404(Productos, pk=pk) if pk else Productos(stock=0, fotografia='')
        form = ProductoForm(instance=objeto)
    return mostrar_formulario(request, 'productos', form, objeto)


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_http_methods(['GET', 'POST'])
def guardar_movimiento(request):
    seleccionado = request.POST.get('producto') if request.method == 'POST' else request.GET.get('producto')
    producto = Productos.objects.filter(pk=seleccionado).first() if seleccionado and seleccionado.isascii() and seleccionado.isdigit() and len(seleccionado) <= 10 else None
    if request.method == 'POST':
        form = MovimientoForm(request.POST, producto=producto)
        if form.is_valid():
            try:
                _, creado = registrar_movimiento(usuario=request.user, producto_id=form.cleaned_data['producto'].pk,
                    **{campo:form.cleaned_data[campo] for campo in ('operacion','cantidad','motivo','operacion_id')})
                return exito(request, 'inventario', 'Movimiento registrado correctamente.' if creado else 'Este movimiento ya estaba registrado.')
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:
                form.add_error(None, 'Esta solicitud ya se procesó. Consulta el historial antes de registrar otra.')
    else:
        form = MovimientoForm(producto=producto)
    return mostrar_formulario(request, 'inventario', form, producto=producto)


@solo_administradores
@require_GET
def producto_info(request):
    seleccionado = request.GET.get('producto', '')
    producto = Productos.objects.filter(pk=seleccionado).first() if seleccionado.isascii() and seleccionado.isdigit() and len(seleccionado) <= 10 else None
    return render(request, 'cafeteria/catalogo/_stock_info.html', {'producto_seleccionado':producto})


@solo_administradores
@require_GET
def buscar_producto_movimiento(request):
    consulta = request.GET.get('producto_busqueda', '').strip()[:150]
    productos = Productos.objects.filter(Q(nombre__icontains=consulta) | Q(codigo__icontains=consulta)).order_by('nombre', 'codigo', 'pk')[:20] if consulta else []
    return render(request, 'cafeteria/catalogo/_productos_busqueda.html', {'productos_encontrados':productos, 'consulta_producto':consulta})
