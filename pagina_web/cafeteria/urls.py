from django.urls import path
from .views.acceso import AccesoView, DashboardView, SalirView, raiz
from .views.usuarios import guardar_usuario, lista_usuarios
from .views.auditoria import lista_auditoria
from .views.pedidos import lista_pedidos, actualizar_pedido
from .views.reportes import inicio_reportes, tabla_reporte
from .views.configuracion import configuracion_horario
from .views.pos import (punto_venta, abrir_apertura, buscar_productos, cotizar_venta, cobrar_venta,
    verificar_cierre, cerrar_apertura, pedidos_para_cobrar, detalle_pedido, atender_pedido, factura_venta)
from .views.catalogo import lista_catalogo, guardar_categoria, guardar_producto, guardar_movimiento, producto_info, buscar_producto_movimiento

urlpatterns = [
    path('', raiz, name='inicio'),
    path('login/', AccesoView.as_view(), name='login'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('logout/', SalirView.as_view(), name='logout'),
    path('usuarios/', lista_usuarios, name='usuarios_lista'),
    path('usuarios/nuevo/', guardar_usuario, name='usuarios_crear'),
    path('usuarios/<int:pk>/editar/', guardar_usuario, name='usuarios_editar'),
    path('auditoria/', lista_auditoria, name='auditoria_lista'),
    path('pedidos/', lista_pedidos, name='pedidos_lista'),
    path('pedidos/<int:pk>/estado/', actualizar_pedido, name='pedidos_estado'),
    path('reportes/', inicio_reportes, name='reportes_inicio'),
    path('reportes/<str:tipo>/', tabla_reporte, name='reportes_tabla'),
    path('configuracion/', configuracion_horario, name='configuracion_horario'),
    path('pos/', punto_venta, name='pos_inicio'),
    path('pos/apertura/', abrir_apertura, name='pos_abrir'),
    path('pos/productos/', buscar_productos, name='pos_productos'),
    path('pos/cotizar/', cotizar_venta, name='pos_cotizar'),
    path('pos/venta/', cobrar_venta, name='pos_cobrar'),
    path('pos/pedidos/', pedidos_para_cobrar, name='pos_pedidos'),
    path('pos/pedidos/<int:pk>/resumen/', detalle_pedido, name='pos_pedido_resumen'),
    path('pos/pedidos/atender/', atender_pedido, name='pos_pedido_atender'),
    path('pos/facturas/<str:numero>/', factura_venta, name='pos_factura'),
    path('pos/cierre/verificar/', verificar_cierre, name='pos_verificar_cierre'),
    path('pos/cierre/', cerrar_apertura, name='pos_cerrar'),
    path('productos/', lista_catalogo, {'tipo':'productos'}, name='productos_lista'),
    path('productos/nuevo/', guardar_producto, name='productos_crear'),
    path('productos/<int:pk>/editar/', guardar_producto, name='productos_editar'),
    path('categorias/', lista_catalogo, {'tipo':'categorias'}, name='categorias_lista'),
    path('categorias/nueva/', guardar_categoria, name='categorias_crear'),
    path('categorias/<int:pk>/editar/', guardar_categoria, name='categorias_editar'),
    path('inventario/', lista_catalogo, {'tipo':'inventario'}, name='inventario_lista'),
    path('inventario/nuevo/', guardar_movimiento, name='inventario_crear'),
    path('inventario/producto-info/', producto_info, name='inventario_producto_info'),
    path('inventario/buscar-producto/', buscar_producto_movimiento, name='inventario_producto_buscar'),
]
