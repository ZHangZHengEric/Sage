import 'dart:convert';
import 'dart:io';

import 'package:file_selector_platform_interface/file_selector_platform_interface.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'rsi_screen_test.dart' show RsiApi;

final dataset = <String, Object?>{
  'format_version': 'sage.rsi.dataset/v1',
  'name': 'Contract dataset',
  'cases': [
    {'id': 'train', 'input': '6*7?', 'rubric': '42', 'reference_answer': '42'},
    {
      'id': 'dev',
      'input': '40+2?',
      'rubric': '42',
      'split': 'validation',
      'reference_answer': '42',
    },
    {
      'id': 'test',
      'input': '21*2?',
      'rubric': '42',
      'split': 'test',
      'reference_answer': '42',
    },
  ],
};
final scorerSource = """
async def score(request):
    import os
    correct = request['observation']['output'].strip() == '42'
    if 'SAGE_RSI_SCORER_MODEL_API' in os.environ:
        from sagents.v2.optimization.scorer_runtime import get_model_provider
        from sagents.v2.model.contracts import ModelRequest, ModelMessage, ModelEventKind
        from sagents.v2.contracts.items import TextBlock
        model = get_model_provider()
        async for event in model.stream(ModelRequest(request_id='fixture-score', run_id='scorer',
                model_binding=model.model_binding,
                messages=(ModelMessage(role='user', content=(TextBlock(text='What is 6*7?'),)),))):
            if event.kind == ModelEventKind.COMPLETED:
                correct = correct and event.response.text.strip() == '42'
    return {'score': .8 if correct else 0, 'passed': correct, 'rationale': 'Contract fixture score'}

SCORER_TEST_CASES = [{'request': {'goal': 'Accuracy', 'case': {'id': 'contract', 'input': '6*7?', 'rubric': '42'}, 'observation': {'state': 'completed', 'output': '42'}}, 'expected_score': .8, 'expected_passed': True}]
""";

class PlanFileSelector extends FileSelectorPlatform {
  @override
  Future<XFile?> openFile({
    List<XTypeGroup>? acceptedTypeGroups,
    String? initialDirectory,
    String? confirmButtonText,
  }) async => acceptedTypeGroups!.first.extensions!.contains('py')
      ? XFile.fromData(
          utf8.encode(scorerSource),
          name: 'accuracy.py',
          path: '/tmp/accuracy.py',
          mimeType: 'text/x-python',
        )
      : XFile.fromData(
          utf8.encode(jsonEncode(dataset)),
          name: 'dataset.json',
          path: '/tmp/dataset.json',
          mimeType: 'application/json',
        );
}

class PlanApi extends RsiApi {
  final scorers = <Map<String, Object?>>[];
  Map<String, Object?>? imported;
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    ...await super.rsiHistory(agentId),
    'scorers': scorers,
  };
  @override
  Future<Map<String, Object?>> importRsiScorer(
    String agentId,
    Map<String, Object?> scorer,
  ) async {
    imported = scorer;
    final result = <String, Object?>{
      'id': 'scorer-contract',
      'name': scorer['name'],
      'validation': {'status': 'passed', 'cases': 1},
    };
    scorers.add(result);
    return result;
  }
}

