import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'rsi_screen_test.dart' show RsiApi;

class HistoryDeletionApi extends RsiApi {
  HistoryDeletionApi({this.singleRun = false});
  final bool singleRun;
  bool rejectDelete = false;
  final deleted = <String>[];
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    ...await super.rsiHistory(agentId),
    'runs': [
      if (!singleRun)
        {
          'id': 'active',
          'goal': 'Current running experiment',
          'status': 'running',
          'rounds': 8,
          'iteration': 0,
        },
      if (!deleted.contains('old'))
        {
          'id': 'old',
          'goal': 'Old failed experiment',
          'status': 'failed',
          'rounds': 8,
          'iteration': 0,
        },
    ],
  };
  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String runId, {
    int afterSequence = 0,
  }) async => {
    ...await super.rsiRun(agentId, runId, afterSequence: afterSequence),
    'status': runId == 'active' ? 'running' : 'failed',
  };
  @override
  Future<void> deleteRsiRun(String agentId, String runId) async {
    if (rejectDelete) throw Exception('Delete failed');
    deleted.add(runId);
  }
}

Future<void> openHistory(WidgetTester tester, HistoryDeletionApi api) async {
  final controller = WorkspaceController(api: api);
  addTearDown(() {
    controller.dispose();
    api.close();
  });
  tester.view.physicalSize = const Size(1440, 1100);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(disableAnimations: true),
        child: child!,
      ),
      home: TickerMode(
        enabled: false,
        child: RsiScreen(
          controller: controller,
          agentId: 'agent',
          agentName: 'Sage',
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const ValueKey('rsi-toggle-history')));
  await tester.pumpAndSettle();
}

Future<void> deleteMenu(WidgetTester tester) async {
  await tester.tap(
    find.byKey(const ValueKey('rsi-run-old')),
    buttons: kSecondaryMouseButton,
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const ValueKey('rsi-delete-run-old')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'right click requires confirmation and deleting old history preserves the active selection',
    (tester) async {
      final api = HistoryDeletionApi();
      await openHistory(tester, api);
      await deleteMenu(tester);
      expect(find.textContaining('已保存的 Agent 版本和数据集仍会保留'), findsOneWidget);
      expect(api.deleted, isEmpty);
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(api.deleted, isEmpty);
      expect(find.byKey(const ValueKey('rsi-run-old')), findsOneWidget);
      await deleteMenu(tester);
      await tester.tap(find.byKey(const ValueKey('rsi-confirm-delete-run')));
      await tester.pumpAndSettle();
      expect(api.deleted, ['old']);
      expect(find.byKey(const ValueKey('rsi-run-old')), findsNothing);
      expect(
        tester
            .widget<ListTile>(find.byKey(const ValueKey('rsi-run-active')))
            .selected,
        isTrue,
      );
      await tester.tap(
        find.byKey(const ValueKey('rsi-run-active')),
        buttons: kSecondaryMouseButton,
      );
      await tester.pumpAndSettle();
      final item = tester.widget<PopupMenuItem<String>>(
        find.byKey(const ValueKey('rsi-delete-run-active')),
      );
      expect(item.enabled, isFalse);
      expect(find.text('删除（请先停止实验）'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'deleting the selected final history entry clears details and remains deleted after polling',
    (tester) async {
      final api = HistoryDeletionApi(singleRun: true);
      await openHistory(tester, api);
      expect(
        tester
            .widget<ListTile>(find.byKey(const ValueKey('rsi-run-old')))
            .selected,
        isTrue,
      );
      await deleteMenu(tester);
      await tester.tap(find.byKey(const ValueKey('rsi-confirm-delete-run')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('rsi-run-old')), findsNothing);
      expect(find.text('暂无 RSI 记录'), findsOneWidget);
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.text('暂无 RSI 记录'), findsOneWidget);
      expect(api.deleted, ['old']);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'failed deletion leaves the record selected and shows the error',
    (tester) async {
      final api = HistoryDeletionApi(singleRun: true)..rejectDelete = true;
      await openHistory(tester, api);
      await deleteMenu(tester);
      await tester.tap(find.byKey(const ValueKey('rsi-confirm-delete-run')));
      await tester.pumpAndSettle();
      expect(api.deleted, isEmpty);
      expect(find.byKey(const ValueKey('rsi-run-old')), findsOneWidget);
      expect(find.textContaining('Delete failed'), findsOneWidget);
      expect(
        tester
            .widget<ListTile>(find.byKey(const ValueKey('rsi-run-old')))
            .selected,
        isTrue,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
