from django.db import migrations, models


ACCIONES = [('Añadido', 'Añadido'), ('Editado', 'Editado'),
            ('Eliminado/desactivado', 'Eliminado/desactivado')]
MODULOS = [(nombre, nombre) for nombre in (
    'Usuarios', 'Productos', 'Inventario', 'Categorías', 'Ventas',
    'Caja', 'Pedidos', 'Configuración', 'General',
)]


def actualizar_auditoria(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql' or 'auditoria' not in connection.introspection.table_names():
        # Las tablas del negocio son unmanaged y se importan antes de migrar la VPS.
        return
    with connection.cursor() as cursor:
        columnas = {col.name for col in connection.introspection.get_table_description(cursor, 'auditoria')}
        if 'modulo' not in columnas:
            cursor.execute("ALTER TABLE auditoria ADD COLUMN modulo VARCHAR(50) NOT NULL DEFAULT 'General' AFTER accion")
        entidades = {
            'usuarios': 'Usuarios', 'productos': 'Productos', 'categorias': 'Categorías',
            'movimientos_inventario': 'Inventario', 'ventas': 'Ventas', 'detalles_venta': 'Ventas',
            'caja': 'Caja', 'movimientos_caja': 'Caja', 'pedidos': 'Pedidos', 'detalles_pedido': 'Pedidos',
            'configuracion': 'Configuración', 'horarios_pedidos': 'Configuración',
        }
        for entidad, modulo in entidades.items():
            cursor.execute('UPDATE auditoria SET modulo = %s WHERE entidad_afectada = %s AND modulo = %s',
                           [modulo, entidad, 'General'])
        cursor.execute('''UPDATE auditoria SET accion = %s, descripcion = %s
            WHERE accion = 'editar_usuario' AND entidad_afectada = 'usuarios'
            AND JSON_UNQUOTE(JSON_EXTRACT(valor_anterior, '$.habilitado')) = 'true'
            AND JSON_UNQUOTE(JSON_EXTRACT(valor_nuevo, '$.habilitado')) = 'false' ''',
            ['Eliminado/desactivado', 'Se desactivó un usuario.'])
        for anterior, nueva, descripcion in (
            ('crear_usuario', 'Añadido', 'Se añadió un usuario.'),
            ('editar_usuario', 'Editado', 'Se cambió información de un usuario.'),
            ('desactivar_usuario', 'Eliminado/desactivado', 'Se desactivó un usuario.'),
            ('eliminar_usuario', 'Eliminado/desactivado', 'Se eliminó un usuario.'),
        ):
            cursor.execute('UPDATE auditoria SET accion = %s, descripcion = %s WHERE accion = %s AND entidad_afectada = %s',
                           [nueva, descripcion, anterior, 'usuarios'])
        indices = connection.introspection.get_constraints(cursor, 'auditoria')
        for nombre, campos in (
            ('idx_auditoria_fecha', 'creado_en DESC, id DESC'),
            ('idx_auditoria_modulo', 'modulo, creado_en DESC'),
            ('idx_auditoria_accion', 'accion, creado_en DESC'),
        ):
            if nombre not in indices:
                cursor.execute(f'CREATE INDEX {nombre} ON auditoria ({campos})')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0002_proteger_admin_principal')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(actualizar_auditoria)],
        state_operations=[
            migrations.AddField('auditoria', 'modulo', models.CharField(choices=MODULOS, default='General', max_length=50)),
            migrations.AlterField('auditoria', 'accion', models.CharField(choices=ACCIONES, max_length=100)),
            migrations.AddIndex('auditoria', models.Index(fields=['-creado_en', '-id'], name='idx_auditoria_fecha')),
            migrations.AddIndex('auditoria', models.Index(fields=['modulo', '-creado_en'], name='idx_auditoria_modulo')),
            migrations.AddIndex('auditoria', models.Index(fields=['accion', '-creado_en'], name='idx_auditoria_accion')),
        ],
    )]
