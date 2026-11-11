import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/cafeteria_provider.dart';
import '../widgets/common.dart';

class VerificationScreen extends StatefulWidget {
  final bool registro;
  const VerificationScreen({super.key, required this.registro});
  @override
  State<VerificationScreen> createState() => _VerificationScreenState();
}

class _VerificationScreenState extends State<VerificationScreen> {
  final _form = GlobalKey<FormState>();
  final _nombre = TextEditingController();
  final _correo = TextEditingController();
  final _password = TextEditingController();
  final _codigo = TextEditingController();
  bool _enviado = false, _loading = false;
  @override
  void dispose() {
    for (final c in [_nombre, _correo, _password, _codigo]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _enviar({bool reenviar = false}) async {
    if (!reenviar && !_form.currentState!.validate()) return;
    setState(() => _loading = true);
    try {
      await context
          .read<CafeteriaProvider>()
          .api
          .enviarCodigo(_correo.text.trim(), recuperar: !widget.registro);
      if (!mounted) return;
      setState(() => _enviado = true);
      mensaje(context,
          'Si el correo corresponde al proceso solicitado, recibirás un código. Revisa también el correo no deseado.');
    } catch (e) {
      if (mounted) mensaje(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verificar() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _loading = true);
    try {
      final api = context.read<CafeteriaProvider>().api;
      if (widget.registro) {
        await api.registrar(_nombre.text.trim(), _correo.text.trim(),
            _password.text, _codigo.text);
      } else {
        await api.cambiarPassword(
            _correo.text.trim(), _password.text, _codigo.text);
      }
      if (!mounted) return;
      mensaje(
          context,
          widget.registro
              ? 'Cuenta creada. Ya puedes iniciar sesión.'
              : 'Contraseña actualizada. Inicia sesión de nuevo.');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) mensaje(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext c) => Scaffold(
      appBar: AppBar(
          title: Text(widget.registro
              ? 'Registro estudiantil'
              : 'Recuperar contraseña')),
      body: SafeArea(
          child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Center(
                  child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 420),
                      child: Form(
                          key: _form,
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                if (widget.registro && !_enviado) ...[
                                  TextFormField(
                                      controller: _nombre,
                                      enabled: !_loading,
                                      maxLength: 150,
                                      decoration: const InputDecoration(
                                          labelText: 'Nombre'),
                                      validator: (v) => (v ?? '').trim().isEmpty
                                          ? 'Ingresa tu nombre.'
                                          : null),
                                  const SizedBox(height: 16)
                                ],
                                TextFormField(
                                    controller: _correo,
                                    enabled: !_loading,
                                    readOnly: _enviado,
                                    keyboardType: TextInputType.emailAddress,
                                    decoration: const InputDecoration(
                                        labelText: 'Correo @itca.edu.sv'),
                                    validator: validarCorreo),
                                const SizedBox(height: 16),
                                if ((widget.registro && !_enviado) ||
                                    (!widget.registro && _enviado)) ...[
                                  TextFormField(
                                      controller: _password,
                                      enabled: !_loading,
                                      obscureText: true,
                                      validator: validarPassword,
                                      decoration: InputDecoration(
                                          labelText: widget.registro
                                              ? 'Contraseña'
                                              : 'Nueva contraseña')),
                                  const SizedBox(height: 16)
                                ],
                                if (_enviado) ...[
                                  const Text(
                                      'Ingresa el código de 6 dígitos. Vence en 10 minutos.'),
                                  const SizedBox(height: 12),
                                  TextFormField(
                                      controller: _codigo,
                                      enabled: !_loading,
                                      keyboardType: TextInputType.number,
                                      autofillHints: const [
                                        AutofillHints.oneTimeCode
                                      ],
                                      maxLength: 6,
                                      inputFormatters: [
                                        FilteringTextInputFormatter.digitsOnly
                                      ],
                                      decoration: const InputDecoration(
                                          labelText: 'Código de verificación'),
                                      validator: (v) =>
                                          RegExp(r'^\d{6}$').hasMatch(v ?? '')
                                              ? null
                                              : 'Ingresa los 6 dígitos.')
                                ],
                                FilledButton(
                                    onPressed: _loading
                                        ? null
                                        : (_enviado
                                            ? _verificar
                                            : () => _enviar()),
                                    child: Text(_loading
                                        ? 'Procesando…'
                                        : _enviado
                                            ? 'Verificar y continuar'
                                            : 'Enviar código')),
                                if (_enviado) ...[
                                  TextButton(
                                      onPressed: _loading
                                          ? null
                                          : () => _enviar(reenviar: true),
                                      child: const Text('Reenviar código')),
                                  TextButton(
                                      onPressed: _loading
                                          ? null
                                          : () => setState(() {
                                                _enviado = false;
                                                _codigo.clear();
                                              }),
                                      child: const Text('Cambiar correo'))
                                ]
                              ])))))));
}
