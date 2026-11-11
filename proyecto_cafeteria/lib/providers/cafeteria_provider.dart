import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../models/carrito.dart';
import '../models/pedido.dart';
import '../models/producto.dart';
import '../services/api_service.dart';
import '../services/session_store.dart';

class CafeteriaProvider extends ChangeNotifier {
  final ApiService api;
  final SessionStore store;
  final bool autoRefresh;
  final DateTime Function() reloj;
  CafeteriaProvider(
      {ApiService? api,
      SessionStore? store,
      this.autoRefresh = true,
      DateTime Function()? reloj})
      : reloj = reloj ?? DateTime.now,
        api = api ?? ApiService(),
        store = store ?? SecureSessionStore();

  bool inicializando = true;
  String? errorInicio;
  Map<String, dynamic>? usuario;
  bool esInvitado = false;
  bool cargandoMenu = false;
  String? errorMenu;
  bool operando = false;
  String? errorEstado;
  String? avisoPedido;
  int avisoVersion = 0;
  final Set<int> _avisados = {};
  List<Producto> _productos = [];
  List<Categoria> _categorias = [];
  Carrito carrito = const Carrito();
  Pedido? pedidoActivo;
  List<Pedido> historial = [];
  Timer? _timer;
  Timer? _relojCarrito;
  int? _carritoVencidoId;
  bool _foreground = true;
  bool _refrescando = false;
  bool _disposed = false;
  int _epoch = 0;
  int _cartRevision = 0;
  int _orderRevision = 0;
  String? _operacionId;

  bool get autenticado => usuario != null;
  List<Producto> get productos => List.unmodifiable(_productos);
  List<Categoria> get categorias => List.unmodifiable(_categorias);
  int get unidades => carrito.items.fold(0, (sum, item) => sum + item.cantidad);

  int get segundosCarrito => carrito.segundosRestantes(reloj());

  void actualizarRelojCarrito() {
    if (carrito.expiraEn == null) return;
    if (segundosCarrito == 0) {
      _carritoVencidoId = carrito.id;
      _cartRevision++;
      _operacionId = null;
      carrito = const Carrito(expirado: true);
      _relojCarrito?.cancel();
    }
    _avisar();
  }

  void _recibirCarrito(Map<String, dynamic> data) {
    final next = Carrito.fromJson(data,
        recibidoEn: reloj(),
        limiteMaximo: data['id'] == carrito.id ? carrito.limiteLocalEn : null);
    if ((next.id != null && next.id == _carritoVencidoId) ||
        (next.id == null && next.items.isEmpty && carrito.expirado)) {
      carrito = const Carrito(expirado: true);
    } else {
      carrito = next;
      if (next.id != null) _carritoVencidoId = null;
    }
    actualizarRelojCarrito();
    _programarRelojCarrito();
  }

  void _programarRelojCarrito() {
    _relojCarrito?.cancel();
    if (autoRefresh && _foreground && carrito.expiraEn != null) {
      _relojCarrito = Timer.periodic(
          const Duration(seconds: 1), (_) => actualizarRelojCarrito());
    }
  }

  void _avisar() {
    if (!_disposed) notifyListeners();
  }

  Future<void> inicializar() async {
    inicializando = true;
    errorInicio = null;
    _avisar();
    try {
      api.token = await store.read();
      if (api.token != null) {
        try {
          usuario = await api.me();
        } on ApiException catch (e) {
          if (e.status != 401 && e.status != 403) rethrow;
          await _limpiarSesion();
        }
        if (autenticado) await refrescar();
      }
    } catch (e) {
      errorInicio = e.toString();
    } finally {
      inicializando = false;
      _programar();
      _avisar();
    }
  }

  Future<void> login(String correo, String password) async {
    final data = await api.login(correo, password);
    final token = data['access_token'] as String;
    await store.write(token);
    _reiniciarPrivado();
    api.token = token;
    usuario = Map<String, dynamic>.from(data['usuario']);
    esInvitado = false;
    inicializando = false;
    _avisar();
    await refrescar();
    _programar();
  }

  Future<void> entrarInvitado() async {
    _reiniciarPrivado();
    api.token = null;
    usuario = null;
    esInvitado = true;
    inicializando = false;
    _avisar();
    await cargarMenu();
    _programar();
  }

  Future<void> logout() async {
    if (operando) return;
    operando = true;
    _avisar();
    try {
      if (autenticado) {
        try {
          await api.logout();
        } on ApiException catch (e) {
          if (e.status != 401) rethrow;
        }
      }
      await _limpiarSesion();
    } finally {
      operando = false;
      _avisar();
    }
  }

  void _reiniciarPrivado() {
    _relojCarrito?.cancel();
    _carritoVencidoId = null;
    _epoch++;
    _cartRevision++;
    _orderRevision++;
    carrito = const Carrito();
    pedidoActivo = null;
    historial = [];
    _operacionId = null;
    _avisados.clear();
    avisoPedido = null;
    errorEstado = null;
  }

  Future<void> _limpiarSesion() async {
    _timer?.cancel();
    _reiniciarPrivado();
    usuario = null;
    esInvitado = false;
    api.token = null;
    await store.clear();
    _avisar();
  }

