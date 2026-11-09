import 'package:flutter/material.dart';

typedef RsiRoundComparison = ({
  int round,
  int? opponent,
  bool? accepted,
  Map<String, Object?> results,
});

typedef RsiTestComparison = ({
  int checkpoint,
  int? version,
  int? expected,
  Map<String, Object?> results,
});

class RsiRoundComparisons extends StatelessWidget {
  const RsiRoundComparisons({
    required this.rounds,
    required this.tests,
    required this.finalTest,
    required this.recommendedRound,
    required this.chinese,
    this.finalVersusFirst,
    super.key,
  });

  final List<RsiRoundComparison> rounds;
  final List<RsiTestComparison> tests;
  final RsiTestComparison? finalTest;
  final int? recommendedRound;
  final bool chinese;
  final (int, int)? finalVersusFirst;

  String _t(String zh, String en) => chinese ? zh : en;
  String _version(int? round) => switch (round) {
    null => _t('保留版本', 'Retained version'),
    0 => _t('原始基线', 'Original baseline'),
    _ => _t('第 $round 轮', 'Round $round'),
  };

  @override
  Widget build(BuildContext context) {
    if (rounds.isEmpty && tests.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    final dark = theme.brightness == Brightness.dark;
    final colors = [
      dark ? const Color(0xFF64E8DD) : const Color(0xFF00746C),
      dark ? const Color(0xFFB6AD97) : const Color(0xFF766744),
      dark ? const Color(0xFFFF8895) : const Color(0xFFAD263E),
    ];

    List<int> countsFor(Map<String, Object?> result) => [
      for (final key in ['wins', 'ties', 'losses'])
        (result[key] as num?)?.toInt() ?? 0,
    ];
    int totalFor(List<int> counts) =>
        counts.fold(0, (sum, count) => sum + count);

    String outcome(Map<String, Object?> result, {int? expected}) {
      final counts = countsFor(result);
      final total = totalFor(counts);
      final bothFailed = (result['both_failed'] as num?)?.toInt() ?? 0;
      final missing = (result['missing'] as num?)?.toInt() ?? 0;
      if (total == 0 && bothFailed == 0 && missing == 0) {
        return _t('暂无判定', 'Awaiting judgments');
      }
      return [
        _t(
          '${counts[0]} 胜 · ${counts[1]} 平 · ${counts[2]} 负',
          '${counts[0]} W · ${counts[1]} T · ${counts[2]} L',
        ),
        if (bothFailed > 0) _t('$bothFailed 双失败', '$bothFailed both failed'),
        if (missing > 0) _t('$missing 缺失', '$missing missing'),
        if (expected != null) '$total/$expected',
      ].join('  ·  ');
    }

    final maxCount = rounds.fold(1, (largest, round) {
      final count = totalFor(countsFor(round.results));
      return count > largest ? count : largest;
    });

    Widget stack(List<int> counts, int scale, Key key, {double height = 76}) {
      final total = totalFor(counts);
      return SizedBox(
        height: height,
        child: Align(
          alignment: Alignment.bottomCenter,
          child: total == 0
              ? Container(
                  width: 22,
                  height: 2,
                  color: theme.colorScheme.outlineVariant,
                )
              : ClipRRect(
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(3),
                  ),
                  child: SizedBox(
                    width: 22,
                    height: height * total / scale,
                    child: Column(
                      key: key,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      verticalDirection: VerticalDirection.up,
                      children: [
                        for (final (i, count) in counts.indexed)
                          if (count > 0)
                            Expanded(
                              flex: count,
                              child: ColoredBox(color: colors[i]),
                            ),
                      ],
                    ),
                  ),
                ),
        ),
      );
    }

    Widget roundColumn(RsiRoundComparison item, double width) {
      final counts = countsFor(item.results);
      final recommended =
          item.accepted == true && item.round == recommendedRound;
      final decision = recommended
          ? _t('推荐', 'Pick')
          : switch (item.accepted) {
              true => _t('采纳', 'Accept'),
              false => _t('保留', 'Keep'),
              null => '—',
            };
      final opponent = switch (item.opponent) {
        null => '—',
        0 => _t('基线', 'Base'),
        final int round => 'R$round',
      };
      return Tooltip(
        key: ValueKey('rsi-comparison-round-${item.round}'),
        message:
            '${_version(item.round)} vs ${_version(item.opponent)} · $decision\n${outcome(item.results)}',
        child: SizedBox(
          width: width,
          child: Column(
            children: [
              stack(
                counts,
                maxCount,
                ValueKey('rsi-comparison-stack-${item.round}'),
              ),
              const SizedBox(height: 4),
              Text('R${item.round}', style: theme.textTheme.labelMedium),
              Text(
                'vs $opponent',
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
              Text(
                decision,
                style: theme.textTheme.labelSmall?.copyWith(
                  color: item.accepted == true ? colors.first : muted,
                  fontWeight: recommended ? FontWeight.w700 : null,
                ),
              ),
            ],
          ),
        ),
      );
    }

    final roundsByNumber = {for (final round in rounds) round.round: round};
    final testsByCheckpoint = {for (final test in tests) test.checkpoint: test};
    final checkpoints = {
      ...roundsByNumber.keys,
      ...testsByCheckpoint.keys,
    }.toList()..sort();
    final testScale = tests.fold(1, (largest, test) {
      final total = totalFor(countsFor(test.results));
      final expected = test.expected ?? 0;
      return [largest, total, expected].reduce((a, b) => a > b ? a : b);
    });

    const testChartHeight = 64.0;
    final points = [
      for (final checkpoint in checkpoints)
        if (testsByCheckpoint[checkpoint] case final test?)
          (
            counts: countsFor(test.results),
            partial:
                test.results['complete'] == false ||
                ((test.results['errors'] as num?) ?? 0) > 0 ||
                (test.expected != null &&
                    totalFor(countsFor(test.results)) < test.expected!),
          )
        else
          null,
    ];

    Widget checkpointColumn(int checkpoint, double width) {
      final test = testsByCheckpoint[checkpoint];
      final counts = countsFor(test?.results ?? {});
      final total = totalFor(counts);
      final version = switch (test?.version) {
        null => '—',
        0 => _t('基线', 'Base'),
        final int round => 'R$round',
      };
      return Tooltip(
        key: ValueKey('rsi-test-checkpoint-$checkpoint'),
        message: test == null
            ? _t('R$checkpoint · 暂无测试', 'R$checkpoint · No test')
            : '${_t('R$checkpoint 检查点', 'R$checkpoint checkpoint')} · ${test.version == null ? _t('受测版本未知', 'Unknown version') : _version(test.version)} vs ${_version(0)}\n${outcome(test.results, expected: test.expected)}',
        child: SizedBox(
          width: width,
          child: Column(
            children: [
              SizedBox(
                key: ValueKey('rsi-test-checkpoint-slot-$checkpoint'),
                width: double.infinity,
                height: testChartHeight,
              ),
              const SizedBox(height: 3),
              if (rounds.isEmpty)
                Text('R$checkpoint', style: theme.textTheme.labelMedium),
              Text(
                version == '—' ? version : _t('测 $version', version),
                style: theme.textTheme.labelSmall,
              ),
              Text(
                test == null
                    ? '—'
                    : test.expected == null
                    ? '$total'
                    : '$total/${test.expected}',
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
            ],
          ),
        ),
      );
    }

    Widget finalColumn(RsiTestComparison test) {
      final counts = countsFor(test.results);
      final total = totalFor(counts);
      final expected =
          test.expected ?? (test.results['pairs'] as num?)?.toInt();
      final scale = expected != null && expected > total ? expected : total;
      final version = test.version == null ? '—' : 'R${test.version}';
      return Tooltip(
        key: const ValueKey('rsi-final-test-column'),
        message:
            '${_t('最终验收 · 测试集', 'Final verification · Test')}\n'
            '${_version(test.version)} vs ${_version(0)}\n'
            '${outcome(test.results, expected: expected)}',
        child: SizedBox(
          width: 62,
          child: Column(
            children: [
              stack(counts, scale, const ValueKey('rsi-final-test-stack')),
              const SizedBox(height: 4),
              Text(
                _t('最终 Test', 'Final Test'),
                style: theme.textTheme.labelMedium,
              ),
              Text(
                '$version vs ${_t('基线', 'Base')}',
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
              Text(
                expected == null ? '$total' : '$total/$expected',
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
            ],
          ),
        ),
      );
    }

    Widget testResult(RsiTestComparison test) => Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${_t('R${test.checkpoint} 检查点 · ', 'R${test.checkpoint} checkpoint · ')}${test.version == null ? _t('受测版本未知', 'Unknown version') : _version(test.version)} vs ${_version(0)}',
          style: theme.textTheme.labelMedium,
        ),
        const SizedBox(height: 5),
        Text(
          outcome(test.results, expected: test.expected),
          style: theme.textTheme.labelSmall?.copyWith(color: muted),
        ),
      ],
    );

    return Column(
      key: const ValueKey('rsi-round-comparisons'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (checkpoints.isNotEmpty || finalTest != null) ...[
          Wrap(
            spacing: 10,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (rounds.isNotEmpty)
                Text(
                  _t('逐轮采纳 · 验证集', 'Round decisions · Dev'),
                  style: theme.textTheme.titleSmall,
                ),
              for (final (i, label) in [
                _t('胜', 'Win'),
                _t('平', 'Tie'),
                _t('负', 'Loss'),
              ].indexed)
                Text(
                  label,
                  style: theme.textTheme.labelSmall?.copyWith(color: colors[i]),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (checkpoints.isNotEmpty)
                Expanded(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final width = (constraints.maxWidth / checkpoints.length)
                          .clamp(45.0, 68.0);
                      return SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (rounds.isNotEmpty)
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  for (final checkpoint in checkpoints)
                                    if (roundsByNumber[checkpoint]
                                        case final round?)
                                      roundColumn(round, width)
                                    else
                                      SizedBox(
                                        width: width,
                                        child: Column(
                                          children: [
                                            stack(
                                              const [],
                                              1,
                                              ValueKey(
                                                'rsi-missing-dev-$checkpoint',
                                              ),
                                            ),
                                            const SizedBox(height: 4),
                                            Text(
                                              'R$checkpoint',
                                              style:
                                                  theme.textTheme.labelMedium,
                                            ),
                                          ],
                                        ),
                                      ),
                                ],
                              ),
                            if (tests.isNotEmpty) ...[
                              if (rounds.isNotEmpty) const SizedBox(height: 8),
                              Text(
                                _t(
                                  '逐轮 Test · 对原始基线',
                                  'Checkpoint Test · vs baseline',
                                ),
                                style: theme.textTheme.labelMedium,
                              ),
                              const SizedBox(height: 4),
                              Stack(
                                children: [
                                  Positioned(
                                    left: 0,
                                    right: 0,
                                    top: 0,
                                    height: testChartHeight,
                                    child: IgnorePointer(
                                      child: CustomPaint(
                                        key: const ValueKey(
                                          'rsi-test-checkpoint-trend',
                                        ),
                                        painter: _TestCheckpointLines(
                                          points: points,
                                          colors: colors,
                                          scale: testScale,
                                          grid:
                                              theme.colorScheme.outlineVariant,
                                          surface: theme.colorScheme.surface,
                                          labelColor: muted,
                                          direction: Directionality.of(context),
                                        ),
                                      ),
                                    ),
                                  ),
                                  Row(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      for (final checkpoint in checkpoints)
                                        checkpointColumn(checkpoint, width),
                                    ],
                                  ),
                                ],
                              ),
                            ],
                          ],
                        ),
                      );
                    },
                  ),
                ),
              if (finalTest case final test?) ...[
                if (checkpoints.isNotEmpty)
                  SizedBox(
                    height: 112,
                    child: VerticalDivider(
                      width: 12,
                      color: theme.colorScheme.outlineVariant,
                    ),
                  ),
                finalColumn(test),
              ],
            ],
          ),
        ],
        if (finalTest != null)
          if (finalVersusFirst case (final retained, final first))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                _t(
                  '${_version(retained)} vs ${_version(first)} · Test 未直接比较',
                  '${_version(retained)} vs ${_version(first)} · No direct Test comparison',
                ),
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
            ),
        if (tests.isNotEmpty)
          ExpansionTile(
            key: const ValueKey('rsi-test-comparison-history'),
            tilePadding: EdgeInsets.zero,
            minTileHeight: 34,
            title: Text(
              _t('测试历史', 'Test history'),
              style: theme.textTheme.labelMedium,
            ),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final test in tests)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: testResult(test),
                ),
            ],
          ),
      ],
    );
  }
}

