import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:proyecto_cafeteria/main.dart';
import 'package:proyecto_cafeteria/screens/cart_screen.dart';
import 'package:proyecto_cafeteria/screens/login_screen.dart';
import 'package:proyecto_cafeteria/screens/register_screen.dart';
import 'support.dart';

void main() {
  testWidgets('acceso directo a carrito exige iniciar sesion', (tester) async {
    final p = FakeServer().provider()..inicializando = false;
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    final c = tester.element(find.byType(LoginScreen));
    Navigator.of(c).pushNamed('/cart');
    await tester.pumpAndSettle();
    expect(find.byType(CartScreen), findsNothing);
    expect(find.text('Ingresar'), findsOneWidget);
  });
  testWidgets(
      'menu invitado muestra precio final y disponibilidad sin cantidades',
      (tester) async {
    final p = FakeServer().provider();
    await p.entrarInvitado();
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    expect(find.text(r'Precio: $1.13'), findsOneWidget);
    expect(find.text('Caliente'), findsOneWidget);
    expect(find.text('Disponible'), findsOneWidget);
    expect(find.textContaining('IVA'), findsNothing);
    expect(find.textContaining('Disponibles:'), findsNothing);
    expect(find.text('Bebidas'), findsOneWidget);
    expect(find.byTooltip('Carrito'), findsNothing);
  });
  testWidgets('login incorrecto no abre menu', (tester) async {
    final p = FakeServer().provider()..inicializando = false;
    await tester.pumpWidget(MyApp(provider: p));
    await tester.enterText(
        find.byType(TextFormField).at(0), 'alumno@itca.edu.sv');
    await tester.enterText(find.byType(TextFormField).at(1), 'incorrecta');
    await tester.tap(find.text('Ingresar'));
    await tester.pumpAndSettle();
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.text('Correo o contraseña incorrectos.'), findsOneWidget);
  });
  testWidgets('correo registrado muestra error sin pasar al codigo',
      (tester) async {
    final server = FakeServer();
    server.override = (r) async => r.url.path.endsWith('/auth/enviar-codigo')
        ? server.response({
            'detail':
                'Este correo ya está registrado. Inicia sesión o recupera tu contraseña.'
          }, 409)
        : null;
    final p = server.provider()..inicializando = false;
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.byType(LoginScreen)))
        .pushNamed('/register');
    await tester.pumpAndSettle();
    expect(find.byType(RegisterScreen), findsOneWidget);
    await tester.enterText(find.byType(TextFormField).at(0), 'Alumno');
    await tester.enterText(
        find.byType(TextFormField).at(1), 'alumno@itca.edu.sv');
    await tester.enterText(find.byType(TextFormField).at(2), 'ClaveSegura2026!');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Este correo ya está registrado'), findsOneWidget);
    expect(find.text('Enviar código'), findsOneWidget);
    expect(find.text('Código de verificación'), findsNothing);
  });
  testWidgets('acceso rapido solo muestra el pedido activo y Mis pedidos todos',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final server = FakeServer()
      ..hasOrder = true
      ..quantity = 0;
    server.previousOrders = [
      {
        ...server.order,
        'id': 22,
        'numero': 'PED-4N8R',
        'estado': 'entregado',
        'puede_cancelar': false
      }
    ];
    final p = server.provider();
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    await tester.tap(find.text('PED-7K2M: En preparación'));
    await tester.pumpAndSettle();
    expect(find.text('Pedido activo'), findsOneWidget);
    expect(find.text('PED-7K2M'), findsOneWidget);
    expect(find.text('Pedidos anteriores'), findsNothing);
    expect(find.text('PED-4N8R'), findsNothing);
    expect(
        find.byWidgetPredicate((w) =>
            w is Image &&
            w.image is AssetImage &&
            (w.image as AssetImage).assetName ==
                'assets/estados/en_preparacion.png'),
        findsOneWidget);
    server.state = 'listo';
    await p.cargarPedidos();
    await tester.pumpAndSettle();
    expect(
        find.byWidgetPredicate((w) =>
            w is Image &&
            w.image is AssetImage &&
            (w.image as AssetImage).assetName == 'assets/estados/listo.png'),
        findsOneWidget);
    Navigator.of(tester.element(find.text('Pedido activo'))).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Mis pedidos'));
    await tester.pumpAndSettle();
    expect(find.text('Mis pedidos'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('PED-4N8R'), 250,
        scrollable: find.byType(Scrollable).last);
    expect(find.text('PED-7K2M'), findsOneWidget);
    expect(find.text('PED-4N8R'), findsOneWidget);
  });
  testWidgets('bloquea doble envio y muestra pedido devuelto por API',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final server = FakeServer();
    final p = server.provider();
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    final pending = Completer<http.Response>();
    var sends = 0;
    server.override = (r) async {
      if (r.url.path.endsWith('/pedidos/')) {
        sends++;
        return pending.future;
      }
      return null;
    };
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Carrito'));
    await tester.pumpAndSettle();
    expect(find.text(r'$2.26'), findsWidgets);
    await tester.tap(find.text('Enviar pedido'));
    await tester.pump();
    final button = tester
        .widget<FilledButton>(find.widgetWithText(FilledButton, 'Procesando…'));
    expect(button.onPressed, isNull);
    expect(sends, 1);
    server.hasOrder = true;
    server.quantity = 0;
    pending.complete(server.response(server.order, 201));
    await tester.pumpAndSettle();
    expect(find.text('PED-7K2M'), findsOneWidget);
    expect(find.text('En preparación'), findsOneWidget);
    expect(find.textContaining('20 minutos'), findsOneWidget);
    expect(find.textContaining('el personal puede cancelarlo'), findsOneWidget);
  });
  testWidgets('contador baja y vacia el carrito al finalizar los cinco minutos',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var now = DateTime.utc(2026, 11, 10, 20);
    final server = FakeServer(reloj: () => now);
    final p = server.provider(reloj: () => now, autoRefresh: true);
    await p.login('alumno@itca.edu.sv', 'ClaveSegura2026!');
    await tester.pumpWidget(MyApp(provider: p));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Carrito'));
    await tester.pumpAndSettle();
    expect(find.text('Tiempo restante: 5:00'), findsOneWidget);
    now = now.add(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Tiempo restante: 4:59'), findsOneWidget);
    now = now.add(const Duration(seconds: 299));
    await tester.pump(const Duration(seconds: 299));
    await tester.pumpAndSettle();
    expect(find.textContaining('Tu carrito se vació'), findsOneWidget);
    expect(find.text('Enviar pedido'), findsNothing);
    expect(p.carrito.items, isEmpty);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
