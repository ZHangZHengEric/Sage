// Opt-in read-only recording of a real Desktop RSI run; no inference is mocked.
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/localization/app_localizations.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';

class RecordingApi extends V2ApiClient {
  RecordingApi(Map setup)
    : runId = setup['run_id'] as String,
      super(
        baseUri: Uri.parse(setup['url'] as String),
        authToken: setup['auth_token'] as String,
        httpClient: HttpClient()..findProxy = (_) => 'DIRECT',
      );
  final String runId;
  Map<String, Object?>? latest;
  int seen = 0;
  int pending = 0;
  Future<Map<String, Object?>> read(
    Future<Map<String, Object?>> Function() request,
  ) async {
    pending++;
    try {
      return await request();
    } finally {
      pending--;
    }
  }

  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) => read(() async {
    final value = await super.rsiHistory(agentId);
    return {
      ...value,
      'runs': (value['runs'] as List)
          .where((r) => (r as Map)['id'] == runId)
          .toList(),
    };
  });

  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String id, {
    int afterSequence = 0,
  }) => read(() async {
    final value = await super.rsiRun(agentId, id, afterSequence: afterSequence);
    if (id == runId) {
      latest = value;
      for (final event in value['events'] as List? ?? []) {
        final sequence = ((event as Map)['sequence'] as num?)?.toInt() ?? 0;
        if (sequence > seen) seen = sequence;
      }
    }
    return value;
  });

  @override
  Future<Map<String, Object?>> startRsi(
    String agentId,
    Map<String, Object?> body,
  ) => throw StateError('Recording is read-only');
  @override
  Future<void> applyRsiVersion(
    String agentId,
    String versionId,
    String fingerprint,
  ) => throw StateError('Recording is read-only');
}

