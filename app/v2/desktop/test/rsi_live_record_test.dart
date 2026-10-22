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
      );
  final String runId;
  Map<String, Object?>? latest;
  int seen = 0;
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async {
    final value = await super.rsiHistory(agentId);
    return {
      ...value,
      'runs': (value['runs'] as List)
          .where((r) => (r as Map)['id'] == runId)
          .toList(),
    };
  }

  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String id, {
    int afterSequence = 0,
  }) async {
    final value = await super.rsiRun(agentId, id, afterSequence: afterSequence);
    if (id == runId) {
      latest = value;
      for (final event in value['events'] as List? ?? []) {
        final sequence = ((event as Map)['sequence'] as num?)?.toInt() ?? 0;
        if (sequence > seen) seen = sequence;
      }
    }
    return value;
  }

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
        HttpOverrides.global = previous;
        await tester.binding.setSurfaceSize(null);
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
        controller.dispose();
        api.close();
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

      for (var i = 0; i < 100; i++) {
        await tick(const Duration(milliseconds: 400));
        if (api.latest != null &&
            api.seen >= ((api.latest!['sequence'] as num?)?.toInt() ?? 0))
          break;
      }
      expect(api.latest?['id'], setup['run_id']);
      final frames = (setup['frames'] as num?)?.toInt() ?? 1;
      final samples = <Map<String, Object?>>[];
      for (var i = 0; i < frames; i++) {
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
