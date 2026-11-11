from django.db import migrations, models


def preparar_movil(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        if 'configuracion' in tables:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, 'configuracion')}
            if 'horarios_habilitados' not in columns:
                cursor.execute('ALTER TABLE configuracion ADD COLUMN horarios_habilitados BOOLEAN NOT NULL DEFAULT 0')
        cursor.execute('''CREATE TABLE IF NOT EXISTS codigos_verificacion_movil (
            correo VARCHAR(254) NOT NULL,
            proposito VARCHAR(20) NOT NULL,
            codigo_hash CHAR(64) NOT NULL,
            expira_en DATETIME NOT NULL,
            enviado_en DATETIME NOT NULL,
            intentos INT UNSIGNED NOT NULL DEFAULT 0,
            PRIMARY KEY (correo,proposito),
            INDEX idx_codigo_expira (expira_en),
            CONSTRAINT chk_codigo_proposito CHECK (proposito IN ('registro','recuperacion'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0004_catalogo_inventario')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(preparar_movil)],
        state_operations=[migrations.AddField('configuracion', 'horarios_habilitados', models.BooleanField(default=False))],
    )]
