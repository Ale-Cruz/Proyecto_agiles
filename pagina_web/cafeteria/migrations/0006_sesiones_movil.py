from django.db import migrations


def preparar_sesiones(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    with connection.cursor() as cursor:
        if 'usuarios' not in connection.introspection.table_names(cursor):
            return
        # Hereda exactamente el tipo de la PK compartida, también en instalaciones importadas.
        cursor.execute("SHOW COLUMNS FROM usuarios LIKE 'id'")
        id_type = cursor.fetchone()[1]
        cursor.execute(f'''CREATE TABLE IF NOT EXISTS sesiones_movil (
            token_hash CHAR(64) NOT NULL PRIMARY KEY,
            usuario_id {id_type} NOT NULL,
            creado_en DATETIME NOT NULL,
            expira_en DATETIME NULL,
            INDEX idx_sesion_usuario (usuario_id),
            CONSTRAINT fk_sesion_movil_usuario FOREIGN KEY (usuario_id)
                REFERENCES usuarios(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        # Conserva las sesiones anteriores al pasar al esquema de varios teléfonos.
        cursor.execute('''INSERT IGNORE INTO sesiones_movil (token_hash,usuario_id,creado_en,expira_en)
            SELECT token_sesion_hash,id,UTC_TIMESTAMP(),sesion_expira_en FROM usuarios
            WHERE rol='estudiante' AND CHAR_LENGTH(token_sesion_hash)=64''')
        cursor.execute("""UPDATE usuarios SET token_sesion_hash=NULL,sesion_expira_en=NULL
                          WHERE rol='estudiante'""")


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('cafeteria', '0005_movil_codigos_horarios')]
    operations = [migrations.RunPython(preparar_sesiones)]
