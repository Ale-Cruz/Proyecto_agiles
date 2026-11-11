import 'producto.dart';

class CartItem {
  final Producto producto;
  final int cantidad;
  final int importe;
  final bool disponible;
  const CartItem(this.producto, this.cantidad, this.importe, this.disponible);
  factory CartItem.fromJson(Map<String, dynamic> json) => CartItem(
      Producto.fromJson(json['producto'] as Map<String, dynamic>),
      json['cantidad'] as int,
      centavos(json['importe']),
      json['disponible'] as bool);
}

class Carrito {
  final int? id;
  final DateTime? limiteLocalEn;
  final List<CartItem> items;
  final int subtotal;
  final int iva;
  final int total;
  final DateTime? expiraEn;
  final bool expirado;
  const Carrito(
      {this.id,
      this.limiteLocalEn,
      this.items = const [],
      this.subtotal = 0,
      this.iva = 0,
      this.total = 0,
      this.expiraEn,
      this.expirado = false});
  int segundosRestantes(DateTime ahora) {
    final limite = limiteLocalEn ?? expiraEn;
    if (limite == null) return 0;
    final milliseconds = limite.difference(ahora).inMilliseconds;
    return milliseconds <= 0 ? 0 : (milliseconds + 999) ~/ 1000;
  }

  factory Carrito.fromJson(Map<String, dynamic> json,
      {DateTime? recibidoEn, DateTime? limiteMaximo}) {
    final expires =
        json['expira_en'] == null ? null : DateTime.parse(json['expira_en']);
    final server = json['servidor_en'] == null
        ? null
        : DateTime.parse(json['servidor_en']);
    final local = recibidoEn ?? DateTime.now();
    var deadline = expires == null
        ? null
        : server == null
            ? expires
            : local.add(expires.difference(server));
    if (deadline != null &&
        limiteMaximo != null &&
        deadline.isAfter(limiteMaximo)) {
      deadline = limiteMaximo;
    }
    return Carrito(
        id: json['id'] as int?,
        limiteLocalEn: deadline,
        items:
            (json['items'] as List).map((e) => CartItem.fromJson(e)).toList(),
        subtotal: centavos(json['subtotal']),
        iva: centavos(json['iva']),
        total: centavos(json['total']),
        expiraEn: expires,
        expirado: json['expirado'] == true);
  }
}
