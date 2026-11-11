from django.db import migrations, models


def preparar_catalogo(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    tablas = connection.introspection.table_names()
    with connection.cursor() as cursor:
        if 'categorias' in tablas:
            cursor.execute('SELECT nombre FROM categorias GROUP BY nombre HAVING COUNT(*) > 1 LIMIT 1')
            if cursor.fetchone():
                raise RuntimeError('Hay categorías con nombres duplicados; renómbralas antes de migrar.')
            indices = connection.introspection.get_constraints(cursor, 'categorias')
            if not any(indice['unique'] and indice['columns'] == ['nombre'] for indice in indices.values()):
                cursor.execute('CREATE UNIQUE INDEX uk_categorias_nombre ON categorias (nombre)')
        if 'movimientos_inventario' in tablas:
            columnas = {col.name for col in connection.introspection.get_table_description(cursor, 'movimientos_inventario')}
            if 'operacion_id' not in columnas:
                cursor.execute('ALTER TABLE movimientos_inventario ADD COLUMN operacion_id CHAR(32) NULL DEFAULT NULL')
            indices = connection.introspection.get_constraints(cursor, 'movimientos_inventario')
            if not any(indice['unique'] and indice['columns'] == ['operacion_id'] for indice in indices.values()):
                cursor.execute('CREATE UNIQUE INDEX uk_inventario_operacion ON movimientos_inventario (operacion_id)')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0003_auditoria_modulo')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(preparar_catalogo)],
        state_operations=[
            migrations.AlterField('categorias', 'nombre', models.CharField(max_length=100, unique=True)),
            migrations.AddField('movimientosinventario', 'operacion_id', models.UUIDField(blank=True, null=True, unique=True)),
        ],
    )]
