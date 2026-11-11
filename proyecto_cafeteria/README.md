# App móvil de cafetería

Flutter/Dart con Provider, HTTP y flutter_secure_storage. Consume la API real
de ../api_movil y la BD compartida sistema_pedidos. Solo admite estudiantes.

## Funciones

Registro y recuperación con códigos reales al correo @itca.edu.sv.
Login con sesión persistente y token en almacenamiento seguro de Android.
Menú público, categorías reales y fotos de la web con imagen alternativa.
El menú muestra solo el precio final de cada producto y Disponible/Agotado;
el desglose base + IVA aparece en el carrito y conserva el total de la web.
Carrito compartido por cuenta que aparta productos durante 5 minutos fijos
desde el primer artículo; muestra el tiempo restante y se vacía al vencer.
Estado del pedido, historial y cancelación durante en_preparacion.
En listo avisa que el personal puede cancelar si pasan más de 20 minutos sin
recogerlo. Ese aviso no ejecuta una cancelación automática.
La tarjeta del menú abre solo el pedido activo; «Mis pedidos» muestra el activo
y los anteriores. Una ilustración negra de chef acompaña «En preparación» y
otra de plato con cubiertos acompaña «Listo».
El código mostrado al estudiante y en los avisos es PED-XXXX; el ID de la fila
queda interno para las operaciones de la API.
Un correo ya registrado muestra un aviso antes de pasar a ingresar código.
Aviso de listo con la app abierta; refresco cada 8 segundos en primer plano.
El polling se detiene cuando la app queda en segundo plano.

Cerrar sesión borra datos privados y token de este teléfono; conserva el carrito
en el servidor para los demás teléfonos. Cambiar contraseña revoca todas
las sesiones. No se guardan contraseñas en el dispositivo.

## Preparación

Con Laragon/MySQL y la API encendidos:

    flutter pub get
    flutter run --dart-define=API_BASE_URL=http://192.168.0.5:8001/api/v1

Android físico y PC deben estar en la misma red. El emulador usa por defecto
http://10.0.2.2:8001/api/v1 . Si cambia la IP de la PC, recompilar con la nueva.

    flutter build apk --debug --dart-define=API_BASE_URL=http://192.168.0.5:8001/api/v1

APK: build/app/outputs/flutter-apk/app-debug.apk.
HTTP está habilitado únicamente en debug/profile. La compilación de producción
debe usar un API_BASE_URL HTTPS, firma de producción y configuración del VPS.
La app no lleva contraseñas MySQL ni credenciales SMTP.

## Helper de esta PC

El SDK Flutter instalado tiene un fallo en su bootstrap de Windows. El helper
local utiliza su snapshot y un wrapper de Gradle generado en .build-tools para
compilar sin modificar el SDK global. También prepara copias locales de los jars
del SDK autorizado y de dependencias para javac en
C:/dev/flutter/bin/cache/cafeteria-javac, sin cambiar scripts ni opciones globales. Rutas locales: C:/dev/flutter y el Android
SDK configurado en android/local.properties. Esas rutas no se suben al servidor.

    python build_android.py
    python build_android.py test
    python build_android.py analyze

API_BASE_URL y FLUTTER_ROOT pueden suministrarse como variables de entorno.
Los logs quedan en .build-logs. El helper no cambia opciones globales de Flutter.

## Pruebas

    flutter test
    flutter analyze

Las pruebas usan HTTP simulado exclusivamente en test/. La app de lib/ no
simula cuentas, códigos, productos, carritos ni pedidos.
El backend prueba las reglas de negocio y concurrencia con MySQL en una BD
aislada que se elimina al terminar.

La web ya incorpora atención de pedidos y cobro del POS.
Al marcar listo desde el servidor, la app consulta el estado real y avisa.
El stock físico se descuenta desde ese cobro. Un carrito no vencido
aparta unidades en la disponibilidad calculada; enviar el pedido mantiene
esa reserva como pedido activo hasta que el POS lo cobre o cancele.

APK local verificado y firmado: http://192.168.0.5:8001/media/descargas/cafeteria-debug.apk?v=20261110-ped4
Disponible mientras esta API y la PC estén encendidas, en la misma red.

El helper usa cachés locales bajo C:/dev/flutter/bin/cache/cafeteria-*,
incluido el NDK instalado mediante enlaces a sus archivos y la firma debug.
Los scripts del SDK y sus opciones globales conservan su configuración.
