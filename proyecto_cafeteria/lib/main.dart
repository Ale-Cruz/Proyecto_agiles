import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/cafeteria_provider.dart';
import 'screens/login_screen.dart';
import 'screens/register_screen.dart';
import 'screens/recovery_screen.dart';
import 'screens/home_screen.dart';
import 'screens/cart_screen.dart';
import 'screens/order_status_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  final CafeteriaProvider? provider;
  const MyApp({super.key, this.provider});
  @override
  Widget build(BuildContext c) => ChangeNotifierProvider(
      create: (_) => provider ?? (CafeteriaProvider()..inicializar()),
      child: const _Application());
}

class _Application extends StatefulWidget {
  const _Application();
  @override
  State<_Application> createState() => _ApplicationState();
}

class _ApplicationState extends State<_Application>
    with WidgetsBindingObserver {
  final _messenger = GlobalKey<ScaffoldMessengerState>();
  CafeteriaProvider? _provider;
  int _notice = 0;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final p = context.read<CafeteriaProvider>();
    if (_provider != p) {
      _provider?.removeListener(_notification);
      _provider = p;
      p.addListener(_notification);
    }
  }

  void _notification() {
    final p = _provider!;
    if (p.avisoVersion > _notice && p.avisoPedido != null) {
      _notice = p.avisoVersion;
      final t = p.avisoPedido!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted)
          _messenger.currentState?.showSnackBar(
              SnackBar(content: Text(t), duration: const Duration(seconds: 8)));
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) =>
      _provider?.setForeground(s == AppLifecycleState.resumed);
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _provider?.removeListener(_notification);
    super.dispose();
  }

  @override
  Widget build(BuildContext c) => MaterialApp(
          title: 'Cafetería ITCA',
          debugShowCheckedModeBanner: false,
          scaffoldMessengerKey: _messenger,
          theme: ThemeData(
              colorScheme:
                  ColorScheme.fromSeed(seedColor: const Color(0xFF800000)),
              scaffoldBackgroundColor: const Color(0xFFF7F5F0),
              appBarTheme: const AppBarTheme(
                  backgroundColor: Color(0xFF800000),
                  foregroundColor: Colors.white),
              inputDecorationTheme:
                  const InputDecorationTheme(border: OutlineInputBorder())),
          home: const _Inicio(),
          routes: {
            '/login': (_) => const LoginScreen(),
            '/register': (_) => const RegisterScreen(),
            '/recovery': (_) => const RecoveryScreen(),
            '/home': (_) => const _Acceso(guest: true, child: HomeScreen()),
            '/cart': (_) => const _Acceso(child: CartScreen()),
            '/active_order': (_) =>
                const _Acceso(child: OrderStatusScreen(soloActivo: true)),
            '/order_status': (_) => const _Acceso(child: OrderStatusScreen())
          });
}

class _Inicio extends StatelessWidget {
  const _Inicio();
  @override
  Widget build(BuildContext c) {
    final p = c.watch<CafeteriaProvider>();
    if (p.inicializando)
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (p.errorInicio != null)
      return Scaffold(
          body: Center(
              child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(p.errorInicio!, textAlign: TextAlign.center),
                    FilledButton(
                        onPressed: () => unawaited(p.inicializar()),
                        child: const Text('Reintentar'))
                  ]))));
    return p.autenticado || p.esInvitado
        ? const HomeScreen()
        : const LoginScreen();
  }
}

class _Acceso extends StatelessWidget {
  final Widget child;
  final bool guest;
  const _Acceso({required this.child, this.guest = false});
  @override
  Widget build(BuildContext c) {
    final p = c.watch<CafeteriaProvider>();
    return p.autenticado || (guest && p.esInvitado)
        ? child
        : const LoginScreen();
  }
}
