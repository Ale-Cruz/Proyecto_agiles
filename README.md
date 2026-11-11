# Proyecto Ágiles · Cafetería ITCA

Sistema de cafetería acompañado de una app de pedidos móviles desarrollada en
Flutter/Dart. La web y la API móvil comparten una base de datos MySQL.

| Carpeta | Contenido |
| --- | --- |
| `pagina_web/` | Django: acceso del personal, usuarios, productos, categorías, inventario, pedidos, POS, auditoría, reportes y horario. |
| `api_movil/` | FastAPI + SQLModel: cuentas de estudiantes, correo de verificación, catálogo, carritos y pedidos. |
| `proyecto_cafeteria/` | Flutter: app de estudiantes con correo `@itca.edu.sv`. |
| `database/schema.sql` | Estructura MySQL sin usuarios, contraseñas ni datos de operación. |

## Preparación de una instalación nueva

Se necesitan MySQL, Python compatible con los archivos `requirements.txt` y
Flutter con el SDK de Android. Cada componente Python utiliza su propio entorno.

### Base de datos y web

1. Crear una base de datos vacía `sistema_pedidos` con `utf8mb4` e importar
   `database/schema.sql` desde Navicat o el cliente de MySQL. El archivo contiene
   solo la estructura; debe importarse en una base nueva.
2. Desde `pagina_web/`:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Configurar la conexión MySQL en `.env` y asignar una `DJANGO_SECRET_KEY`
   aleatoria propia. Se puede generar con:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

4. Solo en una instalación nueva, crear el administrador principal desde
   `manage.py shell`. La contraseña se solicita localmente, sin escribirla en
   archivos ni publicarla:

   ```powershell
   .\.venv\Scripts\python.exe manage.py shell
   ```

   ```python
   from getpass import getpass
   from cafeteria.models import Usuarios
   admin = Usuarios(id=1, nombre='admin', correo='admin@cafeteria.local',
                    rol='administrador', habilitado=True)
   admin.set_password(getpass('Contraseña del administrador: '))
   admin.save(force_insert=True)
   exit()
   ```

5. Aplicar las migraciones de Django:

   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate
   ```

   Los modelos de negocio utilizan tablas existentes (`managed=False`); por eso
   importar el esquema vacío es un paso previo a `migrate`. La migración de
   protección requiere que el administrador `id=1` ya exista con nombre `admin`,
   rol `administrador` y estado habilitado. Las tablas internas las crean las
   migraciones de Django.

6. Iniciar la web:

   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
   ```

### API móvil

Desde `api_movil/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configurar la misma base de datos y una `API_SECRET_KEY` aleatoria propia.
Para los códigos reales por correo, configurar Gmail SMTP con una contraseña
de aplicación en el `.env` local. Los archivos `.env` nunca se publican.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001
```

Documentación de la API: `http://127.0.0.1:8001/docs`.
Ver [api_movil/README.md](api_movil/README.md) para sus contratos y configuración.

### App Flutter

Desde `proyecto_cafeteria/`, con la API encendida y accesible desde el teléfono:

```powershell
flutter pub get
flutter run --dart-define=API_BASE_URL=http://IP_DE_LA_PC:8001/api/v1
```

El Android físico y la PC deben compartir red para una API local. El emulador
Android utiliza `10.0.2.2` para acceder a la PC. Para generar un APK de prueba:

```powershell
flutter build apk --debug --dart-define=API_BASE_URL=http://IP_DE_LA_PC:8001/api/v1
```

Ver [proyecto_cafeteria/README.md](proyecto_cafeteria/README.md).

## Reglas principales

- Los precios del catálogo incluyen IVA; el desglose no añade otro 13 %.
- Un carrito compartido por cuenta aparta productos durante cinco minutos
  fijos. Los pedidos en preparación o listos también apartan unidades.
- El stock físico baja al cobrar en el POS. Los pedidos conservan los precios
  con los que fueron enviados.
- Una única apertura de caja puede estar activa; la opera y cierra su dueño.
- Los pedidos listos con veinte minutos o más se separan visualmente; su
  cancelación es manual.
- El horario de pedidos es opcional. Se configura de lunes a viernes y se
  valida desde la API en hora de El Salvador. Desactivado permite pedidos a
  cualquier hora.
- Los reportes se consultan en pantalla. Las facturas pueden reimprimirse o
  guardarse como PDF desde el navegador.

## Pruebas

Web, desde `pagina_web/`:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test cafeteria --noinput
```

API, desde `api_movil/`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

Las pruebas de Python utilizan bases MySQL temporales y requieren permisos
para crearlas y eliminarlas. Flutter tiene sus pruebas en `test/`:

```powershell
flutter test
flutter analyze
```

## Archivos locales y despliegue

El repositorio incluye código, recursos de la app y plantillas de configuración.
Los datos de usuarios, ventas, sesiones, fotos cargadas, claves, entornos
virtuales, registros y APK quedan fuera de Git. Cada instalación configura sus
propias credenciales.

Para una VPS se deben configurar dominio y HTTPS, secretos propios, usuario
MySQL limitado, procesos de servidor y una carpeta de fotos compartida entre
Django y FastAPI. La app se compila con el `API_BASE_URL` público HTTPS y una
firma Android propia para distribución de producción.
