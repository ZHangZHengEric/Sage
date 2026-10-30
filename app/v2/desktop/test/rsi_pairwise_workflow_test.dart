import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'rsi_evaluation_workflow_test.dart' show PlanApi, tapVisible;

class ComparisonApi extends PlanApi {
  ComparisonApi() {
    scorers.add({
      'id': 'dataset-comparator',
      'name': 'comparison.py',
      'validation': {'status': 'passed', 'protocol': 'sage.rsi.comparison/v1'},
    });
  }
}

void main() {
  for (final brightness in [Brightness.light, Brightness.dark]) {
    testWidgets('select comparison plugin and submit paired mean $brightness', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1440, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = ComparisonApi();
      final controller = WorkspaceController(api: api);
      addTearDown(() {
        controller.dispose();
        api.close();
      });
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
      await tapVisible(tester, 'rsi-evaluation-mode-picker');
      await tapVisible(tester, 'rsi-evaluation-mode-pairwise');
      await tapVisible(tester, 'rsi-scorer-picker');
      await tapVisible(tester, 'rsi-scorer-dataset-comparator');
      await tester.enterText(
        find.byKey(const ValueKey('rsi-goal')),
        'Improve clarity',
      );
      await tester.enterText(find.byKey(const ValueKey('rsi-rounds')), '5');
      await tapVisible(tester, 'rsi-start');
      expect(api.startOptions!['scorer_id'], 'dataset-comparator');
      expect(api.startOptions!['builtin_scoring'], {'mode': 'pairwise'});
      expect(api.startOptions!['evaluation_aggregation'], 'mean');
      expect(api.startOptions!['max_skill_count'], 5);
      expect(api.startOptions!['rounds'], 5);
      expect(api.startOptions!['max_concurrency'], 8);
      expect(api.startOptions!['evaluation_repeats'], 2);
      expect(api.startOptions!['human_test_repeats'], 2);
      expect(api.startOptions!['optimization_scope'], containsAll(['instructions', 'skills']));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }
}
