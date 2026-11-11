import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/pedido.dart';
import '../models/producto.dart';
import '../providers/cafeteria_provider.dart';
import '../widgets/common.dart';

class OrderStatusScreen extends StatefulWidget {
  final bool soloActivo;
  const OrderStatusScreen({super.key, this.soloActivo = false});
  @override
  State<OrderStatusScreen> createState() => _OrderStatusScreenState();
}

class _OrderStatusScreenState extends State<OrderStatusScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(context.read<CafeteriaProvider>().refrescar());
    });
  }

  Future<void> _cancelar(Pedido order) async {
    final confirm = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
                title: const Text('Cancelar pedido'),
                content: const Text('¿Quieres cancelar este pedido?'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(c, false),
                      child: const Text('Volver')),
                  FilledButton(
                      onPressed: () => Navigator.pop(c, true),
                      child: const Text('Cancelar pedido'))
                ]));
    if (confirm != true || !mounted) return;
    final p = context.read<CafeteriaProvider>();
    try {
      await p.cancelarPedido(order.id);
      if (mounted) mensaje(context, 'Pedido cancelado.');
    } catch (e) {
      if (mounted) mensaje(context, e);
      await p.refrescar();
    }
  }

  Widget _pedido(Pedido order, bool activo, bool busy) => Card(
      child: Padding(
          padding: const EdgeInsets.all(16),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (activo &&
                (order.estado == 'en_preparacion' || order.estado == 'listo'))
              Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: Center(
                      child: Image.asset(
                          order.estado == 'listo'
                              ? 'assets/estados/listo.png'
                              : 'assets/estados/en_preparacion.png',
                          width: 140,
                          height: 140,
                          fit: BoxFit.contain,
                          semanticLabel: order.estado == 'listo'
                              ? 'Pedido listo para recoger'
                              : 'Pedido en preparación'))),
            Text(order.numero,
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            Text(order.estadoTexto,
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: order.estado == 'listo'
                        ? Colors.green.shade800
                        : null)),
            for (final item in order.items)
              ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(item.nombre),
                  subtitle: Text('Cantidad: ${item.cantidad}'),
                  trailing: Text(precio(item.importe))),
            Desglose(
                subtotal: order.subtotal, iva: order.iva, total: order.total),
            if (activo && order.puedeCancelar) ...[
              const SizedBox(height: 12),
              OutlinedButton(
                  onPressed: busy ? null : () => _cancelar(order),
                  child: const Text('Cancelar pedido'))
            ],
            if (activo && order.estado == 'listo')
              const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Text(
                      'Pasa a recogerlo en caja. Para cancelarlo, acércate al cajero.')),
            if (activo)
              Container(
                  margin: const EdgeInsets.only(top: 12),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                      color: const Color(0xFFFFF4DF),
                      borderRadius: BorderRadius.circular(8)),
                  child: const Text(
                      'Si pasan más de 20 minutos desde que tu pedido esté listo y no lo recoges, '
                      'el personal puede cancelarlo. Si se cancela, ya no podrás recogerlo.'))
          ])));
  @override
  Widget build(BuildContext c) {
    final p = c.watch<CafeteriaProvider>();
    return Scaffold(
        appBar: AppBar(
            title: Text(widget.soloActivo ? 'Pedido activo' : 'Mis pedidos')),
        body: RefreshIndicator(
            onRefresh: p.refrescar,
            child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(12),
                children: [
                  if (p.errorEstado != null)
                    Padding(
                        padding: const EdgeInsets.all(12),
                        child:
                            Text(p.errorEstado!, textAlign: TextAlign.center)),
                  if (p.pedidoActivo == null)
                    const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('No tienes un pedido activo.',
                            textAlign: TextAlign.center))
                  else
                    _pedido(p.pedidoActivo!, true, p.operando),
                  if (!widget.soloActivo && p.historial.isNotEmpty) ...[
                    Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text('Pedidos anteriores',
                            style: Theme.of(c).textTheme.titleMedium)),
                    for (final order in p.historial)
                      _pedido(order, false, p.operando)
                  ],
                  TextButton(
                      onPressed: () => unawaited(p.refrescar()),
                      child: const Text('Actualizar'))
                ])));
  }
}