class _TestCheckpointLines extends CustomPainter {
  const _TestCheckpointLines({
    required this.points,
    required this.colors,
    required this.scale,
    required this.grid,
    required this.surface,
    required this.labelColor,
    required this.direction,
  });

  final List<({List<int> counts, bool partial})?> points;
  final List<Color> colors;
  final int scale;
  final Color grid, surface, labelColor;
  final TextDirection direction;

  @override
  void paint(Canvas canvas, Size size) {
    final top = 7.0;
    final bottom = size.height - 7;
    for (final (value, y) in [(scale, top), (0, bottom)]) {
      canvas.drawLine(
        Offset(17, y),
        Offset(size.width, y),
        Paint()..color = grid.withValues(alpha: .4),
      );
      final label = TextPainter(
        text: TextSpan(
          text: '$value',
          style: TextStyle(color: labelColor, fontSize: 9),
        ),
        textDirection: direction,
      )..layout();
      label.paint(canvas, Offset(0, y - label.height / 2));
      label.dispose();
    }
    for (final (series, color) in colors.indexed) {
      Offset? previous;
      final line = Paint()
        ..color = color
        ..strokeWidth = 1.5;
      final markers = <(Offset, bool)>[];
      for (final (index, sample) in points.indexed) {
        if (sample == null || sample.counts.every((count) => count == 0)) {
          previous = null;
          continue;
        }
        final point = Offset(
          size.width * (index + .5) / points.length,
          bottom - (bottom - top) * sample.counts[series] / scale,
        );
        if (previous != null) canvas.drawLine(previous, point, line);
        markers.add((point, sample.partial));
        previous = point;
      }
      for (final (point, partial) in markers) {
        canvas.drawCircle(point, 3, Paint()..color = partial ? surface : color);
        if (partial) {
          canvas.drawCircle(
            point,
            3,
            Paint()
              ..color = color
              ..style = PaintingStyle.stroke
              ..strokeWidth = 1.4,
          );
        }
      }
    }
  }

  @override
  bool shouldRepaint(covariant _TestCheckpointLines oldDelegate) =>
      oldDelegate.points != points ||
      oldDelegate.colors != colors ||
      oldDelegate.scale != scale ||
      oldDelegate.grid != grid ||
      oldDelegate.surface != surface ||
      oldDelegate.labelColor != labelColor ||
      oldDelegate.direction != direction;
}
