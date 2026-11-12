import 'dart:async';

import 'package:flutter/material.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_page.dart';
import 'voice_settings.dart';
import 'workbench.dart';

void main() => runApp(const SageVoiceApp());

enum VoiceView { voice, workbench, settings }

class SageVoiceApp extends StatefulWidget {
  const SageVoiceApp({super.key});

  @override
  State<SageVoiceApp> createState() => _SageVoiceAppState();
}

class _SageVoiceAppState extends State<SageVoiceApp> {
  bool dark = false;

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
    themeMode: dark ? ThemeMode.dark : ThemeMode.light,
    home: VoiceScreen(
      dark: dark,
      onToggleTheme: () => setState(() => dark = !dark),
    ),
  );
}

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({
    super.key,
    required this.dark,
    required this.onToggleTheme,
  });

  final bool dark;
  final VoidCallback onToggleTheme;

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
                title: const Text('开始新对话？'),
                content: const Text('当前聊天内容将被清除。'),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消'),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('开始新对话'),
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
            backLabel: previousView == VoiceView.voice ? '返回语音' : '返回工作台',
            onBack: () => navigate(previousView),
          ),
        },
      ),
    ),
  );
}
