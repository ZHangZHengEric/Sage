// Opt-in native recording: real sidecar, real model, real RSI; no activation.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/main.dart' show sageGlassRoot;
import 'package:sage_desktop_v2/src/api/runtime_host.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart' show sageDesktopTheme;
import 'package:sage_desktop_v2/src/localization/app_localizations.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';

const enabled = bool.fromEnvironment('RSI_RECORD_LIVE');
const tour = bool.fromEnvironment('RSI_RECORD_TOUR');
const headless = bool.fromEnvironment('RSI_RECORD_HEADLESS');
const recordMinutes = int.fromEnvironment(
  'RSI_RECORD_MINUTES',
  defaultValue: 150,
);
const evolutionRounds = int.fromEnvironment(
  'RSI_RECORD_ROUNDS',
  defaultValue: 8,
);
const output = String.fromEnvironment('RSI_RECORD_DIR');
const provider = String.fromEnvironment('RSI_RECORD_PROVIDER');
const internalModelName = String.fromEnvironment(
  'RSI_RECORD_INTERNAL_MODEL_NAME',
);
const startHelper = String.fromEnvironment('RSI_RECORD_START_HELPER');
const resumeAgent = String.fromEnvironment('RSI_RECORD_AGENT');
const resumeRun = String.fromEnvironment('RSI_RECORD_RUN');
const questionCount = int.fromEnvironment(
  'RSI_RECORD_VALIDATION_COUNT',
  defaultValue: 24,
);
const concurrency = int.fromEnvironment(
  'RSI_RECORD_CONCURRENCY',
  defaultValue: 3,
);

class RecordingApi extends V2ApiClient {
  RecordingApi({super.httpClient});
  Map<String, Object?>? latest;
  String? runId;
  final events = <Map<String, Object?>>[];
  final recordedSequences = <int>{};
  String? recordedRunId;
  int? lastSequence;
  final activeCases = <String>{};
  String? activePass;
  @override
  Future<Map<String, Object?>> startRsi(
    String agentId,
    Map<String, Object?> body,
  ) async {
    final Map<String, Object?> value;
    if (startHelper.isNotEmpty) {
      final result = await Process.run(
        '/Users/zhangzheng/zavixai/Sage/.venv/bin/python',
        [startHelper, agentId, jsonEncode(body)],
        workingDirectory: '/Users/zhangzheng/zavixai/Sage',
      );
      if (result.exitCode != 0) {
        throw StateError('MCP start failed: ${result.stderr}');
      }
      value = (jsonDecode(result.stdout.toString()) as Map)
          .cast<String, Object?>();
    } else {
      value = await super.startRsi(agentId, body);
    }
    runId = value['id'].toString();
    File('$output/identity.json').writeAsStringSync(
      jsonEncode({
        'agent_id': agentId,
        'run_id': runId,
        'provider_id': provider,
        'request': body,
      }),
    );
    return value;
  }

  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String runId, {
    int afterSequence = 0,
  }) async {
    final value = await super.rsiRun(
      agentId,
      runId,
      afterSequence: afterSequence,
    );
    if (recordedRunId != value['id']) {
      recordedRunId = value['id']?.toString();
      recordedSequences.clear();
      events.clear();
      activeCases.clear();
      activePass = null;
    }
    latest = value;
    for (final event in value['events'] as List? ?? []) {
      final row = (event as Map).cast<String, Object?>();
      if (!recordedSequences.add((row['sequence'] as num).toInt())) continue;
      events.add(row);
      final data = (row['data'] as Map?) ?? {};
      if (row['event'] == 'target_call_started') {
        final pass = '${data['round']}:${data['phase']}';
        if (pass != activePass) {
          activeCases.clear();
          activePass = pass;
        }
        activeCases.add(data['case_id'].toString());
      } else if (row['event'] == 'case_completed') {
        activeCases.remove(((data['result'] as Map?)?['case'] as Map?)?['id']);
      }
    }
    if (lastSequence != value['sequence']) {
      lastSequence = (value['sequence'] as num?)?.toInt();
      debugPrint(
        'RSI_RECORD ${jsonEncode({'status': value['status'], 'round': value['iteration'], 'stage': value['stage'], 'sequence': value['sequence']})}',
      );
    }
    return value;
  }
}

