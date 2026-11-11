int centavos(dynamic value) {
  final text = value.toString();
  final parts = text.split('.');
  final fraction = (parts.length > 1 ? parts[1] : '').padRight(2, '0');
  return int.parse(parts[0]) * 100 + int.parse(fraction.substring(0, 2));
}

String decimal(int value) =>
    '${value ~/ 100}.${(value % 100).toString().padLeft(2, '0')}';
String precio(int value) => '\$${decimal(value)}';

class Producto {
  final int id;
  final String nombre;
  final String? descripcion;
  final int precioCentavos;
  final int sinIvaCentavos;
  final int stock;
  final int categoriaId;
  final String categoria;
  final String? imagen;
  final bool habilitado;

  const Producto(
      {required this.id,
      required this.nombre,
      this.descripcion,
      required this.precioCentavos,
      required this.sinIvaCentavos,
      required this.stock,
      required this.categoriaId,
      required this.categoria,
      this.imagen,
      required this.habilitado});

  factory Producto.fromJson(Map<String, dynamic> json) => Producto(
      id: json['id'] as int,
      nombre: json['nombre'] as String,
      descripcion: json['descripcion'] as String?,
      precioCentavos: centavos(json['precio']),
      sinIvaCentavos: centavos(json['precio_sin_iva']),
      stock: json['stock'] as int,
      categoriaId: json['categoria_id'] as int,
      categoria: json['categoria'] as String,
      imagen: json['imagen'] as String?,
      habilitado: json['habilitado'] as bool);
}

class Categoria {
  final int id;
  final String nombre;
  const Categoria(this.id, this.nombre);
  factory Categoria.fromJson(Map<String, dynamic> json) =>
      Categoria(json['id'] as int, json['nombre'] as String);
}
