# API móvil de cafetería

FastAPI + SQLModel + MySQL. Usa operaciones reales sobre la misma BD de Django:
sistema_pedidos. La app Flutter está en ../proyecto_cafeteria.

## Arranque local

Usar .venv; el antiguo venv estaba vinculado a Python de otra PC.

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copiar .env.example a .env solo en una instalación nueva. Conservar el .env local
existente: contiene la configuración de Gmail y una API_SECRET_KEY aleatoria.
Para generar una clave nueva:

    python -c "import secrets; print(secrets.token_hex(32))"

En una instalación nueva, importar primero ../database/schema.sql en la base
MySQL vacía y crear el administrador principal siguiendo el README de la raíz.
Después, aplicar las migraciones desde ../pagina_web:

    .\.venv\Scripts\python.exe manage.py migrate

Esto incluye 0005 (códigos y activación de horarios), 0006 (sesiones por
teléfono) y 0007 (número corto de pedidos e identificador interno de reintento).
Los archivos migrations/*.sql son referencia de esos cambios, no ejecutarlos
además de las migraciones de Django en la misma instalación.

Desde api_movil, con Laragon/MySQL encendido:

    .\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001

Raíz local: http://127.0.0.1:8001/ . Documentación: /docs.
Django conserva el puerto 8000. Android en la LAN utiliza actualmente
http://192.168.0.5:8001/api/v1 . La IP puede cambiar al reconectar la PC.

## Contrato y reglas acordadas

- Catálogo público de productos y categorías activos. Un producto deshabilitado
  para venta no se puede agregar ni enviar en un pedido.
- El precio de productos YA incluye IVA: 1.13 final se desglosa en base 1.00
  e IVA 0.13. Los importes se calculan en el servidor con Decimal.
- Disponible = stock físico menos detalles de pedidos en_preparacion/listo y
  menos detalles de carritos no vencidos. Agregar un producto lo aparta
  inmediatamente; se valida de nuevo al editar y enviar el pedido.
- La API bloquea filas de productos ordenadamente dentro de la transacción.
  Dos compradores de la última unidad no generan sobreventa.
- Un solo carrito por cuenta, compartido entre teléfonos. Sus 5 minutos
  empiezan al agregar el primer producto. Agregar, editar, vaciar o consultar
  no renueva el plazo; un carrito vacío conserva su fecha de vencimiento.
  configuracion.minutos_carrito permite cambiar la duración en la BD.
- El vencimiento deja de contar como reserva de inmediato, incluso con la app
  cerrada; la API elimina los carritos vencidos cada 60 segundos. Antes de
  operar también comprueba el plazo. Los clientes envían carrito_id para
  impedir que una petición antigua use el carrito nuevo.
- Al comprobar el propio carrito, la API excluye su reserva del cálculo para
  no descontar dos veces los mismos productos.
- Al enviar, se copian líneas y precios al pedido y se vacía el carrito en la
  misma transacción. El stock físico baja al cobrar en el POS.
- Pedido nuevo: en_preparacion. Un solo pedido activo por estudiante.
  El estudiante puede cancelar únicamente mientras está en_preparacion.
  Listo requiere atención del cajero para cancelar o cobrar.
- POST pedidos exige operacion_id UUID y total_esperado. El mismo UUID permite
  reintentar después de un corte de red sin crear pedidos duplicados. El UUID
  queda interno; el número visible es PED- seguido de cuatro caracteres
  alfanuméricos fáciles de leer. La BD exige unicidad y la API reintenta si
  aparece una colisión al generar ese número.
- La API devuelve el pedido activo y los últimos 30 cerrados del estudiante.
- No se crean pedidos pendiente. La BD conserva ese valor legado por
  compatibilidad con el esquema compartido.
- configuracion.horarios_habilitados=0 permite pedidos a cualquier hora.
  Si se habilita, se consultan horarios_pedidos en la hora de El Salvador.

## Autenticación y correo

Solo estudiantes @itca.edu.sv. El registro asigna ese rol desde el servidor;
no acepta un rol enviado por el cliente. Empleados usan la web de Django.
Solicitar código de registro para un correo ya existente devuelve 409 con un
mensaje para iniciar sesión o recuperar contraseña; no envía otro código.

Contraseñas con bcrypt, compatibles también con hashes PBKDF2 de Django.
Tokens aleatorios independientes por inicio de sesión, guardados como hash
en sesiones_movil. SESSION_DAYS=0 conserva las sesiones hasta logout o cambio
de contraseña. Logout revoca solo el token actual y conserva el carrito.
Recuperar/cambiar contraseña revoca todas las sesiones del estudiante.
Una cuenta deshabilitada no puede continuar usando sus tokens.

Registro y recuperación exigen códigos reales de Gmail por SMTP STARTTLS.
Vencen a los 10 minutos, admiten 5 intentos y tienen 60 segundos entre reenvíos.
La BD guarda hash del código; no guarda el código en claro. Hay límites por
correo y por IP. Un fallo SMTP devuelve error, nunca una confirmación ficticia.

Configurar SMTP_USER y SMTP_PASSWORD en .env (contraseña de aplicación de Gmail).
No enviar esas claves por chat ni incluirlas en Git. Verificación sin enviar correo:

    .\.venv\Scripts\python.exe verificar_correo.py

Fotos: /media sirve la misma carpeta de productos de Django. Las rutas
/media/productos/... se convierten a URLs de esta API. Un producto sin foto
muestra el recurso alternativo de Flutter. PUBLIC_BASE_URL permite fijar
el origen HTTPS al desplegar detrás de un proxy.

## Pruebas

    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    .\.venv\Scripts\python.exe -m pytest tests -q

Las pruebas clonan el esquema en test_movil_codex_<identificador>, crean sus
datos ahí y eliminan esa BD al terminar. Requieren permisos de crear BD en
el MySQL local; no insertan pedidos ni usuarios de prueba en sistema_pedidos.

## VPS

Usar MySQL con usuario propio, secretos nuevos de producción, HTTPS mediante
proxy, supervisor de procesos y una ruta MEDIA_ROOT compartida con Django.
Configurar PUBLIC_BASE_URL con el dominio público y compilar Flutter con
ese API_BASE_URL HTTPS. El .env nunca se distribuye con la app.
La sesión segura requiere HTTPS fuera de las pruebas locales.

La web implementa las transiciones listo/entregado, cobros y cancelaciones,
aperturas y cierres de caja, y el descuento de inventario al cobrar. Una venta
presencial respeta las reservas de carritos no vencidos y pedidos activos.
El horario opcional se configura desde la web de lunes a viernes.
La app consulta los
estados reales y avisa en primer plano cuando recibe listo. No hay push cuando
está cerrada, según lo acordado. El aviso de 20 minutos desde listo es
informativo: solo el personal puede cancelar ese pedido.
