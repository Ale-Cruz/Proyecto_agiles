from django.db import migrations


def instalar_proteccion(connection):
    """Conservar la identidad de la cuenta inicial incluso ante DELETE/UPDATE SQL."""
    with connection.cursor() as cursor:
        cursor.execute('''CREATE TRIGGER proteger_admin_delete
            BEFORE DELETE ON usuarios FOR EACH ROW
            BEGIN
                IF OLD.id = 1 THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'La cuenta admin es permanente y no se puede eliminar.';
                END IF;
            END''')
        cursor.execute('''CREATE TRIGGER proteger_admin_update
            BEFORE UPDATE ON usuarios FOR EACH ROW
            BEGIN
                IF OLD.id = 1 AND NOT (
                    (NEW.id <=> 1)
                    AND (BINARY NEW.nombre <=> BINARY 'admin')
                    AND (NEW.rol <=> 'administrador')
                    AND (NEW.habilitado <=> 1)
                ) THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'La cuenta admin debe conservar su identidad, rol y estado habilitado.';
                END IF;
            END''')


def proteger_admin(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql' or 'usuarios' not in connection.introspection.table_names():
        # Las tablas unmanaged se importan antes de migrar una instalacion real.
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT nombre, rol, habilitado FROM usuarios WHERE id = 1')
        if cursor.fetchone() != ('admin', 'administrador', 1):
            raise RuntimeError('La cuenta inicial id=1 debe ser admin, administrador y estar habilitada.')
    instalar_proteccion(connection)


def quitar_proteccion(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('DROP TRIGGER IF EXISTS proteger_admin_delete')
            cursor.execute('DROP TRIGGER IF EXISTS proteger_admin_update')


class Migration(migrations.Migration):
    dependencies = [('cafeteria', '0001_initial')]
    operations = [migrations.RunPython(proteger_admin, quitar_proteccion)]
