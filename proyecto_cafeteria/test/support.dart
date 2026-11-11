import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:proyecto_cafeteria/providers/cafeteria_provider.dart';
import 'package:proyecto_cafeteria/services/api_service.dart';
import 'package:proyecto_cafeteria/services/session_store.dart';
import 'package:proyecto_cafeteria/models/producto.dart';

class MemoryStore implements SessionStore {
  String? token;
  MemoryStore([this.token]);
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async {
    token = value;
  }

  @override
  Future<void> clear() async {
    token = null;
  }
}

class FakeServer {
  final DateTime Function() reloj;
  late DateTime expiraEn;
  FakeServer({DateTime Function()? reloj}) : reloj = reloj ?? DateTime.now {
    expiraEn = this.reloj().toUtc().add(const Duration(minutes: 5));
  }
  final requests = <http.Request>[];
  Future<http.Response?> Function(http.Request)? override;
  int quantity = 2;
  bool hasOrder = false;
  String state = 'en_preparacion';
  List<Map<String, dynamic>> previousOrders = [];
  Map<String, dynamic> get product => {
        'id': 1,
        'codigo': 'P1',
        'nombre': 'Café',
        'descripcion': 'Caliente',
        'categoria_id': 1,
        'categoria': 'Bebidas',
        'precio': '1.13',
        'precio_sin_iva': '1.00',
        'stock': 10,
        'habilitado': true,
        'imagen': null
      };
  Map<String, dynamic> get order => {
        'id': 23,
        'numero': 'PED-7K2M',
        'estado': state,
        'puede_cancelar': state == 'en_preparacion',
        'creado_en': '2026-11-09T18:00:00Z',
        'estado_actualizado_en': '2026-11-09T18:00:00Z',
        'items': [
          {
            'nombre': 'Café',
            'producto_id': 1,
            'cantidad': 2,
            'precio_unitario': '1.13',
            'importe': '2.26'
          }
        ],
        'subtotal': '2.00',
        'iva': '0.26',
        'total': '2.26'
      };
  Map<String, dynamic> get cart => {
        'id': reloj().toUtc().isBefore(expiraEn) && !hasOrder ? 1 : null,
        'servidor_en': reloj().toUtc().toIso8601String(),
        'items': quantity == 0 || !reloj().toUtc().isBefore(expiraEn)
            ? []
            : [
                {
                  'producto': product,
                  'cantidad': quantity,
                  'importe': decimal(quantity * 113),
                  'disponible': true
                }
              ],
        'expirado': !reloj().toUtc().isBefore(expiraEn),
        'expira_en': reloj().toUtc().isBefore(expiraEn) && !hasOrder
            ? expiraEn.toIso8601String()
            : null,
        'subtotal': decimal((quantity * 11300 / 113).round()),
        'iva': decimal(quantity * 13),
        'total': decimal(quantity * 113)
      };
  http.Response response(dynamic data, [int status = 200]) =>
      http.Response(jsonEncode(data), status,
          headers: {'content-type': 'application/json; charset=utf-8'});
  Future<http.Response> handle(http.Request request) async {
    requests.add(request);
    final custom = await override?.call(request);
    if (custom != null) return custom;
    final path = request.url.path;
    if (path.endsWith('/auth/login')) {
      final body = jsonDecode(request.body);
      if (body['password'] != 'ClaveSegura2026!')
        return response({'detail': 'Correo o contraseña incorrectos.'}, 401);
      return response({
        'access_token': 'valid-token',
        'token_type': 'bearer',
        'usuario': {
          'id': 10,
          'nombre': 'Alumno',
          'correo': 'alumno@itca.edu.sv'
        }
      });
    }
    if (path.endsWith('/auth/me'))
      return response(
          {'id': 10, 'nombre': 'Alumno', 'correo': 'alumno@itca.edu.sv'});
    if (path.endsWith('/auth/logout')) {
      return response({'mensaje': 'Sesión cerrada.'});
    }
    if (path.endsWith('/productos/categorias'))
      return response([
        {'id': 1, 'nombre': 'Bebidas'}
      ]);
    if (path.endsWith('/productos/')) return response([product]);
    if (path.endsWith('/carrito/')) return response(cart);
    if (path.contains('/carrito/items/')) {
      final amount = jsonDecode(request.body)['cantidad'] as int;
      if (amount > 10) return response({'detail': 'Stock insuficiente.'}, 409);
      quantity = amount;
      return response(cart);
    }
    if (path.endsWith('/pedidos/mios'))
      return response(
          {'pedido_activo': hasOrder ? order : null, 'historial': previousOrders});
    if (path.endsWith('/pedidos/')) {
      hasOrder = true;
      quantity = 0;
      return response(order, 201);
    }
    if (path.endsWith('/cancelar')) {
      hasOrder = false;
      return response(order);
    }
    return response({'detail': 'No encontrado'}, 404);
  }

  CafeteriaProvider provider(
          {MemoryStore? store,
          DateTime Function()? reloj,
          bool autoRefresh = false}) =>
      CafeteriaProvider(
          api: ApiService(
              client: MockClient(handle), baseUrl: 'http://test/api/v1'),
          store: store ?? MemoryStore(),
          reloj: reloj,
          autoRefresh: autoRefresh);
}
