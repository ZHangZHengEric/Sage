import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_locale.dart';
import 'voice_page.dart';
import 'voice_settings.dart';
import 'workbench.dart';

const preferences = MethodChannel('sage.voice/preferences');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await LiquidGlassWidgets.initialize(enablePerformanceMonitor: false);
  final language = await preferences.invokeMethod<String>('getLanguage');
  runApp(
    SageVoiceApp(initialLocale: language == null ? null : Locale(language)),
  );
}

enum VoiceView { voice, workbench, settings }

class SageVoiceApp extends StatefulWidget {
  const SageVoiceApp({super.key, this.initialLocale});

  final Locale? initialLocale;

  @override
  State<SageVoiceApp> createState() => _SageVoiceAppState();
}

class _SageVoiceAppState extends State<SageVoiceApp> {
  late Locale? locale = widget.initialLocale;
  bool? darkOverride;

  void setLanguage(Locale? value) {
    setState(() => locale = value);
    unawaited(
      preferences.invokeMethod<void>('setLanguage', value?.languageCode),
    );
  }

  ThemeData theme(Brightness brightness) {
    final colors = ColorScheme.fromSeed(
      seedColor: const Color(0xff6c66df),
      brightness: brightness,
      surface: brightness == Brightness.light
          ? Colors.white
          : const Color(0xff17171b),
    );
    return ThemeData(
      colorScheme: colors,
      scaffoldBackgroundColor: colors.surface,
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        isDense: true,
      ),
    );
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: sageVoiceName,
    debugShowCheckedModeBanner: false,
    theme: theme(Brightness.light),
    darkTheme: theme(Brightness.dark),
    locale: locale,
    supportedLocales: const [Locale('en'), Locale('zh')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    themeMode: switch (darkOverride) {
      true => ThemeMode.dark,
      false => ThemeMode.light,
      null => ThemeMode.system,
    },
    home: Builder(
      builder: (context) {
        final dark = Theme.of(context).brightness == Brightness.dark;
        return VoiceScreen(
          dark: dark,
          onToggleTheme: () => setState(() => darkOverride = !dark),
          onLanguageChanged: setLanguage,
        );
      },
    ),
  );
}

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({
    super.key,
    required this.dark,
    required this.onToggleTheme,
    required this.onLanguageChanged,
  });

  final bool dark;
  final VoidCallback onToggleTheme;
  final ValueChanged<Locale?> onLanguageChanged;

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  final engine = VoiceEngine();
  VoiceView view = VoiceView.voice;
  VoiceView previousView = VoiceView.voice;

  @override
  void initState() {
    super.initState();
    unawaited(engine.connect());
  }

  @override
  void dispose() {
    engine.dispose();
    super.dispose();
  }

  void navigate(VoiceView next) => setState(() => view = next);

  void settings() {
    previousView = view;
    navigate(VoiceView.settings);
  }

  Future<void> toggle() async {
    if (!engine.connected) {
      await engine.connect();
    } else if (engine.settings == null) {
      settings();
    } else {
      await engine.toggle();
    }
  }

  Future<void> newConversation() async {
    final confirmed =
        engine.conversation.isEmpty ||
        await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: Text(context.tr('开始新对话？', 'Start a new conversation?')),
                content: Text(
                  context.tr(
                    '当前聊天内容将被清除。',
                    'This will clear the current conversation.',
                  ),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: Text(context.tr('取消', 'Cancel')),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: Text(context.tr('开始新对话', 'New conversation')),
                  ),
                ],
              ),
            ) ==
            true;
    if (mounted && confirmed) await engine.newConversation();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: engine,
    builder: (context, _) => Scaffold(
      body: SafeArea(
        child: switch (view) {
          VoiceView.voice => VoicePage(
            engine: engine,
            onToggle: toggle,
            onSettings: settings,
            onNew: newConversation,
            onWorkbench: () => navigate(VoiceView.workbench),
          ),
          VoiceView.workbench => VoiceWorkbench(
            engine: engine,
            dark: widget.dark,
            onToggleTheme: widget.onToggleTheme,
            onVoice: () => navigate(VoiceView.voice),
            onToggle: toggle,
            onSettings: settings,
            onNew: newConversation,
          ),
          VoiceView.settings => VoiceSettings(
            engine: engine,
            backLabel: previousView == VoiceView.voice
                ? context.tr('返回语音', 'Back to Voice')
                : context.tr('返回工作台', 'Back to Workbench'),
            onLanguageChanged: widget.onLanguageChanged,
            onBack: () => navigate(previousView),
          ),
        },
      ),
    ),
  );
}
