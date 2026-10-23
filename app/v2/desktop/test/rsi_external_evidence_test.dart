// Opt-in: render the actual Desktop HTTP response for an external RSI run.
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';

void main() {
  final source = Platform.environment['RSI_DESKTOP_SNAPSHOT'];
  final output = Platform.environment['RSI_DESKTOP_CAPTURE'];
  setUpAll(() async {
    if (source != null && output != null) {
      await (FontLoader('SageScreenshot')..addFont(
            File(
              '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ).readAsBytes().then(ByteData.sublistView),
          ))
          .load();
      await (FontLoader('packages/cupertino_icons/CupertinoIcons')..addFont(
            rootBundle.load(
              'packages/cupertino_icons/assets/CupertinoIcons.ttf',
            ),
          ))
          .load();
    }
  });
  for (final brightness in Brightness.values) {
    testWidgets('real Desktop external RSI response ${brightness.name}', (
      tester,
    ) async {
      final run = (jsonDecode(File(source!).readAsStringSync()) as Map)
          .cast<String, Object?>();
      final events = (run.remove('events') as List)
          .cast<Map>()
          .map((e) => e.cast<String, Object?>())
          .toList();
      expect(run['external_host'], isTrue);
      expect(events, isNotEmpty);
      expect(events.any((e) => e['event'] == 'suite_fixed'), isTrue);
      tester.view.physicalSize = const Size(1600, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final replay = Platform.environment['RSI_DESKTOP_REPLAY'] == '1';
      final matrixCamera =
          Platform.environment['RSI_DESKTOP_MATRIX_CAMERA'] == '1';
      const stages = {
        'suite_fixed',
        'target_call_started',
        'target_call_completed',
        'case_completed',
        'evaluation_completed',
        'candidate_created',
        'semantic_review_completed',
        'round_completed',
        'optimization_stopped',
        'result_completed',
      };
      final cuts = replay
          ? [
              for (var i = 0; i < events.length; i++)
                if (stages.contains(events[i]['event']) ||
                    i == events.length - 1)
                  i + 1,
            ]
          : [events.length];
      final frameIndex = <Map<String, Object?>>[];
      for (final (frame, cut) in cuts.indexed) {
        final visibleEvents = events.take(cut).toList();
        final viewRun = Map<String, Object?>.of(run);
        if (replay && cut < events.length) {
          for (final field in [
            'result',
            'iterations',
            'test_observations',
            'termination',
            'goal_verified',
            'finished_at',
          ]) {
            viewRun.remove(field);
          }
          viewRun['status'] = 'running';
          viewRun['iteration'] = visibleEvents.fold<int>(0, (latest, e) {
            final data = (e['data'] as Map?) ?? {};
            final record = (data['record'] as Map?) ?? {};
            final round =
                ((data['round'] ?? record['round']) as num?)?.toInt() ?? 0;
            return round > latest ? round : latest;
          });
        }
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(
              brightness: brightness,
              fontFamily: output != null ? 'SageScreenshot' : null,
            ),
            home: Scaffold(
              body: RepaintBoundary(
                key: const ValueKey('external-capture'),
                child: ColoredBox(
                  color: brightness == Brightness.dark
                      ? const Color(0xFF101820)
                      : const Color(0xFFF0F4F8),
                  child: SingleChildScrollView(
                    child: Padding(
                      padding: const EdgeInsets.all(28),
                      child: RsiObservatory(
                        run: viewRun,
                        events: visibleEvents,
                        chinese: true,
                        settings: LiquidGlassSettings(
                          blur: 0,
                          glassColor: brightness == Brightness.dark
                              ? const Color(0xFF172329)
                              : Colors.white,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 600));
        expect(find.byType(RsiObservatory), findsOneWidget);
        expect(tester.takeException(), isNull);
        final matrixView =
            replay &&
            matrixCamera &&
            const {
              'target_call_started',
              'target_call_completed',
              'case_completed',
            }.contains(visibleEvents.last['event']);
        if (matrixCamera) {
          if (matrixView) {
            await Scrollable.ensureVisible(
              tester.element(find.text('对话矩阵')),
              alignment: .02,
            );
          } else {
            Scrollable.of(
              tester.element(find.byType(RsiObservatory)),
            ).position.jumpTo(0);
          }
          await tester.pump(const Duration(milliseconds: 250));
          for (var settling = 0; settling < 8; settling++) {
            await tester.pump(const Duration(milliseconds: 16));
          }
        }
        if (output != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('external-capture')),
          );
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            final file = replay
                ? File(
                    '$output/${brightness.name}/frame-${frame.toString().padLeft(5, '0')}.png',
                  )
                : File('$output/desktop-live-${brightness.name}.png');
            file.parent.createSync(recursive: true);
            file.writeAsBytesSync(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        frameIndex.add({
          'frame': frame,
          'event_count': cut,
          'event': visibleEvents.last['event'],
          'source_time': visibleEvents.last['time'],
          'source_sequence': visibleEvents.last['sequence'],
          'viewport': matrixView ? 'conversation-matrix' : 'overview',
        });
      }
      if (replay && output != null) {
        File('$output/${brightness.name}/frame-index.json').writeAsStringSync(
          jsonEncode({
            'source': source,
            'kind': 'actual-event-replay',
            'idle_waits_compressed': true,
            'scores_unmodified': true,
            'frames': frameIndex,
          }),
        );
      }
      await tester.pumpWidget(const SizedBox());
    }, skip: source == null);
  }
}