void main() {
  final ready = Platform.environment['RSI_RECORD_READY'];
  if (ready != null) {
    LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
        LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  }
  setUpAll(() async {
    if (ready == null) return;
    final setup = jsonDecode(File(ready).readAsStringSync()) as Map;
    final font = File(setup['font_path'] as String).readAsBytesSync();
    await (FontLoader(
      'SageRecording',
    )..addFont(Future.value(ByteData.sublistView(font)))).load();
    final mono = File(
      (setup['mono_font_path'] ?? setup['font_path']) as String,
    ).readAsBytesSync();
    await (FontLoader(
      'monospace',
    )..addFont(Future.value(ByteData.sublistView(mono)))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
    await (FontLoader('packages/cupertino_icons/CupertinoIcons')..addFont(
          rootBundle.load('packages/cupertino_icons/assets/CupertinoIcons.ttf'),
        ))
        .load();
    await LiquidGlassWidgets.initialize();
  });
  testWidgets(
    'record an actual RSI run without changing it',
    (tester) async {
      final setup = jsonDecode(File(ready!).readAsStringSync()) as Map;
      final out = Directory(setup['output'] as String)
        ..createSync(recursive: true);
      final previous = HttpOverrides.current;
      HttpOverrides.global = null;
      final api = RecordingApi(setup);
      final controller = WorkspaceController(api: api);
      await tester.binding.setSurfaceSize(const Size(1920, 1080));
      tester.view.physicalSize = const Size(1920, 1080);
      tester.view.devicePixelRatio = 1;
      addTearDown(() async {
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.runAsync(() async {
          final deadline = DateTime.now().add(const Duration(seconds: 15));
          while (api.pending > 0 && DateTime.now().isBefore(deadline)) {
            await Future<void>.delayed(const Duration(milliseconds: 20));
          }
          expect(api.pending, 0);
        });
        await tester.binding.setSurfaceSize(null);
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
        controller.dispose();
        api.close();
        HttpOverrides.global = previous;
      });
      final brightness = setup['theme'] == 'light'
          ? Brightness.light
          : Brightness.dark;
      await tester.pumpWidget(
        LiquidGlassWidgets.wrap(
          adaptiveQuality: false,
          child: RepaintBoundary(
            key: const ValueKey('recording'),
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: sageDesktopTheme(brightness).copyWith(
                textTheme: sageDesktopTheme(
                  brightness,
                ).textTheme.apply(fontFamily: 'SageRecording'),
              ),
              locale: const Locale('zh'),
              supportedLocales: SageLocalizations.supportedLocales,
              localizationsDelegates: const [
                SageLocalizations.delegate,
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              home: RsiScreen(
                controller: controller,
                agentId: setup['agent_id'] as String,
                agentName: setup['agent_name'] as String,
              ),
            ),
          ),
        ),
      );
      Future<void> tick(Duration time) async {
        await tester.runAsync(() => Future<void>.delayed(time));
        await tester.pump();
        expect(tester.takeException(), isNull);
      }

      var synchronized = false;
      for (var i = 0; i < 450; i++) {
        await tick(const Duration(milliseconds: 400));
        if (api.latest != null &&
            api.seen >= ((api.latest!['sequence'] as num?)?.toInt() ?? 0)) {
          synchronized = true;
          break;
        }
      }
      expect(api.latest?['id'], setup['run_id']);
      expect(
        synchronized,
        isTrue,
        reason: 'Load the actual journal before recording',
      );
      if (setup['selected_round'] is num) {
        final round = (setup['selected_round'] as num).toInt();
        final choice = find.widgetWithText(
          ChoiceChip,
          round == 0 ? '基线轮' : '第 $round 轮',
        );
        expect(choice, findsOneWidget);
        if (choice.hitTestable().evaluate().isEmpty) {
          await tester.ensureVisible(choice);
        }
        await tester.tap(choice);
        await tick(const Duration(milliseconds: 400));
        expect(tester.widget<ChoiceChip>(choice).selected, isTrue);
      }
      if (setup['show_library'] == true) {
        final library = find.byKey(const ValueKey('rsi-open-suite'));
        await tester.ensureVisible(library);
        await tester.tap(library);
        await tick(const Duration(milliseconds: 500));
        expect(find.byType(DataTable), findsOneWidget);
      }
      final frames = (setup['frames'] as num?)?.toInt() ?? 1;
      final samples = <Map<String, Object?>>[];
      for (var i = 0; i < frames; i++) {
        if (i == 60 && setup['show_diff_round'] is num) {
          final round = (setup['show_diff_round'] as num).toInt();
          final changes = find.byKey(ValueKey('rsi-round-diff-$round'));
          expect(changes, findsOneWidget);
          await tester.ensureVisible(changes);
          await tester.tap(changes);
          await tick(const Duration(milliseconds: 500));
          expect(find.byKey(const ValueKey('rsi-diff-files')), findsOneWidget);
        }
        if (i == 75 &&
            setup['show_diff_round'] is num &&
            setup['diff_file'] is num) {
          final index = (setup['diff_file'] as num).toInt();
          final file = find.byKey(ValueKey('rsi-diff-file-$index'));
          expect(file, findsOneWidget);
          await tester.ensureVisible(file);
          await tester.tap(file);
          await tick(const Duration(milliseconds: 300));
        }
        if (i == 40 || i == 100) {
          final scrolls = find.byType(Scrollable);
          if (scrolls.evaluate().isNotEmpty) {
            await tester.drag(scrolls.first, const Offset(0, -420));
            await tester.pump(const Duration(milliseconds: 300));
          }
        }
        await tick(const Duration(milliseconds: 250));
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('recording')),
        );
        final image = await boundary.toImage(pixelRatio: 1);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        File(
          '${out.path}/frame-${i.toString().padLeft(5, '0')}.png',
        ).writeAsBytesSync(data!.buffer.asUint8List());
        image.dispose();
        samples.add({
          'frame': i,
          'time': DateTime.now().toIso8601String(),
          'sequence': api.latest?['sequence'],
          'seen': api.seen,
          'status': api.latest?['status'],
          'iteration': api.latest?['iteration'],
          'stage': api.latest?['stage'],
        });
      }
      File('${out.path}/recording.json').writeAsStringSync(
        jsonEncode({
          'run_id': setup['run_id'],
          'theme': brightness.name,
          'frames_per_second': 4,
          'mode': 'actual API data; read-only Flutter rendering',
          'samples': samples,
        }),
      );
    },
    skip: ready == null,
    timeout: const Timeout(Duration(minutes: 8)),
  );
}
