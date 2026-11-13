import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_voice/voice_engine.dart';
import 'package:sage_voice/voice_page.dart';
import 'package:sage_voice/voice_settings.dart';
import 'package:sage_voice/workbench.dart';

void noop() {}

void main() {
  for (final (language, brightness) in [
    ('zh', Brightness.light),
    ('zh', Brightness.dark),
    ('en', Brightness.light),
    ('en', Brightness.dark),
  ]) {
    final chinese = language == 'zh';
    String label(String zh, String en) => chinese ? zh : en;
    testWidgets(
      'Sage Voice fits the minimum window in $language and $brightness',
      (tester) async {
        tester.view.physicalSize = const Size(720, 520);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final engine = VoiceEngine()..state = VoiceState.idle;
        Future<void> show(Widget page) => tester.pumpWidget(
          MaterialApp(
            locale: Locale(language),
            supportedLocales: const [Locale('en'), Locale('zh')],
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: MediaQuery(
                data: const MediaQueryData(disableAnimations: true),
                child: page,
              ),
            ),
          ),
        );

        await show(
          VoicePage(
            engine: engine,
            onToggle: noop,
            onSettings: noop,
            onNew: noop,
            onWorkbench: noop,
          ),
        );
        await tester.pump();
        expect(find.text('Sage Voice'), findsOneWidget);
        expect(
          find.byTooltip(label('切换至工作台', 'Open workbench')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);

        await show(
          VoiceWorkbench(
            engine: engine,
            dark: brightness == Brightness.dark,
            onToggleTheme: noop,
            onVoice: noop,
            onToggle: noop,
            onSettings: noop,
            onNew: noop,
          ),
        );
        await tester.tap(find.byTooltip(label('监控', 'Monitor')));
        await tester.pump();
        expect(find.text(label('麦克风输入', 'Microphone input')), findsOneWidget);
        await tester.tap(find.text(label('运行事件', 'Runtime events')));
        await tester.pump();
        expect(find.text(label('暂无运行事件', 'No runtime events')), findsOneWidget);
        expect(tester.takeException(), isNull);

        await show(
          VoiceSettings(engine: engine, backLabel: '返回语音', onBack: noop),
        );
        await tester.tap(
          find.text(label('语音合成', 'Speech synthesis')).hitTestable().first,
        );
        await tester.pump();
        expect(
          find.text(label('音色 ID（可选）', 'Voice ID (optional)')),
          findsOneWidget,
        );
        await tester.tap(find.text(label('智能体', 'Agent')).hitTestable().first);
        await tester.pump();
        expect(find.text('Base URL'), findsOneWidget);
        final generation = find.widgetWithText(
          ListTile,
          label('生成参数', 'Generation'),
        );
        final prompt = find.widgetWithText(
          ListTile,
          label('系统提示词', 'System prompt'),
        );
        await tester.tap(generation);
        await tester.pump();
        expect(find.text(label('思考强度', 'Reasoning effort')), findsOneWidget);
        expect(find.text('Base URL'), findsNothing);
        await tester.tap(prompt);
        await tester.pump();
        await tester.enterText(find.byType(TextField), 'Test voice prompt');
        await tester.tap(generation);
        await tester.pump();
        await tester.tap(prompt);
        await tester.pump();
        expect(find.text('Test voice prompt'), findsOneWidget);
        await tester.tap(find.widgetWithText(ListTile, label('工具', 'Tools')));
        await tester.pump();
        expect(
          find.text(label('工具进度播报', 'Tool announcements')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        engine.dispose();
      },
    );
  }
}
