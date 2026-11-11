import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/producto.dart';
import '../providers/cafeteria_provider.dart';
import '../widgets/common.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int? _categoria;
  Future<void> _agregar(Producto product) async {
    final p = context.read<CafeteriaProvider>();
    if (!p.autenticado) {
      mensaje(context, 'Inicia sesión para agregar productos.');
      return;
    }
    try {
      await p.cantidad(product.id, p.cantidadActual(product.id) + 1);
      if (mounted) mensaje(context, 'Producto agregado al carrito.');
    } catch (e) {
      if (mounted) mensaje(context, e);
      await p.refrescar();
    }
  }

  Future<void> _salir() async {
    try {
      await context.read<CafeteriaProvider>().logout();
      if (mounted)
        Navigator.pushNamedAndRemoveUntil(context, '/login', (_) => false);
    } catch (e) {
      if (mounted) mensaje(context, e);
    }
  }

  @override
  Widget build(BuildContext c) {
    final p = c.watch<CafeteriaProvider>();
    final selected =
        p.categorias.any((v) => v.id == _categoria) ? _categoria : null;
    final products = p.productos
        .where((v) => selected == null || v.categoriaId == selected)
        .toList();
    return Scaffold(
        appBar: AppBar(title: const Text('Cafetería ITCA'), actions: [
          if (p.autenticado) ...[
            IconButton(
                tooltip: 'Mis pedidos',
                onPressed: () => Navigator.pushNamed(c, '/order_status'),
                icon: const Icon(Icons.receipt_long)),
            IconButton(
                tooltip: 'Carrito',
                onPressed: () => Navigator.pushNamed(c, '/cart'),
                icon: Badge(
                    label: Text('${p.unidades}'),
                    isLabelVisible: p.unidades > 0,
                    child: const Icon(Icons.shopping_cart_outlined)))
          ],
          IconButton(
              tooltip: 'Salir',
              onPressed: p.operando ? null : _salir,
              icon: const Icon(Icons.logout))
        ]),
        body: Column(children: [
          if (p.autenticado)
            Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text('Hola, ${p.usuario!['nombre']}'))),
          if (p.pedidoActivo != null)
            Card(
                margin: const EdgeInsets.all(12),
                child: ListTile(
                    leading: const Icon(Icons.receipt_long),
                    title: Text(
                        '${p.pedidoActivo!.numero}: ${p.pedidoActivo!.estadoTexto}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.pushNamed(c, '/active_order'))),
          SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                ChoiceChip(
                    label: const Text('Todos'),
                    selected: selected == null,
                    onSelected: (_) => setState(() => _categoria = null)),
                for (final cat in p.categorias)
                  Padding(
                      padding: const EdgeInsets.only(left: 8),
                      child: ChoiceChip(
                          label: Text(cat.nombre),
                          selected: selected == cat.id,
                          onSelected: (_) =>
                              setState(() => _categoria = cat.id)))
              ])),
          if (p.errorMenu != null)
            Padding(
                padding: const EdgeInsets.all(12),
                child: Text(p.errorMenu!, textAlign: TextAlign.center)),
          Expanded(
              child: p.cargandoMenu && p.productos.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : RefreshIndicator(
                      onRefresh: p.refrescar,
                      child: ListView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          padding: const EdgeInsets.fromLTRB(12, 0, 12, 20),
                          children: [
                            if (products.isEmpty)
                              Padding(
                                  padding: const EdgeInsets.all(32),
                                  child: Column(children: [
                                    const Text(
                                        'No hay productos disponibles en esta categoría.'),
                                    TextButton(
                                        onPressed: () =>
                                            unawaited(p.refrescar()),
                                        child: const Text('Actualizar'))
                                  ])),
                            for (final product in products)
                              Card(
                                  child: Padding(
                                      padding: const EdgeInsets.all(12),
                                      child: Row(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            FotoProducto(product.imagen),
                                            const SizedBox(width: 12),
                                            Expanded(
                                                child: Column(
                                                    crossAxisAlignment:
                                                        CrossAxisAlignment
                                                            .start,
                                                    children: [
                                                  Text(product.nombre,
                                                      style: Theme.of(c)
                                                          .textTheme
                                                          .titleMedium),
                                                  if ((product.descripcion ??
                                                          '')
                                                      .isNotEmpty)
                                                    Text(product.descripcion!),
                                                  const SizedBox(height: 6),
                                                  Text(
                                                      'Precio: ${precio(product.precioCentavos)}',
                                                      style: const TextStyle(
                                                          fontWeight:
                                                              FontWeight.bold)),
                                                  const SizedBox(height: 8),
                                                  Container(
                                                      padding:
                                                          const EdgeInsets.symmetric(
                                                              horizontal: 10,
                                                              vertical: 5),
                                                      decoration: BoxDecoration(
                                                          color: product.stock > 0
                                                              ? const Color(
                                                                  0xFFE8F3EC)
                                                              : const Color(
                                                                  0xFFFBEAEA),
                                                          borderRadius:
                                                              BorderRadius
                                                                  .circular(8)),
                                                      child: Text(
                                                          product.stock > 0
                                                              ? 'Disponible'
                                                              : 'Agotado',
                                                          style: TextStyle(
                                                              color: product.stock > 0
                                                                  ? const Color(
                                                                      0xFF316B44)
                                                                  : const Color(0xFF9C4444),
                                                              fontSize: 13,
                                                              fontWeight: FontWeight.w600))),
                                                  Align(
                                                      alignment:
                                                          Alignment.centerRight,
                                                      child: FilledButton.tonal(
                                                          onPressed: p.operando ||
                                                                  product.stock <=
                                                                      0
                                                              ? null
                                                              : () => _agregar(
                                                                  product),
                                                          child: const Text(
                                                              'Agregar')))
                                                ]))
                                          ]))),
                          ])))
        ]));
  }
}
