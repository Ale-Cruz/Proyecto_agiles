def panel(request):
    if not request.user.is_authenticated:
        return {}
    modulos = [
        ('sales', 'Punto de venta', 'Registra ventas y cobra pedidos.', 'orange'),
        ('box', 'Inventario', 'Organiza productos y existencias.', 'teal'),
        ('clipboard', 'Pedidos', 'Consulta y prepara los pedidos.', 'purple'),
        ('chart', 'Reportes', 'Revisa los resultados de la cafetería.', 'blue'),
    ]
    if request.user.rol == 'administrador':
        modulos += [
            ('shield', 'Auditoría', 'Consulta el historial de operaciones.', 'teal'),
            ('users', 'Usuarios', 'Gestiona los accesos del personal.', 'purple'),
            ('settings', 'Configuración', 'Define los ajustes de tu cafetería.', 'orange'),
        ]
    else:
        modulos = [modulo for modulo in modulos if modulo[0] != 'box']
    nombre_ruta = (request.resolver_match.url_name or '') if request.resolver_match else ''
    seccion = 'usuarios' if nombre_ruta.startswith('usuarios_') else 'auditoria' if nombre_ruta.startswith('auditoria_') else 'inicio'
    if nombre_ruta.startswith('pedidos_'):
        seccion = 'pedidos'
    if nombre_ruta.startswith('pos_'):
        seccion = 'pos'
    if nombre_ruta.startswith('reportes_'):
        seccion = 'reportes'
    if nombre_ruta.startswith('configuracion_'):
        seccion = 'configuracion'
    for prefijo in ('productos', 'categorias', 'inventario'):
        if nombre_ruta.startswith(prefijo + '_'):
            seccion = prefijo
    return {'modulos': modulos, 'seccion': seccion, 'inventario_abierto':seccion in ('productos','categorias','inventario')}