  Future<T> _privado<T>(Future<T> Function() action) async {
    final epoch = _epoch;
    try {
      return await action();
    } on ApiException catch (e) {
      if (e.status == 401 && epoch == _epoch) await _limpiarSesion();
      rethrow;
    }
  }

  Future<void> cargarMenu({bool silencioso = false}) async {
    if (!silencioso) {
      cargandoMenu = true;
      _avisar();
    }
    try {
      final values = await Future.wait([api.productos(), api.categorias()]);
      if (_disposed) return;
      _productos = values[0].map((e) => Producto.fromJson(e)).toList();
      _categorias = values[1].map((e) => Categoria.fromJson(e)).toList();
      errorMenu = null;
    } catch (e) {
      errorMenu = e.toString();
    } finally {
      cargandoMenu = false;
      _avisar();
    }
  }

  Future<void> cargarCarrito() async {
    if (!autenticado || operando) return;
    final epoch = _epoch;
    final revision = _cartRevision;
    final data = await _privado(api.carrito);
    if (epoch == _epoch &&
        revision == _cartRevision &&
        !operando &&
        !_disposed) {
      _recibirCarrito(data);
      _avisar();
    }
  }

  Future<void> cargarPedidos() async {
    if (!autenticado || operando) return;
    final epoch = _epoch;
    final revision = _orderRevision;
    try {
      final data = await _privado(api.pedidos);
      if (epoch != _epoch ||
          revision != _orderRevision ||
          operando ||
          _disposed) return;
      pedidoActivo = data['pedido_activo'] == null
          ? null
          : Pedido.fromJson(data['pedido_activo']);
      historial =
          (data['historial'] as List).map((e) => Pedido.fromJson(e)).toList();
      errorEstado = null;
      final pedido = pedidoActivo;
      if (pedido != null &&
          pedido.estado == 'listo' &&
          _avisados.add(pedido.id)) {
        avisoPedido =
            'Tu pedido ${pedido.numero} está listo. Pasa a recogerlo en caja.';
        avisoVersion++;
      }
      _avisar();
    } catch (e) {
      errorEstado = e.toString();
      _avisar();
      rethrow;
    }
  }

  Future<void> refrescar() async {
    if (_refrescando || operando || _disposed) return;
    _refrescando = true;
    try {
      await Future.wait([
        cargarMenu(silencioso: _productos.isNotEmpty),
        if (autenticado) cargarCarrito(),
        if (autenticado) cargarPedidos(),
      ]);
    } catch (_) {
      /* Los errores se muestran en su pantalla; no borrar datos válidos. */
    } finally {
      _refrescando = false;
    }
  }

  Future<void> cantidad(int productoId, int cantidad) async {
    if (!autenticado)
      throw const ApiException(401, 'Inicia sesión para agregar productos.');
    if (operando) return;
    operando = true;
    _cartRevision++;
    _orderRevision++;
    final epoch = _epoch;
    _avisar();
    try {
      final data = await _privado(
          () => api.cantidad(productoId, cantidad, carritoId: carrito.id));
      if (epoch == _epoch) {
        _recibirCarrito(data);
        _operacionId = null;
      }
    } finally {
      operando = false;
      _avisar();
    }
  }

  int cantidadActual(int productoId) => carrito.items
      .where((e) => e.producto.id == productoId)
      .fold(0, (sum, item) => sum + item.cantidad);

  Future<Pedido> enviarPedido() async {
    actualizarRelojCarrito();
    if (operando)
      throw const ApiException(
          409, 'Espera a que termine la solicitud actual.');
    if (carrito.items.isEmpty)
      throw ApiException(
          409,
          carrito.expirado
              ? 'Los 5 minutos terminaron. Agrega los productos de nuevo.'
              : 'Tu carrito está vacío.');
    operando = true;
    _cartRevision++;
    _orderRevision++;
    final epoch = _epoch;
    _operacionId ??= _uuid();
    _avisar();
    try {
      final data = await _privado(() => api.crearPedido(
          _operacionId!, decimal(carrito.total),
          carritoId: carrito.id));
      final pedido = Pedido.fromJson(data);
      if (epoch == _epoch) {
        _relojCarrito?.cancel();
        carrito = const Carrito();
        pedidoActivo = pedido;
        _operacionId = null;
      }
      return pedido;
    } finally {
      operando = false;
      _avisar();
    }
  }

  Future<void> cancelarPedido(int id) async {
    if (operando) return;
    _orderRevision++;
    operando = true;
    _avisar();
    try {
      await _privado(() => api.cancelar(id));
    } finally {
      operando = false;
      _avisar();
    }
    await refrescar();
  }

  String _uuid() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final h = bytes.map((e) => e.toRadixString(16).padLeft(2, '0')).join();
    return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
  }

  void setForeground(bool value) {
    _foreground = value;
    _timer?.cancel();
    _relojCarrito?.cancel();
    if (value) {
      actualizarRelojCarrito();
      _programarRelojCarrito();
      unawaited(refrescar());
      _programar();
    }
  }

  void _programar() {
    _timer?.cancel();
    if (autoRefresh && _foreground && (autenticado || esInvitado)) {
      _timer = Timer.periodic(
          const Duration(seconds: 8), (_) => unawaited(refrescar()));
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _relojCarrito?.cancel();
    api.dispose();
    super.dispose();
  }
}
