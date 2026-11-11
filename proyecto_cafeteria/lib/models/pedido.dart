import 'producto.dart';

class PedidoItem {
  final String nombre;
  final int cantidad;
  final int importe;
  const PedidoItem(this.nombre, this.cantidad, this.importe);
  factory PedidoItem.fromJson(Map<String, dynamic> json) =>
      PedidoItem(json['nombre'], json['cantidad'], centavos(json['importe']));
}

class Pedido {
  final int id;
  final String numero;
  final String estado;
  final bool puedeCancelar;
  final int subtotal;
  final int iva;
  final int total;
  final List<PedidoItem> items;
  final DateTime creadoEn;
  const Pedido(
      {required this.id,
      required this.numero,
      required this.estado,
      required this.puedeCancelar,
      required this.subtotal,
      required this.iva,
      required this.total,
      required this.items,
      required this.creadoEn});
  String get estadoTexto => switch (estado) {
        'en_preparacion' => 'En preparación',
        'listo' => 'Listo para recoger',
        'entregado' => 'Entregado',
        'cancelado' => 'Cancelado',
        _ => estado,
      };
  factory Pedido.fromJson(Map<String, dynamic> json) => Pedido(
      id: json['id'],
      numero: json['numero'],
      estado: json['estado'],
      puedeCancelar: json['puede_cancelar'] == true,
      subtotal: centavos(json['subtotal']),
      iva: centavos(json['iva']),
      total: centavos(json['total']),
      items:
          (json['items'] as List).map((e) => PedidoItem.fromJson(e)).toList(),
      creadoEn: DateTime.parse(json['creado_en']));
}