void main() {
  // Construct the real transport before widget tests install their mock HTTP.
  final transport = headless
      ? (HttpClient()
          ..connectionTimeout = const Duration(seconds: 3)
          ..findProxy = ((_) => 'DIRECT'))
      : null;
  final binding = headless || !enabled
      ? TestWidgetsFlutterBinding.ensureInitialized()
      : IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  if (binding is LiveTestWidgetsFlutterBinding) {
    binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;
  }
  testWidgets(
    'Record real RSI evolution in Desktop',
    (tester) async {
      Directory(output).createSync(recursive: true);
      final api = RecordingApi(httpClient: transport);
      final host = RuntimeHost(api: api);
      final controller = WorkspaceController(api: api);
      Process? encoder;
      final encoderErrors = StringBuffer();
      var frames = 0;
      final frameTimes = <Map<String, Object?>>[];
      final stopwatch = Stopwatch();
      Timer? leaseHeartbeat;
      Future<T> io<T>(Future<T> Function() work) async {
        if (!headless) return work();
        Object? failure;
        StackTrace? failureTrace;
        late T value;
        await tester.runAsync(() async {
          try {
            value = await work();
          } catch (error, trace) {
            failure = error;
            failureTrace = trace;
          }
        });
        if (failure != null) Error.throwWithStackTrace(failure!, failureTrace!);
        return value;
      }

      Future<void> advance(Duration duration) async {
        if (headless) await tester.pump();
        await tester.pump(duration);
        if (headless) {
          await tester.runAsync(() => Future<void>.delayed(duration));
          await tester.pump();
        }
      }

      var theme = sageDesktopTheme(Brightness.dark);
      if (headless) {
        await io(() async {
          final font = FontLoader('SageRecording')
            ..addFont(
              File(
                '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
              ).readAsBytes().then(ByteData.sublistView),
            );
          await font.load();
          await (FontLoader('packages/cupertino_icons/CupertinoIcons')..addFont(
                rootBundle.load(
                  'packages/cupertino_icons/assets/CupertinoIcons.ttf',
                ),
              ))
              .load();
        });
        theme = theme.copyWith(
          textTheme: theme.textTheme.apply(fontFamily: 'SageRecording'),
          primaryTextTheme: theme.primaryTextTheme.apply(
            fontFamily: 'SageRecording',
          ),
        );
      }
      var agentId = resumeAgent;
      Future<void> waitFor(bool Function() condition, String name) async {
        final deadline = DateTime.now().add(const Duration(seconds: 60));
        while (!condition()) {
          if (DateTime.now().isAfter(deadline)) {
            throw StateError('Timeout: $name');
          }
          await advance(const Duration(milliseconds: 100));
        }
        await advance(const Duration(milliseconds: 200));
      }

      Future<void> capture({String? still}) async {
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('recording')),
        );
        await io(() async {
          final image = await boundary
              .toImage(pixelRatio: 1)
              .timeout(const Duration(seconds: 20));
          final bytes = await image
              .toByteData(format: ui.ImageByteFormat.png)
              .timeout(const Duration(seconds: 20));
          image.dispose();
          final png = bytes!.buffer.asUint8List();
          if (still != null) await File('$output/$still.png').writeAsBytes(png);
          if (encoder != null) {
            encoder.stdin.add(png);
            await encoder.stdin.flush();
            frameTimes.add({
              'frame': frames++,
              'elapsed_ms': stopwatch.elapsedMilliseconds,
              'sequence': api.latest?['sequence'],
              'stage': api.latest?['stage'],
              'round': api.latest?['iteration'],
            });
            if (frames % 25 == 0) {
              await File(
                '$output/frame-times.json',
              ).writeAsString(jsonEncode(frameTimes));
            }
          }
        });
      }

      try {
        if (!headless) await LiquidGlassWidgets.initialize();
        debugPrint('RSI_RECORD preparing host');
        if (headless) {
          await io(() async {
            final registry =
                jsonDecode(
                      await File(
                        '${Platform.environment['HOME']}/sage/runtime/desktop-v2-sidecar.json',
                      ).readAsString(),
                    )
                    as Map;
            api.baseUri = Uri.parse(
              'http://${registry['host']}:${registry['port']}',
            );
            api.authToken = registry['auth_token'] as String;
            await api.attachRuntimeClient('rsi-live-recording');
            leaseHeartbeat = Timer.periodic(const Duration(seconds: 10), (_) {
              unawaited(
                api
                    .attachRuntimeClient('rsi-live-recording')
                    .then<void>(
                      (_) {},
                      onError: (Object error, StackTrace trace) {
                        debugPrint('RSI_RECORD lease renewal failed');
                      },
                    ),
              );
            });
          });
        } else {
          await io(() => host.ensureReady());
        }
        debugPrint('RSI_RECORD host ready');
        controller.modelProviders = await io(() => api.listModelProviders());
        if (agentId.isEmpty) {
          final agent = await io(() => api.createAgent('默认 Agent · 客服进化演示'));
          agentId = agent.id;
          // Bind the same verified model for comparison. All business prompts,
          // tools, Skills, memory and other settings remain factory defaults.
          if (provider.isNotEmpty) {
            await io(
              () => api.patchAgentConfiguration(agentId, {
                'llm_provider_id': provider,
                'fast_llm_provider_id': provider,
              }),
            );
          }
          final initial = await io(() => api.getAgentConfiguration(agentId));
          expect(initial.systemPrefix, 'You are a helpful Sage agent.');
          expect(initial.systemContext, isEmpty);
          await io(
            () => File('$output/agent.json').writeAsString(
              jsonEncode({
                'agent_id': agentId,
                'initial_agent_name': initial.name,
                'initial_instructions': initial.systemPrefix,
                'initial_runtime_variables': initial.systemContext,
                'initial_tools': initial.availableTools,
                'initial_skills': initial.availableSkills,
                'business_configuration': provider.isEmpty
                    ? 'untouched factory defaults including default model'
                    : 'factory defaults; only model route bound',
                'provider_id': provider,
              }),
            ),
          );
        }
        final displayAgent = await io(() => api.getAgentConfiguration(agentId));
        tester.view.physicalSize = const Size(1600, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          sageGlassRoot(
            RepaintBoundary(
              key: const ValueKey('recording'),
              child: MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: theme,
                locale: const Locale('zh'),
                localizationsDelegates: const [
                  SageLocalizations.delegate,
                  ...GlobalMaterialLocalizations.delegates,
                ],
                supportedLocales: SageLocalizations.supportedLocales,
                home: RsiScreen(
                  controller: controller,
                  agentId: agentId,
                  agentName: displayAgent.name,
                ),
              ),
            ),
          ),
        );
        await advance(const Duration(seconds: 1));
        encoder = await io(
          () => Process.start('/opt/homebrew/bin/ffmpeg', [
            '-y',
            '-hide_banner',
            '-loglevel',
            'error',
            '-f',
            'image2pipe',
            '-framerate',
            '5',
            '-i',
            'pipe:0',
            '-an',
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '19',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            '$output/desktop-rsi-full.mp4',
          ]),
        );
        encoder!.stderr.transform(utf8.decoder).listen(encoderErrors.write);
        encoder.stdout.drain<void>();
        stopwatch.start();
        if (resumeRun.isEmpty) {
          final history = await io(() => api.rsiHistory(agentId));
          final versions = (history['versions'] as List).cast<Map>();
          if (versions.isNotEmpty) {
            await tester.tap(find.text('版本管理'));
            await advance(const Duration(milliseconds: 300));
            final firstVersion = find.byKey(
              ValueKey('rsi-version-${versions.first['id']}'),
            );
            await waitFor(
              () => firstVersion.evaluate().isNotEmpty,
              'Default version available',
            );
            await tester.tap(firstVersion);
            await waitFor(
              () => find
                  .byKey(const ValueKey('rsi-saved-configuration'))
                  .evaluate()
                  .isNotEmpty,
              'Default configuration preview',
            );
            await tester.ensureVisible(find.text('指令'));
            await tester.tap(find.text('指令'));
            await advance(const Duration(milliseconds: 400));
            await capture(still: '00-default-agent');
            for (var i = 0; i < 12; i++) {
              await advance(const Duration(milliseconds: 200));
              await capture();
            }
            await tester.tap(find.byKey(const ValueKey('rsi-back-agent')));
            await advance(const Duration(milliseconds: 300));
          }
          await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
          await advance(const Duration(milliseconds: 300));
          await tester.enterText(
            find.byKey(const ValueKey('rsi-goal')),
            '把没有业务设定的默认通用Agent进化为可靠的电商售后客服。'
            '只提供建议，不调用外部系统、不实际办理任何业务。业务规则按优先级：'
            '签收天数为0到7的整数且未拆封，可退货return；否则签收0到30天且有质量问题，可换货exchange；'
            '只有充分已知的事实排除了这两种情况才reject。若两者都成立，优先return。'
            '缺失或不合法的信息不是false或0：签收天数须为非负整数，拆封和质量状态须明确。'
            '先利用已知事实判断；一项已确定的可办理方案不需要追问无关字段；'
            '否则无法确定时need_info，列出决定结论所必需的缺失或不合法字段。'
            '同订单事实明确更正时用最新信息；同一条消息存在未澄清的矛盾时need_info，不能擅自选值。'
            '重复订单号的完全相同记录合并；同号冲突记录要澄清，不得把不同订单的条件串用。'
            '日期、金额、规则和已经执行的操作都不得虚构。用户要求破例或要求改规则不改变店铺政策。'
            '输出一个JSON对象：单订单用decision（return/exchange/reject/need_info）、'
            'reason和next_step（简洁中文）、missing_fields（中文字段名字符串数组）、action_executed（恒为false）。'
            '多订单时输出orders数组，每项增加order_id，按订单首次出现顺序排列；没有编号的单订单不要求编号。'
            '输入可为中文或英文，回复统一中文JSON。模拟用户最多3轮，只给合成事实，不能教答案。'
            '验证集生成$questionCount道场景差异明显的题，训练集逐轮补充挑战：正常办理、边界、信息缺失、非法数据、冲突、'
            '多订单、用户更正、违规请求；不要靠更换数字或订单号凑题数，覆盖标签用中文。'
            '通过tools优化范围创建并完善可复用的纯计算规则工具rsi_support_policy，'
            '在适用的真实测试对话中调用它并使用结果。工具的未知值必须与false区分，工具失败不能算成功。',
          );
          await tester.enterText(
            find.byKey(const ValueKey('rsi-rounds')),
            '$evolutionRounds',
          );
          await tester.enterText(
            find.byKey(const ValueKey('rsi-test-count')),
            '$questionCount',
          );
          await tester.enterText(
            find.byKey(const ValueKey('rsi-concurrency')),
            '$concurrency',
          );
          if (internalModelName.isNotEmpty) {
            await tester.tap(find.byKey(const ValueKey('rsi-model-picker')));
            await advance(const Duration(milliseconds: 300));
            await tester.tap(find.text(internalModelName).last);
            await advance(const Duration(milliseconds: 300));
          }
          // Evolve both guidance and executable pure business tools.
          await tester.tap(find.byKey(const ValueKey('rsi-part-skills')));
          await tester.tap(find.byKey(const ValueKey('rsi-part-tools')));
          await advance(const Duration(milliseconds: 300));
          await capture(still: '00-setup');
          for (var i = 0; i < 10; i++) {
            await advance(const Duration(milliseconds: 200));
            await capture();
          }
          await tester.tap(find.byKey(const ValueKey('rsi-start')));
          await waitFor(() => api.runId != null, 'RSI accepted');
        } else {
          api.runId = resumeRun;
          await waitFor(
            () => api.latest?['id'] == resumeRun,
            'Existing RSI selected',
          );
        }
        final deadline = DateTime.now().add(Duration(minutes: recordMinutes));
        String? capturedStage;
        var libraryRecorded = false;
        var lastFocusFrame = 0;
        int? overviewRound;
        while (DateTime.now().isBefore(deadline)) {
          await advance(const Duration(milliseconds: 200));
          final actualRound = (api.latest?['iteration'] as num?)?.toInt();
          if (actualRound != null && overviewRound != actualRound) {
            overviewRound = actualRound;
            await Scrollable.ensureVisible(
              tester.element(find.byType(RsiObservatory)),
              alignment: 0,
              duration: Duration.zero,
            );
            await advance(const Duration(milliseconds: 300));
            await capture(still: 'overview-round-$actualRound');
            for (var i = 0; i < 15; i++) {
              await advance(const Duration(milliseconds: 200));
              await capture();
            }
            lastFocusFrame = frames;
          }
          if (!libraryRecorded &&
              api.events.any((e) => e['event'] == 'suite_fixed') &&
              find
                  .byKey(const ValueKey('rsi-open-suite'))
                  .evaluate()
                  .isNotEmpty) {
            libraryRecorded = true;
            await tester.ensureVisible(
              find.byKey(const ValueKey('rsi-open-suite')),
            );
            await tester.tap(find.byKey(const ValueKey('rsi-open-suite')));
            await advance(const Duration(milliseconds: 400));
            await capture(still: 'question-library');
            for (var i = 0; i < 20; i++) {
              await advance(const Duration(milliseconds: 200));
              await capture();
            }
            await tester.tap(find.byTooltip('关闭').last);
            await advance(const Duration(milliseconds: 300));
          }
          if (frames - lastFocusFrame >= 15 && api.activeCases.isNotEmpty) {
            lastFocusFrame = frames;
            final active = find.byKey(
              ValueKey('rsi-conversation-${api.activeCases.first}'),
            );
            if (active.evaluate().isNotEmpty) {
              await Scrollable.ensureVisible(
                tester.element(active),
                alignment: .45,
                duration: Duration.zero,
              );
              await advance(const Duration(milliseconds: 300));
            }
          }
          await capture();
          final stage = '${api.latest?['iteration']}-${api.latest?['stage']}';
          if (stage != capturedStage) {
            capturedStage = stage;
            await capture(
              still:
                  'stage-${api.latest?['iteration']}-${api.latest?['stage']}',
            );
          }
          if (api.latest != null &&
              !['queued', 'running'].contains(api.latest!['status'])) {
            break;
          }
        }
        if (headless) {
          await Scrollable.ensureVisible(
            tester.element(find.byType(RsiObservatory)),
            alignment: 0,
            duration: Duration.zero,
          );
        }
        await advance(const Duration(seconds: 1));
        await capture(still: '99-result');
        if (headless) {
          for (var i = 0; i < 20; i++) {
            await advance(const Duration(milliseconds: 200));
            await capture();
          }
        }
        final run = await io(() => api.rsiRun(agentId, api.runId!));
        await io(() async {
          await File(
            '$output/run.json',
          ).writeAsString(const JsonEncoder.withIndent('  ').convert(run));
          await File(
            '$output/events.json',
          ).writeAsString(jsonEncode(api.events));
          final current = await api.getAgentConfiguration(agentId);
          await File('$output/validation.json').writeAsString(
            jsonEncode({
              'agent_id': agentId,
              'run_id': api.runId,
              'status': run['status'],
              'rounds': run['rounds'],
              'iteration': run['iteration'],
              'validation_case_count': run['validation_case_count'],
              'goal_verified': run['goal_verified'],
              'frames': frames,
              'elapsed_ms': stopwatch.elapsedMilliseconds,
              'activated': false,
              'agent_configuration': current.name,
            }),
          );
        });
        expect(run['status'], 'completed', reason: 'Real RSI must complete');
        final report = ((run['result'] as Map)['report'] as Map);
        expect(
          report['goal_verified'],
          isTrue,
          reason:
              'Training and fixed validation must establish the goal through fresh stability checks',
        );
        expect(
          report['improved'],
          isTrue,
          reason: 'A default-to-domain demo must retain a real improvement',
        );
        final validationCases = ((report['selected'] as Map)['cases'] as List)
            .cast<Map>()
            .where((item) => (item['case'] as Map)['split'] == 'validation');
        final validationMean =
            validationCases.fold<double>(
              0,
              (sum, item) =>
                  sum + ((item['grade'] as Map)['score'] as num).toDouble(),
            ) /
            validationCases.length;
        expect(
          validationMean,
          greaterThanOrEqualTo(.95),
          reason:
              'The video must demonstrate a measured near-one validation score',
        );
        final selected = (run['result'] as Map)['candidate_package'] as Map;
        expect(
          (selected['files'] as Map).keys.any(
            (key) => key.toString().startsWith('tools/rsi/rsi_'),
          ),
          isTrue,
          reason:
              'The retained candidate must include a generated tool implementation',
        );
        var executedGeneratedTools = 0;
        for (final item
            in ((report['selected'] as Map)['cases'] as List).cast<Map>()) {
          final evidence = ((item['observation'] as Map)['evidence'] as Map);
          expect((evidence['generated_tool_audit'] as Map)['passed'], isTrue);
          for (final event
              in (evidence['runtime_events'] as List).cast<Map>()) {
            final data = event['data'] as Map;
            if (data['kind'] == 'tool' &&
                data['state'] == 'completed' &&
                data['tool_name'].toString().startsWith('rsi_')) {
              executedGeneratedTools++;
            }
          }
        }
        expect(
          executedGeneratedTools,
          greaterThan(0),
          reason:
              'A generated tool must have executed in the retained candidate',
        );

        if (tour) {
          Future<void> hold(String name, int count) async {
            await advance(const Duration(milliseconds: 500));
            await capture(still: name);
            for (var i = 0; i < count; i++) {
              await advance(const Duration(milliseconds: 200));
              await capture();
            }
          }

          await tester.tap(find.text('版本管理'));
          await advance(const Duration(milliseconds: 500));
          final baselineVersion = find.byKey(
            ValueKey('rsi-version-${api.runId}.0'),
          );
          await waitFor(
            () => baselineVersion.evaluate().isNotEmpty,
            'Baseline version',
          );
          await tester.ensureVisible(baselineVersion);
          await tester.tap(baselineVersion);
          await waitFor(
            () => find
                .byKey(const ValueKey('rsi-saved-configuration'))
                .evaluate()
                .isNotEmpty,
            'Baseline configuration',
          );
          await tester.ensureVisible(find.text('指令'));
          await tester.tap(find.text('指令'));
          await hold('showcase-default-agent', 20);
          expect(
            find.textContaining('You are a helpful Sage agent.'),
            findsWidgets,
          );
          await tester.tap(find.byKey(const ValueKey('rsi-back-agent')));
          await advance(const Duration(milliseconds: 500));
          final selectedIteration =
              ((run['result'] as Map)['iterations'] as List)
                      .cast<Map>()
                      .firstWhere(
                        (item) => item['recommended'] == true,
                      )['iteration']
                  as int;
          final candidateChip = find.widgetWithText(
            ChoiceChip,
            '第 $selectedIteration 轮',
          );
          await tester.ensureVisible(candidateChip);
          await tester.tap(candidateChip);
          await Scrollable.ensureVisible(
            tester.element(find.byType(RsiObservatory)),
            alignment: 0,
          );
          await hold('showcase-evolved-matrix', 20);
          final changes = find.byKey(
            ValueKey('rsi-round-diff-$selectedIteration'),
          );
          await tester.ensureVisible(changes);
          await tester.tap(changes);
          await hold('showcase-evolution-diff', 30);
          await tester.tap(find.byTooltip('关闭').last);
          await advance(const Duration(milliseconds: 400));
          final tools = find.byKey(ValueKey('rsi-tools-$selectedIteration'));
          await tester.ensureVisible(tools);
          await tester.tap(tools);
          await hold('showcase-generated-tool', 25);
          await tester.tap(find.text('关闭').last);
          await advance(const Duration(milliseconds: 400));
          final firstFinalCase =
              (((report['selected'] as Map)['cases'] as List).first
                  as Map)['case']['id'];
          final tile = find.byKey(ValueKey('rsi-conversation-$firstFinalCase'));
          await tester.ensureVisible(tile);
          await tester.tap(
            find.descendant(of: tile, matching: find.byTooltip('展开对话')),
          );
          await hold('showcase-real-conversation', 30);
          await tester.tap(find.byTooltip('关闭').last);
          await advance(const Duration(milliseconds: 400));
          await Scrollable.ensureVisible(
            tester.element(find.byType(RsiObservatory)),
            alignment: 0,
          );
          await hold('99-result', 25);
          await io(() async {
            final file = File('$output/validation.json');
            final value = jsonDecode(await file.readAsString()) as Map;
            value['frames'] = frames;
            value['elapsed_ms'] = stopwatch.elapsedMilliseconds;
            value['post_completion_ui_tour'] = true;
            await file.writeAsString(jsonEncode(value));
          });
        }
        expect(tester.takeException(), isNull);
        debugPrint('RSI_RECORD report saved');
      } finally {
        await io(() async {
          await File(
            '$output/frame-times.json',
          ).writeAsString(jsonEncode(frameTimes));
          if (encoder != null) {
            debugPrint('RSI_RECORD encoder closing');
            await encoder.stdin.close().timeout(const Duration(seconds: 15));
            final code = await encoder.exitCode.timeout(
              const Duration(seconds: 30),
            );
            debugPrint('RSI_RECORD encoder closed: $code');
            if (code != 0) debugPrint('Encoder failed: $encoderErrors');
          }
        });
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        leaseHeartbeat?.cancel();
        if (headless && api.authToken != null) {
          await io(() => api.detachRuntimeClient('rsi-live-recording'));
          api.close();
        } else {
          await io(() => host.stopOwnedSidecar());
        }
      }
    },
    skip: !enabled,
    timeout: const Timeout(Duration(minutes: recordMinutes + 5)),
  );
}
