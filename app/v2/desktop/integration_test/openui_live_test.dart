// Opt-in native macOS E2E: real HTTP sidecar and configured model providers.
// Only the OS save picker is substituted; export HTTP and file writes are real.
import 'dart:convert';
import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:file_selector_platform_interface/file_selector_platform_interface.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sage_desktop_v2/main.dart' as entry;
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/openui_message_visibility.dart';
import 'package:sage_desktop_v2/src/ui/openui_pill.dart';
import 'package:sage_desktop_v2/src/ui/openui_charts.dart';
import 'package:sage_desktop_v2/src/ui/workspace_screen.dart';

const enabled = bool.fromEnvironment('OPENUI_LIVE');
const outputPath = String.fromEnvironment('OPENUI_LIVE_OUTPUT');
const recordVideo = bool.fromEnvironment('OPENUI_LIVE_RECORD');
const modelFilter = String.fromEnvironment('OPENUI_LIVE_MODEL');
const caseFilter = String.fromEnvironment('OPENUI_LIVE_CASE');

const cases = {
  'coffee-ppt':
      '帮我做一份 4 页的咖啡店创业路演演示文稿：封面、市场机会、经营测算、开店计划。风格有设计感，使用深蓝和暖色点缀，每页文字简洁，经营测算页包含图表。',
  'calculator':
      '做一个咖啡店经营测算交互界面：每天销量100杯，每杯售价25元，单杯成本8元，每月固定成本20000元，按30天。以上参数可调整，月收入、成本、利润和利润率立即联动，不需要提交。',
  'tracker':
      '做一个4周任务打卡界面。每周都是任务A、任务B、任务C，共12项。按周切换，每周的清单可展开收起，可以勾选和取消；即时显示总完成次数、完成率和进度条。',
  'comparison':
      '帮我比较三个会员方案：基础版每月免费，支持1人；专业版每月99元，支持5人；团队版每月299元，支持20人。用交互式表格和柱状图比较月费与月均每人成本，可以切换查看。数据都已给出，无须查资料。',
};

class SaveFiles extends FileSelectorPlatform {
  SaveFiles(this.out);
  final Directory out;
  String name = 'deck';
  @override
  Future<FileSaveLocation?> getSaveLocation({
    List<XTypeGroup>? acceptedTypeGroups,
    SaveDialogOptions options = const SaveDialogOptions(),
    String? initialDirectory,
    String? suggestedName,
    String? confirmButtonText,
  }) async => FileSaveLocation('${out.path}/$name.pptx');
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'real models native OpenUI closed loop',
    (tester) async {
      // Occluded macOS windows can withhold vsync. These recordings verify
      // functional behavior, not raster timing or FPS performance.
      final frameWatchdog = Timer.periodic(const Duration(seconds: 1), (_) {
        if (binding.schedulerPhase == SchedulerPhase.idle) {
          binding.scheduleWarmUpFrame();
        }
      });
      addTearDown(frameWatchdog.cancel);
      final conn =
          jsonDecode(
                File(
                  '/private/tmp/sage-openui-live-connection.json',
                ).readAsStringSync(),
              )
              as Map;
      final out = Directory(outputPath)..createSync(recursive: true);
      final api = V2ApiClient(
        baseUri: Uri.parse('http://127.0.0.1:${conn['port']}'),
        authToken: conn['auth_token'],
      );
      final controller = WorkspaceController(api: api);
      SharedPreferences.setMockInitialValues({});
      final selector = SaveFiles(out);
      final previousSelector = FileSelectorPlatform.instance;
      FileSelectorPlatform.instance = selector;
      await LiquidGlassWidgets.initialize();
      final reports = <Map<String, Object?>>[];
      final recordingClock = Stopwatch()..start();
      final frames = <Map<String, Object?>>[];
      var recordingCase = 'initialize';
      var lastFrameMs = -1000;
      final framesDir = Directory('${out.path}/frames');
      if (recordVideo) framesDir.createSync(recursive: true);
      Future<void> recordFrame({bool force = false}) async {
        if (!recordVideo) return;
        final elapsed = recordingClock.elapsedMilliseconds;
        if (!force && elapsed - lastFrameMs < 1000) return;
        final finder = find.byKey(const ValueKey('live-capture'));
        if (finder.evaluate().isEmpty) return;
        final boundary = tester.renderObject<RenderRepaintBoundary>(finder);
        if (boundary.debugNeedsPaint) return;
        final image = await boundary
            .toImage(pixelRatio: 1)
            .timeout(const Duration(seconds: 10));
        try {
          final bytes = await image
              .toByteData(format: ui.ImageByteFormat.png)
              .timeout(const Duration(seconds: 10));
          final filename = '${frames.length.toString().padLeft(6, '0')}.png';
          await File(
            '${framesDir.path}/$filename',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          frames.add({
            'file': filename,
            'elapsed_ms': elapsed,
            'case': recordingCase,
          });
          lastFrameMs = elapsed;
          File('${out.path}/frames.json').writeAsStringSync(
            jsonEncode({
              'sampling_interval_ms': 1000,
              'description':
                  'Native Flutter screenshots, sampled during test pumps and after actions. Not a raster performance recording.',
              'frames': frames,
            }),
          );
        } finally {
          image.dispose();
        }
      }

      Future<void> until(
        bool Function() condition,
        String label, {
        int seconds = 90,
      }) async {
        final deadline = DateTime.now().add(Duration(seconds: seconds));
        while (!condition()) {
          if (DateTime.now().isAfter(deadline)) {
            throw StateError('Timeout: $label');
          }
          await tester.pump(const Duration(milliseconds: 200));
          await recordFrame();
          final error = tester.takeException();
          if (error != null) throw StateError('Flutter: $error');
        }
        await tester.pump(const Duration(milliseconds: 200));
      }

      Future<void> tap(Finder f) async {
        // The transcript is a lazy ListView; old process rows may be unbuilt.
        for (var attempt = 0; f.evaluate().isEmpty && attempt < 16; attempt++) {
          final transcript = find.byKey(const ValueKey('thread-message-list'));
          if (transcript.evaluate().isEmpty) break;
          await tester.drag(transcript, const Offset(0, 500));
          await tester.pump(const Duration(milliseconds: 200));
        }
        expect(f, findsWidgets, reason: 'Requested control must exist');
        for (var attempt = 0; attempt < 5; attempt++) {
          await Scrollable.ensureVisible(
            tester.element(f.first),
            alignment: .4,
          );
          await tester.pump();
          if (f.first.hitTestable().evaluate().isNotEmpty) break;
          await tester.pump(const Duration(milliseconds: 200));
        }
        expect(
          f.first.hitTestable(),
          findsOneWidget,
          reason: 'Control must be on screen before tapping',
        );
        await tester.tap(f.first);
        await tester.pump(const Duration(milliseconds: 300));
        await recordFrame(force: true);
      }

      Future<void> capture(String name) async {
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('live-capture')),
        );
        final image = await boundary.toImage(pixelRatio: 1);
        final bytes = await image
            .toByteData(format: ui.ImageByteFormat.png)
            .timeout(const Duration(seconds: 10));
        await File(
          '${out.path}/$name.png',
        ).writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
        await recordFrame(force: true);
      }

