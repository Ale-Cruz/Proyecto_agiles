import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:proyecto_cafeteria/models/producto.dart';
import 'package:proyecto_cafeteria/services/api_service.dart';
import 'support.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('precios decimales y desglose no agregan IVA al total', () async {
    expect(centavos('1.13'), 113);
    expect(centavos(1.13), 113);
    expect(centavos(2), 200);
    final server = FakeServer();
    final p = server.provider();
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    expect(p.carrito.total, 226);
    expect(p.carrito.subtotal, 200);
    expect(p.carrito.iva, 26);
    expect(
        server.requests
            .where((r) => r.url.path.contains('/carrito/'))
            .every((r) => r.headers['Authorization'] == 'Bearer valid-token'),
        isTrue);
  });
  test('logout limpia datos locales y conserva el carrito compartido',
      () async {
    final server = FakeServer();
    final store = MemoryStore();
    final p = server.provider(store: store);
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    expect(p.carrito.items, isNotEmpty);
    await p.logout();
    expect(p.carrito.items, isEmpty);
    expect(p.autenticado, isFalse);
    expect(store.token, isNull);
    expect(p.api.token, isNull);
    expect(server.quantity, 2);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    expect(p.carrito.items.single.cantidad, 2);
  });
  test('reanuda la sesion con token sin guardar contraseña', () async {
    final server = FakeServer();
    final store = MemoryStore('valid-token');
    final p = server.provider(store: store);
    addTearDown(p.dispose);
    await p.inicializar();
    expect(p.autenticado, isTrue);
    expect(p.usuario!['nombre'], 'Alumno');
    expect(server.requests.any((r) => r.url.path.endsWith('/auth/login')),
        isFalse);
  });
  test('401 limpia la sesion y sus datos privados', () async {
    final server = FakeServer();
    final store = MemoryStore();
    final p = server.provider(store: store);
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    server.override = (r) async => r.url.path.endsWith('/carrito/')
        ? server.response({'detail': 'Sesión terminada'}, 401)
        : null;
    await expectLater(p.cargarCarrito(), throwsA(isA<ApiException>()));
    expect(p.autenticado, isFalse);
    expect(p.carrito.items, isEmpty);
    expect(store.token, isNull);
  });
  test('un fallo de envio conserva carrito y reutiliza operacion al reintentar',
      () async {
    final server = FakeServer();
    final p = server.provider();
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    var fail = true;
    server.override = (r) async {
      if (r.url.path.endsWith('/pedidos/') && fail) {
        fail = false;
        throw http.ClientException('sin red');
      }
      return null;
    };
    await expectLater(p.enviarPedido(), throwsA(isA<ApiException>()));
    expect(p.carrito.items, isNotEmpty);
    expect(p.operando, isFalse);
    final order = await p.enviarPedido();
    expect(order.id, 23);
    expect(p.carrito.items, isEmpty);
    final calls =
        server.requests.where((r) => r.url.path.endsWith('/pedidos/')).toList();
    expect(calls.length, 2);
    expect(jsonDecode(calls[0].body)['operacion_id'],
        jsonDecode(calls[1].body)['operacion_id']);
    expect(jsonDecode(calls[0].body).containsKey('estudiante_id'), isFalse);
  });
  test('un GET atrasado no reemplaza una cantidad recien editada', () async {
    final server = FakeServer();
    final p = server.provider();
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    final pending = Completer<http.Response>();
    final old = server.cart;
    server.override =
        (r) async => r.url.path.endsWith('/carrito/') ? pending.future : null;
    final request = p.cargarCarrito();
    await Future<void>.delayed(Duration.zero);
    await p.cantidad(1, 3);
    pending.complete(server.response(old));
    await request;
    expect(p.carrito.items.single.cantidad, 3);
  });
  test('avisa una sola vez cuando pasa a listo', () async {
    final server = FakeServer()..hasOrder = true;
    final p = server.provider();
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    expect(p.avisoVersion, 0);
    server.state = 'listo';
    await p.cargarPedidos();
    expect(p.avisoVersion, 1);
    expect(p.avisoPedido, contains('listo'));
    await p.cargarPedidos();
    expect(p.avisoVersion, 1);
    expect(p.pedidoActivo!.puedeCancelar, isFalse);
  });
  test('error de servidor HTML se presenta sin FormatException', () async {
    final server = FakeServer();
    final p = server.provider();
    addTearDown(p.dispose);
    server.override = (r) async => http.Response('<html>Error</html>', 502);
    await expectLater(p.api.login('alumno@itca.edu.sv', 'ClaveSegura2026!'),
        throwsA(isA<ApiException>()));
  });
  test('plazo fijo calibrado con servidor y sin reinicio al editar', () async {
    var serverNow = DateTime.utc(2026, 11, 10, 20);
    var deviceNow = DateTime.utc(2040, 1, 1);
    final server = FakeServer(reloj: () => serverNow);
    final p = server.provider(reloj: () => deviceNow);
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    expect(p.segundosCarrito, 300);
    final deadline = p.carrito.expiraEn;
    serverNow = serverNow.add(const Duration(minutes: 2));
    deviceNow = deviceNow.add(const Duration(minutes: 2));
    for (final n in [3, 0, 4]) {
      await p.cantidad(1, n);
      expect(p.carrito.expiraEn, deadline);
      expect(p.segundosCarrito, 180);
    }
    final call = server.requests
        .lastWhere((r) => r.url.path.contains('/carrito/items/'));
    expect(jsonDecode(call.body)['carrito_id'], 1);
    serverNow = serverNow.add(const Duration(minutes: 3));
    deviceNow = deviceNow.add(const Duration(minutes: 3));
    p.actualizarRelojCarrito();
    expect(p.carrito.items, isEmpty);
    expect(p.carrito.expirado, isTrue);
    await expectLater(p.enviarPedido(), throwsA(isA<ApiException>()));
    expect(
        server.requests.any((r) => r.url.path.endsWith('/pedidos/')), isFalse);
  });

  test('volver del fondo no recupera un carrito vencido', () async {
    var now = DateTime.utc(2026, 11, 10, 20);
    final server = FakeServer(reloj: () => now);
    final p = server.provider(reloj: () => now);
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    p.setForeground(false);
    now = now.add(const Duration(minutes: 6));
    p.setForeground(true);
    await Future<void>.delayed(Duration.zero);
    expect(p.carrito.items, isEmpty);
    expect(p.carrito.expirado, isTrue);
  });

  test('una respuesta atrasada no revive el carrito al vencer', () async {
    var now = DateTime.utc(2026, 11, 10, 20);
    final server = FakeServer(reloj: () => now);
    final p = server.provider(reloj: () => now);
    addTearDown(p.dispose);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    final old = server.cart;
    final pending = Completer<http.Response>();
    server.override =
        (r) async => r.url.path.endsWith('/carrito/') ? pending.future : null;
    final request = p.cargarCarrito();
    await Future<void>.delayed(Duration.zero);
    now = now.add(const Duration(minutes: 5));
    p.actualizarRelojCarrito();
    pending.complete(server.response(old));
    await request;
    expect(p.carrito.items, isEmpty);
    expect(p.carrito.expirado, isTrue);
  });
}
