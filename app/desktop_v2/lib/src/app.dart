import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'localization/app_localizations.dart';
import 'state/workspace_controller.dart';
import 'ui/workspace_screen.dart';
import 'ui/workspace_panels/workspace_panel_plugin.dart';

class SageDesktopV2App extends StatefulWidget {
  const SageDesktopV2App({
    super.key,
    this.controller,
    this.panelPlugins = const [],
    this.panelDockController,
  });

  final WorkspaceController? controller;
  final List<WorkspacePanelPlugin> panelPlugins;
  final WorkspacePanelDockController? panelDockController;

  @override
  State<SageDesktopV2App> createState() => _SageDesktopV2AppState();
}

class _SageDesktopV2AppState extends State<SageDesktopV2App> {
  late final WorkspaceController _controller =
      widget.controller ?? WorkspaceController();
  ThemeMode _themeMode = ThemeMode.system;
  String _language = 'system';

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    await _controller.initialize();
    if (!mounted) return;
    final restored = switch (_controller.settings.themeMode) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
    final language = _controller.settings.language;
    if (restored != _themeMode || language != _language) {
      setState(() {
        _themeMode = restored;
        _language = language;
      });
    }
  }

  @override
  void dispose() {
    if (widget.controller == null) _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Sage v2',
      themeMode: _themeMode,
      locale: _language == 'system' ? null : Locale(_language),
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      localizationsDelegates: const [
        SageLocalizations.delegate,
        ...GlobalMaterialLocalizations.delegates,
      ],
      supportedLocales: SageLocalizations.supportedLocales,
      home: WorkspaceScreen(
        controller: _controller,
        themeMode: _themeMode,
        onThemeModeChanged: (value) => setState(() => _themeMode = value),
        language: _language,
        onLanguageChanged: (value) => setState(() => _language = value),
        panelPlugins: widget.panelPlugins,
        panelDockController: widget.panelDockController,
      ),
    );
  }
}

ThemeData _theme(Brightness brightness) {
  const seed = Color(0xFF0A84FF);
  final scheme = ColorScheme.fromSeed(
    seedColor: seed,
    brightness: brightness,
    surface: brightness == Brightness.dark
        ? const Color(0xFF000000)
        : const Color(0xFFFFFFFF),
  );
  final base = Typography.material2021(platform: TargetPlatform.macOS).black
      .apply(
        bodyColor: scheme.onSurface,
        displayColor: scheme.onSurface,
        fontFamily: '.AppleSystemUIFont',
      );
  return ThemeData(
    useMaterial3: true,
    platform: TargetPlatform.macOS,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    dividerTheme: DividerThemeData(color: scheme.outlineVariant),
    iconTheme: IconThemeData(color: scheme.onSurface),
    textTheme: base.copyWith(
      titleLarge: base.titleLarge?.copyWith(
        fontSize: 19,
        fontWeight: FontWeight.w600,
        letterSpacing: 0,
      ),
      titleMedium: base.titleMedium?.copyWith(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        letterSpacing: 0,
      ),
      bodyMedium: base.bodyMedium?.copyWith(
        fontSize: 13.5,
        height: 1.35,
        letterSpacing: 0,
      ),
      labelLarge: base.labelLarge?.copyWith(
        fontSize: 12,
        fontWeight: FontWeight.w600,
        letterSpacing: 0,
      ),
      labelMedium: base.labelMedium?.copyWith(fontSize: 11.5, letterSpacing: 0),
    ),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
      filled: true,
      fillColor: scheme.surfaceContainerHighest.withValues(alpha: 0.28),
    ),
  );
}
