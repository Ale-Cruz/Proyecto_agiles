import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/carrito.dart';
import '../models/producto.dart';
import '../providers/cafeteria_provider.dart';
import '../widgets/common.dart';

class CartScreen extends StatefulWidget {
  const CartScreen({super.key});
  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(context.read<CafeteriaProvider>().refrescar());
    });
  }

  Future<void> _cantidad(CartItem item, int amount) async {
    final p = context.read<CafeteriaProvider>();
    try {
      await p.cantidad(item.producto.id, amount);
    } catch (e) {
      if (mounted) mensaje(context, e);
      await p.refrescar();
    }
  }

  Future<void> _enviar() async {
    final p = context.read<CafeteriaProvider>();
    try {
      await p.enviarPedido();
      if (!mounted) return;
      mensaje(context, 'Pedido enviado. Puedes consultar su estado.');
      Navigator.pushReplacementNamed(context, '/active_order');
    } catch (e) {
      if (mounted) mensaje(context, e);
      await p.refrescar();
    }
  }

  @override
  Widget build(BuildContext c) {
    final p = c.watch<CafeteriaProvider>();
    final cart = p.carrito;
    final seconds = p.segundosCarrito;
    final countdown =
        '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, "0")}';
    return Scaffold(
        appBar: AppBar(title: const Text('Carrito')),
        body: SafeArea(
            child: Column(children: [
          if (p.pedidoActivo != null)
            Card(
                margin: const EdgeInsets.all(12),
                child: ListTile(
                    title: const Text('Ya tienes un pedido activo'),
                    subtitle: const Text('Recógelo antes de enviar otro.'),
                    onTap: () => Navigator.pushNamed(c, '/active_order'),
                    trailing: const Icon(Icons.chevron_right))),
          if (cart.expiraEn != null)
            Card(
                margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(children: [
                      const Icon(Icons.timer_outlined),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                            Text('Tiempo restante: $countdown',
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold)),
                            const Text(
                                'Tienes 5 minutos fijos. Al terminar se vaciará el carrito.')
                          ]))
                    ]))),
          Expanded(
              child: RefreshIndicator(
                  onRefresh: p.refrescar,
                  child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(12),
                      children: [
                        if (cart.items.isEmpty)
                          Padding(
                              padding: const EdgeInsets.all(32),
                              child: Text(
                                  cart.expirado
                                      ? 'Se terminaron los 5 minutos. Tu carrito se vació y los productos se liberaron.'
                                      : 'Tu carrito está vacío.',
                                  textAlign: TextAlign.center)),
                        for (final item in cart.items)
                          Card(
                              child: Padding(
                                  padding: const EdgeInsets.all(12),
                                  child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(item.producto.nombre,
                                            style: Theme.of(c)
                                                .textTheme
                                                .titleMedium),
                                        Text(
                                            '${precio(item.producto.precioCentavos)} con IVA por unidad'),
                                        if (!item.disponible)
                                          const Text(
                                              'La disponibilidad cambió. Ajusta la cantidad o retira el producto.',
                                              style:
                                                  TextStyle(color: Colors.red)),
                                        Row(children: [
                                          IconButton(
                                              tooltip: 'Disminuir cantidad',
                                              onPressed: p.operando
                                                  ? null
                                                  : () => _cantidad(
                                                      item, item.cantidad - 1),
                                              icon: const Icon(
                                                  Icons.remove_circle_outline)),
                                          Text('${item.cantidad}'),
                                          IconButton(
                                              tooltip: 'Aumentar cantidad',
                                              onPressed: p.operando ||
                                                      item.cantidad >=
                                                          item.producto.stock
                                                  ? null
                                                  : () => _cantidad(
                                                      item, item.cantidad + 1),
                                              icon: const Icon(
                                                  Icons.add_circle_outline)),
                                          const Spacer(),
                                          Text(precio(item.importe)),
                                          IconButton(
                                              tooltip: 'Quitar producto',
                                              onPressed: p.operando
                                                  ? null
                                                  : () => _cantidad(item, 0),
                                              icon: const Icon(
                                                  Icons.delete_outline))
                                        ])
                                      ]))),
                      ]))),
          if (cart.items.isNotEmpty)
            Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Desglose(
                          subtotal: cart.subtotal,
                          iva: cart.iva,
                          total: cart.total),
                      const SizedBox(height: 12),
                      FilledButton(
                          onPressed: p.operando ||
                                  seconds == 0 ||
                                  p.pedidoActivo != null ||
                                  cart.items.any((i) => !i.disponible)
                              ? null
                              : _enviar,
                          child: Text(
                              p.operando ? 'Procesando…' : 'Enviar pedido'))
                    ]))
        ])));
  }
}
