import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/cafeteria_provider.dart';
import '../widgets/common.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _form = GlobalKey<FormState>();
  final _correo = TextEditingController();
  final _password = TextEditingController();
  bool _loading = false;
  @override
  void dispose() {
    _correo.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _entrar({bool invitado = false}) async {
    if (!invitado && !_form.currentState!.validate()) return;
    setState(() => _loading = true);
    try {
      final p = context.read<CafeteriaProvider>();
      if (invitado) {
        await p.entrarInvitado();
      } else {
        await p.login(_correo.text.trim(), _password.text);
      }
      if (mounted)
        Navigator.pushNamedAndRemoveUntil(context, '/home', (_) => false);
    } catch (e) {
      if (mounted) mensaje(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext c) => Scaffold(
      body: SafeArea(
          child: Center(
              child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 420),
                      child: Card(
                          child: Padding(
                              padding: const EdgeInsets.all(24),
                              child: AutofillGroup(
                                  child: Form(
                                      key: _form,
                                      child: Column(
                                          mainAxisSize: MainAxisSize.min,
                                          crossAxisAlignment:
                                              CrossAxisAlignment.stretch,
                                          children: [
                                            const Icon(Icons.coffee_rounded,
                                                size: 64,
                                                color: Color(0xFF800000)),
                                            const SizedBox(height: 12),
                                            Text('Cafetería ITCA',
                                                textAlign: TextAlign.center,
                                                style: Theme.of(c)
                                                    .textTheme
                                                    .headlineSmall),
                                            const SizedBox(height: 24),
                                            TextFormField(
                                                controller: _correo,
                                                enabled: !_loading,
                                                keyboardType:
                                                    TextInputType.emailAddress,
                                                autofillHints: const [
                                                  AutofillHints.username
                                                ],
                                                decoration: const InputDecoration(
                                                    labelText:
                                                        'Correo institucional'),
                                                validator: validarCorreo),
                                            const SizedBox(height: 16),
                                            TextFormField(
                                                controller: _password,
                                                enabled: !_loading,
                                                obscureText: true,
                                                autofillHints: const [
                                                  AutofillHints.password
                                                ],
                                                decoration:
                                                    const InputDecoration(
                                                        labelText:
                                                            'Contraseña'),
                                                validator: (v) => v == null ||
                                                        v.isEmpty
                                                    ? 'Ingresa tu contraseña.'
                                                    : null,
                                                onFieldSubmitted: (_) {
                                                  if (!_loading) _entrar();
                                                }),
                                            const SizedBox(height: 20),
                                            FilledButton(
                                                onPressed: _loading
                                                    ? null
                                                    : () => _entrar(),
                                                child: Text(_loading
                                                    ? 'Ingresando…'
                                                    : 'Ingresar')),
                                            OutlinedButton(
                                                onPressed: _loading
                                                    ? null
                                                    : () =>
                                                        _entrar(invitado: true),
                                                child: const Text(
                                                    'Ver menú como invitado')),
                                            Wrap(
                                                alignment: WrapAlignment.center,
                                                children: [
                                                  TextButton(
                                                      onPressed: _loading
                                                          ? null
                                                          : () => Navigator
                                                              .pushNamed(c,
                                                                  '/register'),
                                                      child: const Text(
                                                          'Registrarse')),
                                                  TextButton(
                                                      onPressed: _loading
                                                          ? null
                                                          : () => Navigator
                                                              .pushNamed(c,
                                                                  '/recovery'),
                                                      child: const Text(
                                                          'Recuperar contraseña'))
                                                ])
                                          ]))))))))));
}
