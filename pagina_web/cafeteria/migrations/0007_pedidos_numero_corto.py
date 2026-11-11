import re
import secrets

from django.db import migrations, models


ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def numero_corto(usados):
    for _ in range(100):
        numero = 'PED-' + ''.join(secrets.choice(ALFABETO) for _ in range(4))
        if numero not in usados:
            usados.add(numero)
            return numero
    raise RuntimeError('No se pudo asignar un número de pedido único.')


def separar_operacion_y_numero(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        if 'pedidos' not in schema_editor.connection.introspection.table_names(cursor):
            return
        cursor.execute("SHOW COLUMNS FROM pedidos LIKE 'operacion_id'")
        if cursor.fetchone() is None:
            cursor.execute('ALTER TABLE pedidos ADD COLUMN operacion_id CHAR(32) NULL')
        cursor.execute("SHOW INDEX FROM pedidos WHERE Key_name = 'uq_pedidos_operacion_id'")
        if cursor.fetchone() is None:
            cursor.execute('CREATE UNIQUE INDEX uq_pedidos_operacion_id ON pedidos (operacion_id)')

        cursor.execute('SELECT id, numero, operacion_id FROM pedidos ORDER BY id')
        pedidos = cursor.fetchall()
        usados = {numero.upper() for _, numero, _ in pedidos}
        for pedido_id, numero, operacion_id in pedidos:
            anterior = re.fullmatch(r'PED-([0-9a-fA-F]{32})', numero)
            if anterior is None:
                continue
            if operacion_id is None:
                cursor.execute('UPDATE pedidos SET operacion_id = %s WHERE id = %s',
                               [anterior.group(1).lower(), pedido_id])
            cursor.execute('UPDATE pedidos SET numero = %s WHERE id = %s',
                           [numero_corto(usados), pedido_id])


def restaurar_numero_anterior(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SHOW COLUMNS FROM pedidos LIKE 'operacion_id'")
        if cursor.fetchone() is None:
            return
        cursor.execute('SELECT id, operacion_id FROM pedidos WHERE operacion_id IS NOT NULL')
        for pedido_id, operacion_id in cursor.fetchall():
            cursor.execute('UPDATE pedidos SET numero = %s WHERE id = %s',
                           ['PED-' + operacion_id, pedido_id])
        cursor.execute('ALTER TABLE pedidos DROP INDEX uq_pedidos_operacion_id, DROP COLUMN operacion_id')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0006_sesiones_movil')]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(
                separar_operacion_y_numero, restaurar_numero_anterior)],
            state_operations=[migrations.AddField(
                model_name='pedidos', name='operacion_id',
                field=models.UUIDField(blank=True, null=True, unique=True))],
        ),
    ]
