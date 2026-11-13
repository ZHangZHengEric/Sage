import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
        engine.tools = [
          {
            'name': 'list_dir',
            'available': true,
            'description': {'zh': '列出目录。', 'en': 'List a directory.'},
            'input_schema': {
              for (final language in ['zh', 'en'])
                language: {
                  'properties': {
                    'path': {'type': 'string'},
                  },
                },
            },
            'speech': {'zh': '我在查看目录。', 'en': 'Checking the directory.'},
          },
          {
            'name': 'file_read',
            'available': true,
            'description': {'zh': '读取文件。', 'en': 'Read a file.'},
            'input_schema': {
              for (final language in ['zh', 'en'])
                language: {
                  'properties': {
                    'file_path': {'type': 'string'},
                  },
                  'required': ['file_path'],
                },
            },
            'speech': {},
          },
        ];
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

        Locale? selectedLocale;
        await show(
          VoiceSettings(
            engine: engine,
            backLabel: label('返回语音', 'Back to Voice'),
            onBack: noop,
            onLanguageChanged: (locale) => selectedLocale = locale,
          ),
        );
        await tester.tap(find.text(label('界面语言', 'Interface language')));
        await tester.pumpAndSettle();
        expect(find.text(label('跟随系统', 'System default')), findsOneWidget);
        expect(find.text('简体中文'), findsOneWidget);
        await tester.tap(find.text('English'));
        await tester.pumpAndSettle();
        expect(selectedLocale, const Locale('en'));
        final help = find.text(label('如何获取 API Key', 'How to get an API key'));
        final close = find.text(label('关闭', 'Close'));
        String? openedUrl;
        const platform = MethodChannel('sage.voice/preferences');
        final messenger = tester.binding.defaultBinaryMessenger;
        messenger.setMockMethodCallHandler(platform, (call) async {
          expect(call.method, 'openHelpLink');
          openedUrl = call.arguments as String;
          return true;
        });
        addTearDown(() => messenger.setMockMethodCallHandler(platform, null));
        await tester.tap(help);
        await tester.pumpAndSettle();
        expect(find.text('qwen-audio-3.0-asr-flash-streaming'), findsOneWidget);
        await tester.tap(close);
        await tester.pumpAndSettle();
        await tester.tap(find.text(label('火山引擎语音', 'Volcengine')));
        await tester.pumpAndSettle();
        await tester.tap(
          find.text(label('语音合成', 'Speech synthesis')).hitTestable().first,
        );
        await tester.pump();
        expect(
          find.text(label('音色 ID（可选）', 'Voice ID (optional)')),
          findsOneWidget,
        );
        await tester.tap(help);
        await tester.pumpAndSettle();
        expect(find.text('seed-tts-2.0'), findsOneWidget);
        expect(find.text('zh_female_vv_uranus_bigtts'), findsOneWidget);
        await tester.tap(
          find.text(label('豆包语音 API Key 控制台', 'Doubao Voice API keys')),
        );
        await tester.pumpAndSettle();
        expect(
          openedUrl,
          'https://console.volcengine.com/speech/new/setting/apikeys',
        );
        await tester.tap(close);
        await tester.pumpAndSettle();
        await tester.tap(find.text(label('智能体', 'Agent')).hitTestable().first);
        await tester.pump();
        expect(find.text('Base URL'), findsOneWidget);
        await tester.tap(help);
        await tester.pumpAndSettle();
        expect(
          find.text(label('OpenAI 模型目录', 'OpenAI model catalog')),
          findsOneWidget,
        );
        await tester.tap(close);
        await tester.pumpAndSettle();
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
        final reasoning = find.byType(DropdownMenu<String>);
        await tester.tap(
          find.descendant(of: reasoning, matching: find.byType(TextField)),
        );
        await tester.pumpAndSettle();
        await tester.tap(
          find.widgetWithText(MenuItemButton, label('高', 'High')),
        );
        await tester.pumpAndSettle();
        expect(
          tester.widget<DropdownMenu<String>>(reasoning).initialSelection,
          'high',
        );
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
        final listDir = find.widgetWithText(
          ExpansionTile,
          label('查看目录', 'List directory'),
        );
        final fileRead = find.widgetWithText(
          ExpansionTile,
          label('读取文件', 'Read file'),
        );
        Finder toggle(Finder row) =>
            find.descendant(of: row, matching: find.byType(Switch)).first;
        expect(tester.widget<Switch>(toggle(listDir)).value, isFalse);
        await tester.tap(toggle(listDir));
        await tester.pump();
        expect(tester.widget<Switch>(toggle(listDir)).value, isTrue);
        expect(tester.widget<Switch>(toggle(fileRead)).value, isFalse);
        await tester.tap(find.text(label('查看目录', 'List directory')));
        await tester.pumpAndSettle();
        expect(find.text('path'), findsOneWidget);
        expect(
          find.text(label('工具进度播报', 'Tool announcements')),
          findsOneWidget,
        );
        await tester.tap(find.text(label('查看目录', 'List directory')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(label('读取文件', 'Read file')));
        await tester.pumpAndSettle();
        expect(find.text('file_path'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        engine.dispose();
      },
    );
  }
}