Future<void> tapVisible(WidgetTester tester, String key) async {
  final finder = find.byKey(ValueKey(key));
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  final readyPath = Platform.environment['RSI_EVALUATION_TEST_READY'];
  testWidgets(
    'real API: import scorer, start RSI, finish and display fixed scores',
    (tester) async {
      final ready =
          jsonDecode(File(readyPath!).readAsStringSync())
              as Map<String, dynamic>;
      final overrides = HttpOverrides.current;
      HttpOverrides.global = null;
      final api = V2ApiClient(
        baseUri: Uri.parse(ready['url'] as String),
        authToken: ready['auth_token'] as String,
      );
      final controller = WorkspaceController(api: api);
      final previous = FileSelectorPlatform.instance;
      FileSelectorPlatform.instance = PlanFileSelector();
      addTearDown(() {
        FileSelectorPlatform.instance = previous;
        HttpOverrides.global = overrides;
        api.close();
      });
      tester.view.physicalSize = const Size(1440, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final agent = ready['agent_id'] as String;
      Future<void> progress() async {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 100)),
        );
        await tester.pump(const Duration(milliseconds: 500));
      }

      await tester.pumpWidget(
        MaterialApp(
          home: RsiScreen(
            controller: controller,
            agentId: agent,
            agentName: 'Contract Agent',
          ),
        ),
      );
      for (var i = 0; i < 10; i++) {
        await progress();
      }
      await tapVisible(tester, 'rsi-toggle-setup');
      await tapVisible(tester, 'rsi-import-scorer');
      for (
        var i = 0;
        i < 100 && find.text('accuracy.py').evaluate().isEmpty;
        i++
      ) {
        await progress();
      }
      expect(find.text('accuracy.py'), findsOneWidget);
      await tapVisible(tester, 'rsi-import-suite');
      await tester.enterText(
        find.byKey(const ValueKey('rsi-goal')),
        'Answer accurately',
      );
      await tester.enterText(
        find.byKey(const ValueKey('rsi-training-increment')),
        '0',
      );
      await tester.enterText(find.byKey(const ValueKey('rsi-rounds')), '1');
      await tapVisible(tester, 'rsi-start');
      Map<String, Object?>? finished;
      for (var i = 0; i < 500; i++) {
        await progress();
        final history = await tester.runAsync(() => api.rsiHistory(agent));
        final runs = history?['runs'] as List? ?? [];
        if (runs.isEmpty) continue;
        final run = (runs.first as Map).cast<String, Object?>();
        if (run['status'] == 'failed') {
          fail('Real RSI failed: ${run['error_type']}');
        }
        if (run['status'] == 'completed') {
          finished = await tester.runAsync(
            () => api.rsiRun(agent, run['id'] as String),
          );
          break;
        }
      }
      expect(finished, isNotNull);
      final observations = finished!['test_observations'] as List;
      expect(observations, isNotEmpty);
      expect((observations.first as Map)['scores'], containsPair('test', .8));
      expect(finished['scorer_id'], isNotNull);
      for (var i = 0; i < 8; i++) {
        await progress();
      }
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
    skip: readyPath == null,
  );
  for (final brightness in Brightness.values) {
    testWidgets('import, select, reset default and start ${brightness.name}', (
      tester,
    ) async {
      final previous = FileSelectorPlatform.instance;
      FileSelectorPlatform.instance = PlanFileSelector();
      addTearDown(() => FileSelectorPlatform.instance = previous);
      tester.view.physicalSize = const Size(1440, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = PlanApi();
      final controller = WorkspaceController(api: api);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: RsiScreen(
            controller: controller,
            agentId: 'agent',
            agentName: 'Sage',
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tapVisible(tester, 'rsi-toggle-setup');
      await tapVisible(tester, 'rsi-import-scorer');
      expect(api.imported!['source'], scorerSource);
      await tester.enterText(
        find.byKey(const ValueKey('rsi-goal')),
        'Answer accurately',
      );
      expect(find.text('accuracy.py'), findsOneWidget);
      await tapVisible(tester, 'rsi-scorer-picker');
      await tapVisible(tester, 'rsi-scorer-default');
      await tapVisible(tester, 'rsi-start');
      expect(api.startOptions!.containsKey('scorer_id'), isFalse);
      expect(api.startOptions!.containsKey('scorer'), isFalse);
      await tapVisible(tester, 'rsi-toggle-setup');
      await tapVisible(tester, 'rsi-scorer-picker');
      await tapVisible(tester, 'rsi-scorer-scorer-contract');
      await tapVisible(tester, 'rsi-import-suite');
      await tapVisible(tester, 'rsi-start');
      expect(api.startOptions!['scorer_id'], 'scorer-contract');
      expect(api.startOptions!['dataset'], dataset);
      expect(api.startOptions!['validation_case_count'], 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    });
  }
}