      await tester.pumpWidget(
        entry.sageGlassRoot(
          RepaintBoundary(
            key: const ValueKey('live-capture'),
            child: SageDesktopV2App(controller: controller),
          ),
        ),
      );
      await until(
        () =>
            controller.agents.isNotEmpty &&
            controller.selectedConversation != null,
        'initialize',
      );
      for (final agent in conn['agents'] as List) {
        if (modelFilter.isNotEmpty && agent['model'] != modelFilter) continue;
        for (final c in cases.entries) {
          if (caseFilter.isNotEmpty && c.key != caseFilter) continue;
          final name = '${agent['model']}-${c.key}';
          recordingCase = name;
          final report = <String, Object?>{
            'model': agent['model'],
            'case': c.key,
          };
          reports.add(report);
          debugPrint('OPENUI_LIVE_START $name');
          final started = DateTime.now();
          try {
            await controller.createAgentWorkspaceConversation();
            await controller.selectAgent(agent['id']);
            controller.setPreferInteractiveUi(true);
            await tester.pump(const Duration(milliseconds: 300));
            await tester.enterText(
              find.byKey(const ValueKey('agent-composer')),
              c.value,
            );
            await tester.sendKeyEvent(LogicalKeyboardKey.enter);
            await until(
              () => controller.selectedConversation!.runId.isNotEmpty,
              'run start',
            );
            final conversation = controller.selectedConversation!;
            await until(
              () =>
                  [
                    RunStatus.completed,
                    RunStatus.failed,
                    RunStatus.suspended,
                    RunStatus.cancelled,
                  ].contains(conversation.status) ||
                  conversation.pendingInteraction != null,
              'generation',
              seconds: 420,
            );
            report['status'] = conversation.status.name;
            report['pending_interaction'] = conversation.pendingInteraction
                ?.toJson();
            report['session'] = conversation.sessionId;
            report['seconds'] = DateTime.now().difference(started).inSeconds;
            final uiMessages = conversation.messages
                .where((m) => m.openUiSurfaces.isNotEmpty)
                .toList();
            report['ui_messages'] = uiMessages.length;
            report['repair_decisions'] = conversation.runtimeEvents
                .where((e) => e['type'] == 'continuation.decided')
                .map((e) => e['data'])
                .toList();
            File('${out.path}/$name-messages.json').writeAsStringSync(
              jsonEncode(uiMessages.map((m) => m.toJson()).toList()),
            );
            if (uiMessages.isEmpty) {
              throw StateError(
                'No UI output; status ${conversation.status.name}',
              );
            }
            final latest = uiMessages.last;
            final surface = latest.openUiSurfaces.last;
            report['validation_error'] = surface['error'];
            if (surface['complete'] != true ||
                surface['surface_id'] == null ||
                surface['error'] != null) {
              throw StateError('Invalid UI: ${surface['error']}');
            }
            if (conversation.status != RunStatus.completed) {
              throw StateError('Run not completed');
            }
            final superseded = supersededOpenUiMessages(conversation.messages);
            report['superseded'] = superseded.length;
            for (final id in superseded) {
              expect(find.byKey(ValueKey(id)), findsNothing);
            }
            if (superseded.isNotEmpty) {
              final toggles = find.byKey(
                const ValueKey('process-panel-toggle'),
              );
              await tap(toggles.last);
              final old = uiMessages.firstWhere(
                (m) => superseded.contains(m.id),
              );
              final row = find.byKey(
                ValueKey(
                  'process-openui:${old.id}:${old.openUiSurfaces.first['block_index']}',
                ),
              );
              await tap(row);
              expect(
                controller.expandedOpenUiKey,
                '${old.id}:${old.openUiSurfaces.first['block_index']}',
              );
              report['process_sidebar'] = true;
              await capture('$name-process');
            }
            // Screenshots and local operations use the actual generated native widgets.
            await tap(
              find.byKey(const ValueKey('openui-open-in-sidebar')).last,
            );
            await until(
              () => find
                  .byKey(const ValueKey('openui-panel-background'))
                  .evaluate()
                  .isNotEmpty,
              'sidebar',
            );
            report['sidebar'] = true;
            if (c.key == 'coffee-ppt') {
              final workspace = find.byKey(
                const ValueKey('openui-deck-workspace'),
              );
              expect(workspace, findsOneWidget);
              final pages =
                  ((surface['tree'] as Map)['props'] as Map)['children']
                      as List;
              expect(pages.length, 4);
              for (var i = 0; i < 4; i++) {
                await tap(find.byKey(ValueKey('openui-slide-thumbnail:$i')));
                await capture('$name-page-${i + 1}');
              }
              selector.name = name;
              final export = find.descendant(
                of: workspace,
                matching: find.textContaining('PPTX'),
              );
              await tap(export);
              await until(
                () => File('${out.path}/$name.pptx').existsSync(),
                'PPTX export',
              );
              report['export_bytes'] = File(
                '${out.path}/$name.pptx',
              ).lengthSync();
            } else if (c.key == 'calculator') {
              final panel = find.byKey(
                const ValueKey('openui-panel-background'),
              );
              final fields = find.descendant(
                of: panel,
                matching: find.byType(EditableText),
              );
              final count = fields.evaluate().length;
              expect(count, greaterThanOrEqualTo(4));
              final beforeRun = conversation.runId;
              // Locate the known initial daily volume, not a model-chosen field name.
              final volume = fields.evaluate().firstWhere(
                (e) =>
                    (e.widget as EditableText).controller.text == '100' ||
                    (e.widget as EditableText).controller.text == '100.0',
              );
              await Scrollable.ensureVisible(volume, alignment: .4);
              await tester.enterText(find.byWidget(volume.widget), '200');
              await tester.pump(const Duration(milliseconds: 500));
              expect(conversation.runId, beforeRun);
              final texts = find
                  .descendant(of: panel, matching: find.byType(Text))
                  .evaluate()
                  .map((e) => (e.widget as Text).data ?? '')
                  .join(' ')
                  .replaceAll(',', '');
              expect(texts, contains('82000'));
              report['local_calculation'] = true;
            } else if (c.key == 'tracker') {
              final panel = find.byKey(
                const ValueKey('openui-panel-background'),
              );
              var options = find.descendant(
                of: panel,
                matching: find.byType(OpenUiPill),
              );
              if (!options.evaluate().any(
                (e) =>
                    (e.widget.key?.toString() ?? '').contains('openui-option:'),
              )) {
                final sections = find.descendant(
                  of: panel,
                  matching: find.byType(ExpansionTile),
                );
                if (sections.evaluate().isNotEmpty) await tap(sections.first);
              }
              options = find.descendant(
                of: panel,
                matching: find.byType(OpenUiPill),
              );
              final option = options
                  .evaluate()
                  .where(
                    (e) => (e.widget.key?.toString() ?? '').contains(
                      'openui-option:',
                    ),
                  )
                  .first;
              final pill = option.widget as OpenUiPill;
              final beforeRun = conversation.runId;
              await tap(
                find.descendant(of: panel, matching: find.byKey(pill.key!)),
              );
              expect(
                tester.widget<OpenUiPill>(find.byKey(pill.key!).last).selected,
                !pill.selected,
              );
              expect(conversation.runId, beforeRun);
              report['local_check'] = true;
            } else if (c.key == 'comparison') {
              final panel = find.byKey(
                const ValueKey('openui-panel-background'),
              );
              final charts = find.descendant(
                of: panel,
                matching: find.byType(OpenUiChart),
              );
              if (charts.evaluate().isEmpty) {
                final tabs = find.descendant(
                  of: panel,
                  matching: find.byType(OpenUiPill),
                );
                for (final key
                    in tabs
                        .evaluate()
                        .map((e) => e.widget.key)
                        .whereType<ValueKey>()
                        .where(
                          (k) => k.value.toString().startsWith('openui-tab:'),
                        )
                        .toList()) {
                  await tap(
                    find.descendant(of: panel, matching: find.byKey(key)),
                  );
                  if (charts.evaluate().isNotEmpty) break;
                }
              }
              expect(charts, findsWidgets);
              final chart = tester.widget<OpenUiChart>(charts.first);
              expect(chart.props['type'], 'bar');
              final plot = find.descendant(
                of: charts.first,
                matching: find.byKey(const ValueKey('openui-chart-plot')),
              );
              await Scrollable.ensureVisible(
                tester.element(plot),
                alignment: .4,
              );
              await tester.pump(const Duration(milliseconds: 300));
              final labels = chart.props['labels'] as List;
              final geometry = OpenUiChartGeometry(
                tester.getSize(plot),
                labels.length,
                'bar',
              );
              final origin = tester.getTopLeft(plot);
              final mouse = await tester.createGesture(
                kind: ui.PointerDeviceKind.mouse,
              );
              await mouse.addPointer(location: Offset.zero);
              for (var i = 0; i < labels.length; i++) {
                await mouse.moveTo(origin + Offset(geometry.categoryX(i), 100));
                await tester.pump(const Duration(milliseconds: 200));
                expect(
                  find.descendant(
                    of: charts.first,
                    matching: find.textContaining('${labels[i]} ·'),
                  ),
                  findsOneWidget,
                );
                await capture('$name-hover-$i');
              }
              await mouse.removePointer();
              report['chart_hover'] = true;
            }
            tester
                .widget<WorkspaceScreen>(find.byType(WorkspaceScreen))
                .onThemeModeChanged(ThemeMode.dark);
            await until(
              () =>
                  Theme.of(
                    tester.element(
                      find.byKey(const ValueKey('openui-panel-background')),
                    ),
                  ).brightness ==
                  Brightness.dark,
              'dark theme',
            );
            expect(
              Theme.of(
                tester.element(
                  find.byKey(const ValueKey('openui-panel-background')),
                ),
              ).brightness,
              Brightness.dark,
            );
            await capture('$name-dark');
            tester
                .widget<WorkspaceScreen>(find.byType(WorkspaceScreen))
                .onThemeModeChanged(ThemeMode.light);
            await until(
              () =>
                  Theme.of(
                    tester.element(
                      find.byKey(const ValueKey('openui-panel-background')),
                    ),
                  ).brightness ==
                  Brightness.light,
              'light theme',
            );
            expect(
              Theme.of(
                tester.element(
                  find.byKey(const ValueKey('openui-panel-background')),
                ),
              ).brightness,
              Brightness.light,
            );
            await capture('$name-light');
            tester
                .widget<WorkspaceScreen>(find.byType(WorkspaceScreen))
                .onThemeModeChanged(ThemeMode.dark);
            report['passed'] = true;
          } catch (e, stack) {
            report['stack'] = stack.toString();
            report['passed'] = false;
            report['error'] = e.toString();
            await capture('$name-failure');
            final conversation = controller.selectedConversation;
            if (conversation != null &&
                [
                  RunStatus.running,
                  RunStatus.starting,
                ].contains(conversation.status)) {
              await controller.cancel();
            }
          }
          File('${out.path}/report.json').writeAsStringSync(
            const JsonEncoder.withIndent('  ').convert(reports),
          );
          debugPrint('OPENUI_LIVE_RESULT ${jsonEncode(report)}');
        }
      }
      FileSelectorPlatform.instance = previousSelector;
      controller.dispose();
      expect(reports.where((r) => r['passed'] != true), isEmpty);
    },
    skip: !enabled,
    timeout: const Timeout(Duration(minutes: 60)),
  );
}
