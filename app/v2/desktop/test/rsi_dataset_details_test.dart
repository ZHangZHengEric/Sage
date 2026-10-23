import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_dataset_details.dart';
import 'rsi_dataset_revision_test.dart' show sourceVersion;

void main() {
  for (final width in [380.0, 1100.0]) {
    testWidgets(
      'dataset details can reopen, filter and inspect cases at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            home: Builder(
              builder: (context) => Scaffold(
                body: TextButton(
                  onPressed: () => showDialog<void>(
                    context: context,
                    builder: (_) => RsiDatasetDetailsDialog(
                      version: sourceVersion(),
                      chinese: true,
                    ),
                  ),
                  child: const Text('详情'),
                ),
              ),
            ),
          ),
        );
        for (var attempt = 0; attempt < 2; attempt++) {
          await tester.tap(find.text('详情'));
          await tester.pumpAndSettle();
          expect(
            find.byKey(const ValueKey('rsi-dataset-details-dialog')),
            findsOneWidget,
          );
          expect(find.text('数据集详情'), findsOneWidget);
          await tester.tap(find.text('题目 (4)'));
          await tester.pumpAndSettle();
          await tester.enterText(
            find.byKey(const ValueKey('rsi-dataset-case-search')),
            'suspected',
          );
          await tester.pumpAndSettle();
          final caseRow = find.byKey(const ValueKey('dataset-case-suspected'));
          expect(caseRow, findsOneWidget);
          expect(
            find.byKey(const ValueKey('dataset-case-train')),
            findsNothing,
          );
          await tester.tap(
            find.descendant(of: caseRow, matching: find.text('suspected')),
          );
          await tester.pumpAndSettle();
          expect(find.text('Question with a missing fact'), findsOneWidget);
          expect(find.text('评分规则'), findsOneWidget);
          await tester.tap(find.text('排除记录 (0)'));
          await tester.pumpAndSettle();
          expect(find.text('此版本没有排除题目'), findsOneWidget);
          await tester.tap(
            find.byKey(const ValueKey('rsi-dataset-details-close')),
          );
          await tester.pumpAndSettle();
          expect(
            find.byKey(const ValueKey('rsi-dataset-details-dialog')),
            findsNothing,
          );
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
}
