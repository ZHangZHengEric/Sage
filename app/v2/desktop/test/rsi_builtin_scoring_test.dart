import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'rsi_screen_test.dart' show RsiApi;

void main() {
  for (final brightness in Brightness.values) {
    testWidgets('built-in scoring defaults and selection ${brightness.name}', (
      tester,
    ) async {
      final api = RsiApi();
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
      await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('rsi-goal')),
        'Improve task quality',
      );
      final picker = find.byKey(const ValueKey('rsi-scorer-picker'));
      await tester.ensureVisible(picker);
      await tester.tap(picker);
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<ListTile>(find.byKey(const ValueKey('rsi-scorer-default')))
            .selected,
        isTrue,
      );
      await tester.tap(find.byKey(const ValueKey('rsi-scorer-quality_cost')));
      await tester.pumpAndSettle();
      expect(find.text('质量与成本'), findsOneWidget);
      await tester.tap(picker);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('rsi-scorer-default')));
      await tester.pumpAndSettle();
      expect(find.text('质量'), findsOneWidget);
      await tester.tap(picker);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('rsi-scorer-quality_tokens')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const ValueKey('rsi-start')));
      await tester.tap(find.byKey(const ValueKey('rsi-start')));
      await tester.pumpAndSettle();
      expect(api.startOptions?['builtin_scoring'], {'mode': 'quality_tokens'});
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
      api.close();
    });
  }
}
