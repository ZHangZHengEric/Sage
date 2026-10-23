import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_dataset_revision.dart';

Map<String, Object?> sourceVersion() => {
  'id': 'source-v1',
  'dataset': {
    'name': 'Benchmark',
    'cases': [
      {
        'id': 'train',
        'input': 'Question',
        'rubric': 'Answer',
        'split': 'training',
      },
      {
        'id': 'suspected',
        'input': 'Question with a missing fact',
        'rubric': 'Answer',
        'split': 'validation',
      },
      {
        'id': 'other-dev',
        'input': 'Question',
        'rubric': 'Answer',
        'split': 'validation',
      },
      {'id': 'test', 'input': 'Question', 'rubric': 'Answer', 'split': 'test'},
    ],
  },
  'manifest': {
    'version_id': 'source-v1',
    'source_version': 'source-v1',
    'name': 'Benchmark',
    'label': 'original',
    'original_count': 4,
    'excluded_count': 0,
    'active_count': 4,
    'exclusions': [],
    'counts': {
      'training': {'original': 1, 'active': 1},
      'validation': {'original': 2, 'active': 2},
      'test': {'original': 1, 'active': 1},
    },
  },
};

void main() {
  testWidgets(
    'human exclusion requires evidence and explicit confirmation and returns a new-version proposal',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final version = sourceVersion();
      final original = jsonEncode(version);
      Map<String, Object?>? proposal;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  proposal = await showDialog<Map<String, Object?>>(
                    context: context,
                    builder: (_) => RsiDatasetRevisionDialog(
                      version: version,
                      chinese: true,
                      issue: const {
                        'case_ids': ['suspected'],
                        'rationale': 'A required fact might be missing',
                        'impact': 'Task may stop',
                      },
                    ),
                  );
                },
                child: const Text('Review'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Review'));
      await tester.pumpAndSettle();
      expect(find.textContaining('模型意见不是已确认的数据错误'), findsOneWidget);
      expect(find.textContaining('当前实验不变'), findsOneWidget);
      final submit = find.byKey(const ValueKey('dataset-revision-submit'));
      expect(tester.widget<FilledButton>(submit).onPressed, isNull);
      await tester.ensureVisible(
        find.byKey(const ValueKey('dataset-revision-confirm')),
      );
      await tester.tap(find.byKey(const ValueKey('dataset-revision-confirm')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(proposal, isNull);
      expect(find.text('请提供证据'), findsOneWidget);
      await tester.enterText(
        find.byKey(const ValueKey('dataset-revision-reason')),
        'Required fixture field is absent',
      );
      await tester.enterText(
        find.byKey(const ValueKey('dataset-revision-evidence')),
        'Quoted original scenario field',
      );
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(proposal!['confirmed'], isTrue);
      expect(proposal!['expected_version'], 'source-v1');
      final mark = (proposal!['exclusions'] as List).single as Map;
      expect(mark['case_id'], 'suspected');
      expect(mark['evidence'], ['Quoted original scenario field']);
      expect(proposal!.containsKey('operator'), isFalse);
      expect(jsonEncode(version), original);
    },
  );
}
