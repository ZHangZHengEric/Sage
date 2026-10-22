// Opt-in native Desktop E2E. Uses real sidecar/model calls; never run in CI by default.
// Only the OS file dialog is replaced: it returns the real synthetic suite file.
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:file_selector_platform_interface/file_selector_platform_interface.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/api/runtime_host.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

const enabled = bool.fromEnvironment('RSI_LIVE_MODEL');
const outputPath = String.fromEnvironment('RSI_LIVE_ARTIFACT_DIR');
const resumeRun = String.fromEnvironment('RSI_RESUME_RUN');

class SuiteFiles extends FileSelectorPlatform {
  SuiteFiles(this.output);
  final Directory output;
  @override
  Future<XFile?> openFile({
    List<XTypeGroup>? acceptedTypeGroups,
    String? initialDirectory,
    String? confirmButtonText,
  }) async => XFile('${output.path}/suite.json');
  @override
  Future<FileSaveLocation?> getSaveLocation({
    List<XTypeGroup>? acceptedTypeGroups,
    SaveDialogOptions options = const SaveDialogOptions(),
    String? initialDirectory,
    String? suggestedName,
    String? confirmButtonText,
  }) async {
    final root = Directory('${output.path}/exports')
      ..createSync(recursive: true);
    return FileSaveLocation(
      '${root.path}/${options.suggestedName ?? suggestedName}',
    );
  }
}

class AuditApi extends V2ApiClient {
  AuditApi(this.audit);
  final Map<String, Object?> audit;
  String? runId;
  Map<String, Object?>? latestRun;
  int applyRequests = 0, applyCompleted = 0;
  Map<String, Object?>? lastDetach;
  @override
  Future<Map<String, Object?>> startRsi(
    String agentId,
    Map<String, Object?> body,
  ) async {
    final value = await super.startRsi(agentId, body);
    runId = value['id'].toString();
    audit['start_options'] = body;
    audit['run_id'] = runId;
    return value;
  }

  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String id, {
    int afterSequence = 0,
  }) async {
    final value = await super.rsiRun(agentId, id, afterSequence: afterSequence);
    latestRun = value;
    final samples = audit['progress'] as List<Map<String, Object?>>;
    final sample = <String, Object?>{
      'time': DateTime.now().toIso8601String(),
      'status': value['status'],
      'iteration': value['iteration'],
      'stage': value['stage'],
      'role': value['role'],
      'sequence': value['sequence'],
      'after_sequence': afterSequence,
    };
    if (samples.isEmpty ||
        samples.last['sequence'] != sample['sequence'] ||
        samples.last['status'] != sample['status']) {
      samples.add(sample);
      // No credentials, prompts or model outputs in the terminal progress stream.
      debugPrint('RSI_PROGRESS ${jsonEncode(sample)}');
    }
    return value;
  }

  @override
  Future<void> applyRsiVersion(
    String agentId,
    String versionId,
    String fingerprint,
  ) async {
    applyRequests++;
    await super.applyRsiVersion(agentId, versionId, fingerprint);
    applyCompleted++;
  }

  @override
  Future<Map<String, Object?>> detachRuntimeClient(String clientId) async {
    final value = await super.detachRuntimeClient(clientId);
    lastDetach = value;
    return value;
  }
}

Object? canonical(Object? value) {
  if (value is Map) {
    final keys = value.keys.map((k) => k.toString()).toList()..sort();
    return {for (final key in keys) key: canonical(value[key])};
  }
  if (value is List) return value.map(canonical).toList();
  return value;
}

