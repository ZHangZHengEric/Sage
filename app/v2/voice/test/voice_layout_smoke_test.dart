import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_voice/voice_engine.dart';
import 'package:sage_voice/voice_page.dart';
import 'package:sage_voice/voice_settings.dart';
import 'package:sage_voice/workbench.dart';

void noop() {}

void main() {
  testWidgets(
    'Sage Voice views fit the minimum window and expose their controls',
    (tester) async {
      tester.view.physicalSize = const Size(720, 520);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final engine = VoiceEngine()..state = VoiceState.idle;
      Future<void> show(Widget page) => tester.pumpWidget(
        MaterialApp(
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
      expect(find.byTooltip('切换至工作台'), findsOneWidget);
      expect(tester.takeException(), isNull);

      await show(
        VoiceWorkbench(
          engine: engine,
          dark: false,
          onToggleTheme: noop,
          onVoice: noop,
          onToggle: noop,
          onSettings: noop,
          onNew: noop,
        ),
      );
      await tester.tap(find.text('监控'));
      await tester.pump();
      expect(find.text('麦克风输入'), findsOneWidget);
      await tester.tap(find.text('运行事件'));
      await tester.pump();
      expect(find.text('暂无运行事件'), findsOneWidget);
      expect(tester.takeException(), isNull);

      await show(
        VoiceSettings(engine: engine, backLabel: '返回语音', onBack: noop),
      );
      await tester.tap(find.text('智能体'));
      await tester.pump();
      expect(find.text('模型配置'), findsOneWidget);
      await tester.tap(find.text('语音合成'));
      await tester.pump();
      expect(find.text('音色 ID（可选）'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      engine.dispose();
    },
  );
}
