import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_diff.dart';

Map<String, Object?> package(
  String instruction, {
  List<String> tools = const [],
  Map<String, Object?> files = const {},
  int budget = 8,
  String version = '1',
}) => {
  'manifest': {
    'metadata': {'version': version},
    'entrypoint': {'agent': 'main'},
    'agents': {
      'main': {
        'instructions': {'inline': instruction},
        'tools': tools,
        'skills': [],
        'budgets': {'max_steps': budget},
      },
    },
  },
  'files': files,
};
Map<String, Object?> record(
  int round,
  String parent,
  String hash,
  bool accepted,
  Map<String, Object?> candidate,
) => {
  'round': round,
  'parent_hash': parent,
  'accepted': accepted,
  'candidate_package': candidate,
  'evaluation': {'package_hash': hash},
};
Map<String, Object?> run(List<Map<String, Object?>> records) => {
  'result': {
    'iterations': [
      {'iteration': 0, 'package': package('base')},
    ],
    'report': {
      'baseline': {'package_hash': 'base-hash'},
      'rounds': records,
    },
  },
};

void main() {
  testWidgets(
    'round changes show only selected proposal and recorded rationale',
    (tester) async {
      final records = [
        {
          ...record(1, 'base-hash', 'first', true, package('first')),
          'patch': {'rationale': 'Fix missing verification'},
        },
        {
          ...record(2, 'first', 'second', false, package('second')),
          'patch': {'rationale': 'Improve tool handling'},
        },
      ];
      Future<void> render(int selected) async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: RsiRoundChanges(
                run: run(records),
                events: const [],
                settings: const LiquidGlassSettings(),
                chinese: true,
                selectedRound: selected,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
      }

      await render(2);
      expect(find.byKey(const ValueKey('rsi-round-diff-2')), findsOneWidget);
      expect(find.byKey(const ValueKey('rsi-round-diff-1')), findsNothing);
      expect(find.text('Improve tool handling'), findsOneWidget);
      expect(find.text('Fix missing verification'), findsNothing);
      await render(1);
      expect(find.byKey(const ValueKey('rsi-round-diff-1')), findsOneWidget);
      expect(find.byKey(const ValueKey('rsi-round-diff-2')), findsNothing);
      expect(find.text('Fix missing verification'), findsOneWidget);
      await render(0);
      expect(find.text('基线轮，无进化改动'), findsOneWidget);
      expect(find.byKey(const ValueKey('rsi-round-diff-1')), findsNothing);
      await render(3);
      expect(find.text('本轮暂无改动记录'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  test(
    'file-backed system prompt appears once as instructions in the diff',
    () {
      final candidate = package(
        'unused',
        files: {'prompts/system.md': 'Rewritten prompt'},
      );
      final manifest = candidate['manifest'] as Map<String, Object?>;
      final agents = manifest['agents'] as Map<String, Object?>;
      (agents['main'] as Map<String, Object?>)['instructions'] = {
        'path': 'prompts/system.md',
      };
      final diffs = collectRsiRoundDiffs(
        run([record(1, 'base-hash', 'new', true, candidate)]),
        [],
      );
      expect(diffs.single.changes, hasLength(1));
      expect(diffs.single.changes.single.kind, 'instructions');
      expect(diffs.single.changes.single.after, 'Rewritten prompt');
    },
  );
  test('diff follows actual retained parent after a rejected proposal', () {
    final records = [
      record(1, 'base-hash', 'first', true, package('base\nfirst')),
      record(2, 'first', 'rejected', false, package('base\nwrong')),
      record(3, 'first', 'third', true, package('base\nfirst\nthird')),
    ];
    final diffs = collectRsiRoundDiffs(run(records), []);
    expect(diffs[2].parentRound, 1);
    expect(diffs[2].changes.single.before, 'base\nfirst');
    expect(diffs[2].changes.single.after, 'base\nfirst\nthird');
    expect(diffs[1].accepted, isFalse);
  });
  test(
    'no-op versions do not redirect parent hashes or invent version-only changes',
    () {
      final first = package('base\nfirst');
      final records = [
        record(1, 'base-hash', 'first', true, first),
        {
          ...record(2, 'first', 'first', false, first),
          'evaluation_reused': true,
        },
        record(3, 'first', 'third', true, package('base\nthird')),
      ];
      final diffs = collectRsiRoundDiffs(run(records), []);
      expect(diffs[1].changes, isEmpty);
      expect(diffs[1].reused, isTrue);
      expect(diffs[2].parentRound, 1);
      expect(
        collectRsiRoundDiffs(
          run([
            record(
              1,
              'base-hash',
              'first',
              true,
              package('base', version: '2'),
            ),
          ]),
          [],
        ).single.changes,
        isEmpty,
      );
    },
  );
  test(
    'unknown parents and invalid proposals are explicit rather than fabricated diffs',
    () {
      final diff = collectRsiRoundDiffs(
        run([record(1, 'missing', 'candidate', false, package('new'))]),
        [],
      ).single;
      expect(diff.parentAvailable, isFalse);
      expect(diff.changes, isEmpty);
      final invalid = collectRsiRoundDiffs(
        run([
          {
            'round': 1,
            'parent_hash': 'base-hash',
            'accepted': false,
            'patch': {
              'files': {'forbidden': 'x'},
            },
          },
        ]),
        [],
      ).single;
      expect(invalid.parentAvailable, isTrue);
      expect(invalid.candidateMissing, isTrue);
    },
  );
  test(
    'tool implementation, skill resources and budgets are real comparison categories',
    () {
      final candidate = package(
        'base\nnew',
        tools: ['rsi_calc'],
        budget: 12,
        files: {
          'tools/rsi/rsi_calc.json': '{"description":"exact","expression":1}',
          'skills/check/SKILL.md': 'Check facts.',
        },
      );
      final changes = collectRsiRoundDiffs(
        run([record(1, 'base-hash', 'new', true, candidate)]),
        [],
      ).single.changes;
      expect(
        changes.map((c) => c.kind),
        containsAll(['instructions', 'tools', 'skills', 'budgets']),
      );
      expect(changes.singleWhere((c) => c.name == 'rsi_calc').added, isTrue);
      final budget = changes.singleWhere((c) => c.name == 'max_steps');
      expect(budget.before, '8');
      expect(budget.after, '12');
    },
  );
  test(
    'line comparison preserves additions, removals and unchanged context',
    () {
      final diff = rsiLineDiff('keep\nold\nend', 'keep\nnew\nend');
      expect(diff.where((l) => l.kind == 'remove').map((l) => l.text), ['old']);
      expect(diff.where((l) => l.kind == 'add').map((l) => l.text), ['new']);
      final large = rsiLineDiff(
        List.filled(1000, 'old').join('\n'),
        List.filled(1000, 'new').join('\n'),
      );
      expect(large.where((l) => l.kind == 'add').length, 1000);
      expect(large.where((l) => l.kind == 'remove').length, 1000);
    },
  );
  for (final brightness in Brightness.values) {
    testWidgets('round changes open readable diff in ${brightness.name}', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1100, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: Scaffold(
            body: RsiRoundChanges(
              run: run([
                record(
                  1,
                  'base-hash',
                  'first',
                  true,
                  package(
                    'base\nnew guidance',
                    files: {
                      'skills/check/SKILL.md':
                          '# Verify\nVerify completed work.',
                    },
                  ),
                ),
              ]),
              events: const [],
              settings: const LiquidGlassSettings(),
              chinese: true,
            ),
          ),
        ),
      );
      await tester.tap(find.byKey(const ValueKey('rsi-round-diff-1')));
      await tester.pumpAndSettle();
      expect(find.text('第 1 轮改动 · 已采纳'), findsOneWidget);
      expect(find.text('基线 → R1'), findsOneWidget);
      expect(find.text('+ new guidance'), findsOneWidget);
      expect(
        tester.getTopLeft(find.byKey(const ValueKey('rsi-diff-content-0'))).dx,
        greaterThanOrEqualTo(
          tester
              .getBottomRight(find.byKey(const ValueKey('rsi-diff-files')))
              .dx,
        ),
      );
      await tester.tap(find.byKey(const ValueKey('rsi-diff-file-1')));
      await tester.pumpAndSettle();
      expect(find.text('+ # Verify'), findsOneWidget);
      expect(find.text('+ new guidance'), findsNothing);
      expect(find.text('新增'), findsOneWidget);
      tester.view.physicalSize = const Size(500, 900);
      await tester.pumpAndSettle();
      expect(find.text('+ # Verify'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