Map<String, dynamic> catalogAgent(String id) {
  final home = Platform.environment['HOME']!;
  final catalog =
      jsonDecode(
            File('$home/sage/runtime/desktop-catalog.json').readAsStringSync(),
          )
          as Map;
  return (catalog['agents'] as List).cast<Map<String, dynamic>>().firstWhere(
    (a) => a['agent_id'] == id,
  );
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Native Desktop: configured model 3 rounds, durable history and read-only version previews',
    (tester) async {
      final out = Directory(outputPath);
      final setup =
          jsonDecode(File('${out.path}/setup.json').readAsStringSync()) as Map;
      final agentId = setup['agent_id'] as String;
      var baseline = jsonEncode(canonical(catalogAgent(agentId)['config']));
      final originalSage = jsonEncode(
        canonical(catalogAgent('sage')['config']),
      );
      final audit = <String, Object?>{
        'model': 'gpt-6.1-sol',
        'agent_id': agentId,
        'progress': <Map<String, Object?>>[],
        'configuration_checks': <Map<String, Object?>>[],
        'file_dialog':
            'deterministic real suite file; native OS picker not tested',
      };
      if (resumeRun.isNotEmpty) {
        final previous =
            jsonDecode(
                  File('${out.path}/live-validation.json').readAsStringSync(),
                )
                as Map;
        audit['start_options'] = previous['start_options'];
        audit['manual_save_from_frontend'] =
            previous['manual_save_from_frontend'];
        audit['last_window_close_kept_background_run'] =
            previous['last_window_close_kept_background_run'];
        audit['run_id'] = resumeRun;
        for (final key in ['progress', 'configuration_checks']) {
          audit[key] = (previous[key] as List)
              .map((v) => (v as Map).cast<String, Object?>())
              .toList();
        }
        audit['resumed_existing_run'] = true;
      }
      var api = AuditApi(audit);
      var host = RuntimeHost(api: api);
      var controller = WorkspaceController(api: api);
      SharedPreferences.setMockInitialValues({});
      final selector = FileSelectorPlatform.instance;
      FileSelectorPlatform.instance = SuiteFiles(out);
      await LiquidGlassWidgets.initialize();
      final semantics = tester.ensureSemantics();
      Map<String, Object?>? selectedVersion;
      void check(String phase, {bool unchanged = true}) {
        final same =
            jsonEncode(canonical(catalogAgent(agentId)['config'])) == baseline;
        final sageSame =
            jsonEncode(canonical(catalogAgent('sage')['config'])) ==
            originalSage;
        (audit['configuration_checks'] as List<Map<String, Object?>>).add({
          'phase': phase,
          'time': DateTime.now().toIso8601String(),
          'baseline_unchanged': same,
          'original_sage_unchanged': sageSame,
          'apply_requests': api.applyRequests,
        });
        expect(sageSame, isTrue, reason: phase);
        if (unchanged) expect(same, isTrue, reason: phase);
        File(
          '${out.path}/live-validation.json',
        ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(audit));
      }

      Future<void> until(
        bool Function() ready,
        String label, {
        Duration timeout = const Duration(seconds: 60),
      }) async {
        final deadline = DateTime.now().add(timeout);
        while (!ready()) {
          if (DateTime.now().isAfter(deadline)) {
            throw StateError('Timeout: $label');
          }
          await tester.pump(const Duration(milliseconds: 200));
        }
        await tester.pump(const Duration(milliseconds: 200));
        expect(tester.takeException(), isNull, reason: label);
      }

      Future<void> tap(Finder finder) async {
        await tester.ensureVisible(finder.first);
        await tester.pump(const Duration(milliseconds: 300));
        await tester.tap(finder.first);
        await tester.pump(const Duration(milliseconds: 300));
      }

      Future<void> capture(String name) async {
        await tester.pump(const Duration(milliseconds: 300));
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('live-capture')),
        );
        final image = await boundary.toImage(pixelRatio: 1);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        await File(
          '${out.path}/$name.png',
        ).writeAsBytes(data!.buffer.asUint8List());
        image.dispose();
      }

      Future<void> mount() async {
        debugPrint("RSI_STEP host_start");
        await host.ensureReady().timeout(const Duration(seconds: 45));
        debugPrint("RSI_STEP host_ready");
        await tester.pumpWidget(
          LiquidGlassWidgets.wrap(
            adaptiveQuality: false,
            child: RepaintBoundary(
              key: const ValueKey('live-capture'),
              child: SageDesktopV2App(controller: controller),
            ),
          ),
        );
        await until(
          () => !controller.loading && controller.agents.isNotEmpty,
          'Desktop ready',
        );
        expect(controller.error, isNull);
        debugPrint('RSI_STEP desktop_ready');
      }

      Future<void> openRsi() async {
        debugPrint('RSI_STEP open_settings');
        await tap(find.byKey(const ValueKey('settings-button')));
        await until(
          () => find.text('智能体').evaluate().isNotEmpty,
          'settings rail',
        );
        debugPrint('RSI_STEP settings_ready');
        await tap(find.text('智能体'));
        await until(
          () => find
              .textContaining('RSI Desktop 验证 GPT-6.1 Sol')
              .evaluate()
              .isNotEmpty,
          'Agent catalog',
        );
        await tap(find.textContaining('RSI Desktop 验证 GPT-6.1 Sol'));
        await until(
          () =>
              controller.agentConfiguration?.id == agentId &&
              !controller.settingsCatalogLoading &&
              controller.settingsAgentLoadingId.isEmpty,
          'RSI target selected',
        );
        expect(
          controller.agentConfiguration!.llmProviderId,
          setup['provider_id'],
        );
        debugPrint('RSI_STEP open_rsi');
        await tap(find.byKey(const ValueKey('settings-agent-rsi')));
        await tap(find.byKey(const ValueKey('rsi-toggle-setup')));
        await until(
          () => find.byKey(const ValueKey('rsi-goal')).evaluate().isNotEmpty,
          'embedded RSI page',
        );
        expect(find.byKey(const ValueKey('settings-rail')), findsOneWidget);
      }

      try {
        await mount();
        await openRsi();
        if (resumeRun.isEmpty) {
          await tap(find.byKey(const ValueKey('rsi-back-agent')));
          await tap(find.byKey(const ValueKey('settings-agent-edit')));
          await until(
            () => find
                .byKey(const ValueKey('agent-description-field'))
                .evaluate()
                .isNotEmpty,
            'manual configuration editor',
          );
          await tester.enterText(
            find.byKey(const ValueKey('agent-description-field')),
            'Desktop RSI 人工保存验证',
          );
          await tap(find.byKey(const ValueKey('settings-agent-edit')));
          await until(
            () =>
                controller.agentConfiguration?.description ==
                    'Desktop RSI 人工保存验证' &&
                find
                    .byKey(const ValueKey('agent-description-field'))
                    .evaluate()
                    .isEmpty,
            'manual save completed',
          );
          baseline = jsonEncode(canonical(catalogAgent(agentId)['config']));
          File('${out.path}/manual-saved-input.json').writeAsStringSync(
            const JsonEncoder.withIndent('  ').convert(catalogAgent(agentId)),
          );
          audit['manual_save_from_frontend'] = true;
          await tap(find.byKey(const ValueKey('settings-agent-rsi')));
          await tap(find.byKey(const ValueKey('rsi-toggle-setup')));
          await until(
            () => find.byKey(const ValueKey('rsi-goal')).evaluate().isNotEmpty,
            'RSI from manually saved version',
          );
        }
        late final String runId;
        if (resumeRun.isEmpty) {
          await tester.enterText(
            find.byKey(const ValueKey('rsi-goal')),
            '提升结构化输出、精确计算、不可信输入处理和多轮约束保持的可靠性；只采用通用方法，不背测试答案，不改变原始目标。测试仅使用合成文本及隔离临时工作区。',
          );
          await tester.enterText(find.byKey(const ValueKey('rsi-rounds')), '3');
          await tap(find.byKey(const ValueKey('rsi-import-suite')));
          await until(
            () => find.text('suite.json').evaluate().isNotEmpty,
            'real suite imported',
          );
          check('before_start');
          await capture('01-before-start');
          await tap(find.byKey(const ValueKey('rsi-start')));
          await until(() => api.runId != null, 'start accepted');

          expect((audit['start_options'] as Map)['rounds'], 3);
          expect(
            ((audit['start_options'] as Map)['suite'] as Map)['cases'],
            hasLength(4),
          );
          await until(
            () => api.latestRun?['status'] == 'running',
            'visible live progress',
            timeout: const Duration(minutes: 2),
          );
          runId = api.runId!;
        } else {
          runId = resumeRun;
          api.runId = runId;
          await until(
            () => api.latestRun?['id'] == runId,
            'existing real run reconnected',
          );
          expect(api.latestRun?['status'], anyOf('running', 'completed'));
        }
        if (api.latestRun?['status'] == 'running') {
          check('running_before_confirmation');
          await capture('02-running');
          await tap(find.byKey(const ValueKey('rsi-back-agent')));
          await until(
            () => find.textContaining(' · RSI').evaluate().isNotEmpty,
            'Agent list RSI badge',
          );
          await capture('03-agent-list-background');
          // Drop the last real UI lease while the run is active, then reconnect.
          await tester.pumpWidget(const SizedBox.shrink());
          controller.dispose();
          await host.stopOwnedSidecar();
          expect(api.lastDetach?['shutdown_requested'], isFalse);
          audit['last_window_close_kept_background_run'] = true;
          await Future<void>.delayed(const Duration(seconds: 3));
          api = AuditApi(audit)..runId = runId;
          host = RuntimeHost(api: api);
          controller = WorkspaceController(api: api);
          await mount();
          await openRsi();
          await until(
            () => api.latestRun?['id'] == runId,
            'same run recovered after UI close',
          );
          check('reopened_during_run');
        }
        final deadline = DateTime.now().add(const Duration(minutes: 20));
        while (!{
          'completed',
          'failed',
          'cancelled',
          'interrupted',
        }.contains(api.latestRun?['status'])) {
          if (DateTime.now().isAfter(deadline)) {
            throw StateError('RSI exceeded live test deadline');
          }
          check('progress_${api.latestRun?['sequence']}');
          await tester.pump(const Duration(seconds: 1));
        }
        expect(
          api.latestRun?['status'],
          'completed',
          reason: api.latestRun?['error_type']?.toString(),
        );
        expect(api.latestRun?['iteration'], 3);
        final complete = await api.rsiRun(agentId, runId);
        final result = complete['result'] as Map;
        expect(result['iterations'], hasLength(4));
        expect(complete['iterations'], hasLength(4));
        File(
          '${out.path}/result.json',
        ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(result));
        check('completed_before_confirmation');
        expect(api.applyRequests, 0);
        await capture('04-completed');
        final history = await api.rsiHistory(agentId);
        final versions = (history['versions'] as List).cast<Map>();
        final original = versions.firstWhere(
          (v) =>
              v['source'] == 'rsi' &&
              v['run_id'] == runId &&
              v['iteration'] == 0,
        );
        final accepted = versions
            .where(
              (v) =>
                  v['source'] == 'rsi' &&
                  v['run_id'] == runId &&
                  (v['iteration'] as int) > 0 &&
                  v['ready'] != false &&
                  (v['review'] == null ||
                      (v['review'] as Map)['approved'] == true),
            )
            .toList();
        expect(
          accepted,
          isNotEmpty,
          reason:
              'A completed, unrejected iteration must be selectable (including no-op)',
        );
        final chosen = accepted.first;
        selectedVersion = await api.rsiVersion(
          agentId,
          chosen['id'].toString(),
        );
        audit['selected_iteration'] = chosen['iteration'];
        audit['selected_package_differs_from_baseline'] =
            chosen['package_hash'] != original['package_hash'];
        await tap(find.textContaining('迭代 ${chosen['iteration']}').first);
        await tap(
          find.byKey(ValueKey('rsi-open-iteration-${chosen['iteration']}')),
        );
        await until(
          () => find
              .byKey(const ValueKey('rsi-export-version'))
              .evaluate()
              .isNotEmpty,
          'full candidate preview',
        );
        await tap(find.byKey(const ValueKey('rsi-export-version')));
        await until(
          () => File(
            '${out.path}/exports/agent-${chosen['id']}.json',
          ).existsSync(),
          'candidate export saved',
        );
        expect(
          jsonDecode(
            File(
              '${out.path}/exports/agent-${chosen['id']}.json',
            ).readAsStringSync(),
          )['package'],
          selectedVersion['package'],
        );
        expect(find.byKey(const ValueKey('rsi-apply-version')), findsNothing);
        expect(find.byKey(const ValueKey('rsi-confirm-apply')), findsNothing);
        expect(api.applyRequests, 0);
        check('candidate_preview_is_read_only');
        await capture('05-read-only-version');
        await tap(find.byKey(ValueKey('rsi-version-${original['id']}')));
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('rsi-apply-version')), findsNothing);
        expect(api.applyRequests, 0);
        check('baseline_preview_is_read_only');
        audit['version_previews_leave_runtime_configuration_unchanged'] = true;
        await tap(find.byKey(const ValueKey('rsi-back-agent')));
        await until(
          () => find
              .byKey(const ValueKey('rsi-export-report'))
              .evaluate()
              .isNotEmpty,
          'report history restored',
        );
        await tap(find.byKey(const ValueKey('rsi-export-report')));
        await until(
          () => File('${out.path}/exports/rsi-$runId.json').existsSync(),
          'report export saved',
        );
        expect(
          jsonDecode(
            File('${out.path}/exports/rsi-$runId.json').readAsStringSync(),
          )['iterations'],
          hasLength(4),
        );
        audit['complete_version_and_report_exports_verified'] = true;
        final oldPid = jsonDecode(
          File(
            '${Platform.environment['HOME']}/sage/runtime/desktop-v2-sidecar.json',
          ).readAsStringSync(),
        )['pid'];
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        await host.stopOwnedSidecar();
        api = AuditApi(audit)..runId = runId;
        host = RuntimeHost(api: api);
        controller = WorkspaceController(api: api);
        await mount();
        await openRsi();
        await until(
          () => api.latestRun?['status'] == 'completed',
          'history after full backend restart',
        );
        final newPid = jsonDecode(
          File(
            '${Platform.environment['HOME']}/sage/runtime/desktop-v2-sidecar.json',
          ).readAsStringSync(),
        )['pid'];
        expect(newPid, isNot(oldPid));
        final reopened = await api.rsiHistory(agentId);
        expect(
          (reopened['versions'] as List).where(
            (v) => (v as Map)['run_id'] == runId,
          ),
          hasLength(4),
        );
        audit['history_survived_backend_restart'] = true;
        await capture('07-history-after-restart');
        await tap(find.byKey(const ValueKey('rsi-back-agent')));
        await tap(find.byKey(const ValueKey('settings-agent-history')));
        await until(
          () =>
              find.textContaining('版本历史 ·').evaluate().isNotEmpty &&
              find.textContaining('配置保存 ·').evaluate().isNotEmpty,
          'manual edit history entry',
        );
        expect(find.byKey(const ValueKey('rsi-start')), findsNothing);
        final manual = (reopened['versions'] as List).cast<Map>().firstWhere(
          (v) => v['source'] == 'settings',
        );
        await tap(find.byKey(ValueKey('rsi-version-${manual['id']}')));
        await until(
          () => find
              .byKey(const ValueKey('rsi-saved-configuration'))
              .evaluate()
              .isNotEmpty,
          'saved configuration preview',
        );
        await tap(find.text('保存的配置'));
        await until(
          () => find.text('Desktop RSI 人工保存验证').evaluate().isNotEmpty,
          'manual description retained',
        );
        audit['manual_history_complete_configuration_visible'] = true;
        await capture('08-manual-version-history');
        audit['passed'] = true;
        debugPrint('RSI_LIVE_E2E_PASSED');
      } finally {
        audit['finished_at'] = DateTime.now().toIso8601String();
        audit['original_sage_unchanged'] =
            jsonEncode(canonical(catalogAgent('sage')['config'])) ==
            originalSage;
        File(
          '${out.path}/live-validation.json',
        ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(audit));
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        await host.stopOwnedSidecar();
        FileSelectorPlatform.instance = selector;
        semantics.dispose();
      }
    },
    skip: !enabled || !Platform.isMacOS,
    timeout: const Timeout(Duration(minutes: 25)),
  );
}
