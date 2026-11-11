import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final int status;
  final String mensaje;
  const ApiException(this.status, this.mensaje);
  @override
  String toString() => mensaje;
}

class ApiService {
  final http.Client _client;
  final String baseUrl;
  String? token;
  ApiService({http.Client? client, String? baseUrl})
      : _client = client ?? http.Client(),
        baseUrl = (baseUrl ?? defaultBaseUrl).replaceFirst(RegExp(r'/+$'), '');

  static String get defaultBaseUrl {
    const configured = String.fromEnvironment('API_BASE_URL');
    if (configured.isNotEmpty) return configured;
    final host = !kIsWeb && defaultTargetPlatform == TargetPlatform.android
        ? '10.0.2.2'
        : '127.0.0.1';
    return 'http://$host:8001/api/v1';
  }

  Future<dynamic> _call(String method, String path,
      {Map<String, dynamic>? body, bool privada = true}) async {
    if (privada && token == null)
      throw const ApiException(401, 'Inicia sesión para continuar.');
    final request = http.Request(method, Uri.parse('$baseUrl$path'));
    request.headers['Accept'] = 'application/json';
    if (privada) request.headers['Authorization'] = 'Bearer $token';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    try {
      final response = await _client
          .send(request)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 25));
      dynamic data;
      try {
        data = jsonDecode(utf8.decode(response.bodyBytes));
      } catch (_) {
        throw const ApiException(0,
            'El servidor no devolvió una respuesta válida. Verifica la conexión con la cafetería.');
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final detail = data is Map ? data['detail'] : null;
        final message = detail is String
            ? detail
            : detail is List && detail.isNotEmpty
                ? detail.first['msg']
                    .toString()
                    .replaceFirst('Value error, ', '')
                : 'No fue posible completar la solicitud.';
        throw ApiException(response.statusCode, message);
      }
      return data;
    } on TimeoutException {
      throw const ApiException(0,
          'El servidor tardó demasiado. Comprueba el estado del pedido antes de reenviarlo.');
    } on http.ClientException {
      throw const ApiException(
          0, 'No se pudo conectar con la cafetería. Comprueba tu conexión.');
    }
  }

  Future<Map<String, dynamic>> login(String correo, String password) async =>
      Map<String, dynamic>.from(await _call('POST', '/auth/login',
          body: {'correo': correo, 'password': password}, privada: false));
  Future<void> enviarCodigo(String correo, {bool recuperar = false}) async {
    await _call('POST', recuperar ? '/auth/recuperar' : '/auth/enviar-codigo',
        body: {'correo': correo}, privada: false);
  }

  Future<void> registrar(
      String nombre, String correo, String password, String codigo) async {
    await _call('POST', '/auth/verificar-registro',
        body: {
          'nombre': nombre,
          'correo': correo,
          'password': password,
          'codigo': codigo
        },
        privada: false);
  }

  Future<void> cambiarPassword(
      String correo, String password, String codigo) async {
    await _call('POST', '/auth/cambiar-password',
        body: {'correo': correo, 'password': password, 'codigo': codigo},
        privada: false);
  }

  Future<Map<String, dynamic>> me() async =>
      Map<String, dynamic>.from(await _call('GET', '/auth/me'));
  Future<void> logout() async {
    await _call('POST', '/auth/logout');
  }

  Future<List<dynamic>> productos() async =>
      List<dynamic>.from(await _call('GET', '/productos/', privada: false));
  Future<List<dynamic>> categorias() async => List<dynamic>.from(
      await _call('GET', '/productos/categorias', privada: false));
  Future<Map<String, dynamic>> carrito() async =>
      Map<String, dynamic>.from(await _call('GET', '/carrito/'));
  Future<Map<String, dynamic>> cantidad(int productoId, int cantidad,
          {int? carritoId}) async =>
      Map<String, dynamic>.from(await _call('PUT', '/carrito/items/$productoId',
          body: {
            'cantidad': cantidad,
            if (carritoId != null) 'carrito_id': carritoId
          }));
  Future<Map<String, dynamic>> crearPedido(String operacionId, String total,
          {int? carritoId}) async =>
      Map<String, dynamic>.from(await _call('POST', '/pedidos/', body: {
        'operacion_id': operacionId,
        'total_esperado': total,
        if (carritoId != null) 'carrito_id': carritoId
      }));
  Future<Map<String, dynamic>> pedidos() async =>
      Map<String, dynamic>.from(await _call('GET', '/pedidos/mios'));
  Future<void> cancelar(int id) async {
    await _call('PUT', '/pedidos/$id/cancelar');
  }

  void dispose() => _client.close();
}
