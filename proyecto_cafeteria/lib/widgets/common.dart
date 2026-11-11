import 'dart:convert';
import 'package:flutter/material.dart';
import '../models/producto.dart';

void mensaje(BuildContext c, Object e) =>
    ScaffoldMessenger.of(c).showSnackBar(SnackBar(content: Text(e.toString())));
String? validarCorreo(String? v) =>
    RegExp(r'^[^\s@]+@itca\.edu\.sv$', caseSensitive: false)
            .hasMatch((v ?? '').trim())
        ? null
        : 'Usa tu correo @itca.edu.sv.';
String? validarPassword(String? v) => v != null &&
        v.length >= 8 &&
        utf8.encode(v).length <= 72 &&
        v.trim().isNotEmpty
    ? null
    : 'Usa de 8 a 72 bytes.';

class FotoProducto extends StatelessWidget {
  final String? url;
  const FotoProducto(this.url, {super.key});
  @override
  Widget build(BuildContext c) => SizedBox(
      width: 62,
      height: 62,
      child: url == null || url!.isEmpty
          ? const Icon(Icons.fastfood_outlined, size: 36)
          : ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.network(url!,
                  fit: BoxFit.cover,
                  errorBuilder: (_, e, s) =>
                      const Icon(Icons.fastfood_outlined, size: 36))));
}

class Desglose extends StatelessWidget {
  final int subtotal, iva, total;
  const Desglose(
      {super.key,
      required this.subtotal,
      required this.iva,
      required this.total});
  @override
  Widget build(BuildContext c) => Column(children: [
        _fila('Precio sin IVA', subtotal),
        const SizedBox(height: 6),
        _fila('IVA incluido (13 %)', iva),
        const Divider(),
        _fila('Total con IVA', total, bold: true)
      ]);
  Widget _fila(String t, int n, {bool bold = false}) =>
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
            child: Text(t,
                style: TextStyle(
                    fontWeight: bold ? FontWeight.bold : FontWeight.normal))),
        const SizedBox(width: 12),
        Text(precio(n),
            style: TextStyle(
                fontWeight: bold ? FontWeight.bold : FontWeight.normal))
      ]);
}
