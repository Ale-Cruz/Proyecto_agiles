from django.db import migrations, models


def preparar_pos(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    tablas = connection.introspection.table_names()
    with connection.cursor() as cursor:
        origen = 'caja' if 'caja' in tablas else 'aperturas_caja' if 'aperturas_caja' in tablas else None
        if origen:
            if 'caja' in tablas and 'aperturas_caja' in tablas:
                raise RuntimeError('Existen caja y aperturas_caja; revisa ambas antes de continuar.')
            cursor.execute(f"SELECT COUNT(*) FROM {origen} WHERE estado='abierta'")
            if cursor.fetchone()[0] > 1:
                raise RuntimeError('Hay varias aperturas abiertas. Debe quedar solo una antes de migrar.')
            if origen == 'caja':
                # MySQL conserva las filas y actualiza las referencias de las FK.
                cursor.execute('RENAME TABLE caja TO aperturas_caja')
            columnas = {col.name for col in connection.introspection.get_table_description(cursor, 'aperturas_caja')}
            if 'activa_unica' not in columnas:
                cursor.execute("ALTER TABLE aperturas_caja ADD COLUMN activa_unica INT UNSIGNED GENERATED ALWAYS AS (CASE WHEN estado='abierta' THEN 1 ELSE NULL END) STORED")
            indices = connection.introspection.get_constraints(cursor, 'aperturas_caja')
            if not any(v['unique'] and v['columns'] == ['activa_unica'] for v in indices.values()):
                cursor.execute('CREATE UNIQUE INDEX uk_apertura_unica ON aperturas_caja (activa_unica)')
        if 'ventas' in tablas:
            columnas = {col.name for col in connection.introspection.get_table_description(cursor, 'ventas')}
            if 'operacion_id' not in columnas:
                cursor.execute('ALTER TABLE ventas ADD COLUMN operacion_id CHAR(32) NULL')
            indices = connection.introspection.get_constraints(cursor, 'ventas')
            if not any(v['unique'] and v['columns'] == ['operacion_id'] for v in indices.values()):
                cursor.execute('CREATE UNIQUE INDEX uk_venta_operacion ON ventas (operacion_id)')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0007_pedidos_numero_corto')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(preparar_pos)],
        state_operations=[
            migrations.AlterModelTable(name='caja', table='aperturas_caja'),
            migrations.AddField(model_name='caja', name='activa_unica', field=models.GeneratedField(
                expression=models.Case(models.When(estado='abierta', then=models.Value(1)), default=models.Value(None), output_field=models.PositiveIntegerField()),
                output_field=models.PositiveIntegerField(), db_persist=True, unique=True, null=True)),
            migrations.AddField(model_name='ventas', name='operacion_id', field=models.UUIDField(blank=True, null=True, unique=True)),
        ],
    )]
