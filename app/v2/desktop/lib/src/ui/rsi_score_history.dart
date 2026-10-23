import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

Map<String, Object?> _map(Object? value) =>
    value is Map ? value.cast<String, Object?>() : {};
List<Map<String, Object?>> _rows(Object? value) => value is List
    ? value.whereType<Map>().map((r) => r.cast<String, Object?>()).toList()
    : [];

/// Human-only checkpoint snapshots. Missing measurements stay missing.
class RsiScoreHistory extends StatefulWidget {
  const RsiScoreHistory({
    super.key,
    required this.records,
    required this.settings,
    required this.chinese,
    this.round,
  });
  final List<Map<String, Object?>> records;
  final LiquidGlassSettings settings;
  final bool chinese;

  /// When supplied, the observatory owns round selection.
  final int? round;
  @override
  State<RsiScoreHistory> createState() => _RsiScoreHistoryState();
}

class _RsiScoreHistoryState extends State<RsiScoreHistory> {
  int? selectedRound;
  String tr(String zh, String en) => widget.chinese ? zh : en;
  @override
  Widget build(BuildContext context) {
    final records = [...widget.records]
      ..sort((a, b) => (a['round'] as num).compareTo(b['round'] as num));
    if (records.isEmpty) return const SizedBox.shrink();
    final requestedRound = widget.round ?? selectedRound;
    final matching = records
        .where((r) => r['round'] == requestedRound)
        .firstOrNull;
    if (widget.round != null && matching == null) {
      return const SizedBox.shrink();
    }
    final selected = matching ?? records.last;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final colors = [
      dark ? const Color(0xFF55D5EB) : const Color(0xFF007C91),
      dark ? const Color(0xFFBFA0FF) : const Color(0xFF7440C0),
      dark ? const Color(0xFFFFCB75) : const Color(0xFF986000),
    ];
    final splits = ['training', 'validation', 'test'];
    final names = [
      tr('训练 train', 'Train'),
      tr('验证 dev', 'Dev'),
      tr('测试 test', 'Test'),
    ];
    String score(Map<String, Object?> r, String split) {
      final n = _map(r['scores'])[split];
      return (split == 'test' && r['valid'] == false) || n is! num
          ? '—'
          : n.toStringAsFixed(3);
    }

    return GlassCard(
      key: const ValueKey('rsi-three-split-history'),
      settings: widget.settings,
      padding: const EdgeInsets.all(18),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 24,
            runSpacing: 10,
            children: [
              for (var i = 0; i < splits.length; i++)
                Text(
                  '${names[i]}  ${score(selected, splits[i])}',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: colors[i],
                    fontWeight: FontWeight.w600,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),
          if (widget.round == null)
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final record in records)
                  ChoiceChip(
                    key: ValueKey('rsi-score-round-${record['round']}'),
                    label: Text(
                      record['round'] == 0
                          ? tr('基线', 'Baseline')
                          : '${tr('第', 'Round ')}${record['round']}${tr('轮', '')}',
                    ),
                    selected: record['round'] == selected['round'],
                    onSelected: (_) => setState(
                      () => selectedRound = (record['round'] as num).toInt(),
                    ),
                  ),
              ],
            ),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              Widget matrix(int index) {
                final split = splits[index];
                final rows = split == 'test'
                    ? _rows(selected['cases'])
                    : _rows(
                        selected['development_cases'],
                      ).where((r) => r['split'] == split).toList();
                final valid = split != 'test' || selected['valid'] != false;
                final graded = rows
                    .where((r) => valid && r['score'] is num)
                    .length;
                return Padding(
                  padding: const EdgeInsets.only(right: 12, bottom: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${names[index]}  $graded / ${rows.length}',
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final (i, row) in rows.indexed)
                            Builder(
                              builder: (context) {
                                final value = valid
                                    ? (row['score'] as num?)?.toDouble()
                                    : null;
                                final status = !valid
                                    ? tr('集合重叠，结果无效', 'Split overlap: invalid')
                                    : switch (row['status']) {
                                        'error' => tr(
                                          '测量错误',
                                          'Measurement error',
                                        ),
                                        'cancelled' => tr('已取消', 'Cancelled'),
                                        'running' => tr('评测中', 'Evaluating'),
                                        _ => tr('未评估', 'Not evaluated'),
                                      };
                                final label =
                                    '${names[index]} ${i + 1} · ${value?.toStringAsFixed(3) ?? status}';
                                final color = value == null
                                    ? (dark
                                          ? const Color(0xFF35434D)
                                          : const Color(0xFFD3DBDF))
                                    : Color.lerp(
                                        dark
                                            ? const Color(0xFFB94355)
                                            : const Color(0xFFB72136),
                                        dark
                                            ? const Color(0xFF61E3B1)
                                            : const Color(0xFF188554),
                                        value.clamp(0, 1),
                                      )!;
                                return Semantics(
                                  label: label,
                                  child: Tooltip(
                                    message: label,
                                    child: AnimatedContainer(
                                      key: ValueKey(
                                        'rsi-history-dot-${selected['round']}-$split-${row['id']}',
                                      ),
                                      duration:
                                          MediaQuery.disableAnimationsOf(
                                            context,
                                          )
                                          ? Duration.zero
                                          : const Duration(milliseconds: 220),
                                      width: 14,
                                      height: 14,
                                      decoration: BoxDecoration(
                                        color: color,
                                        shape: BoxShape.circle,
                                        border: row['status'] == 'running'
                                            ? Border.all(
                                                color: colors[index],
                                                width: 2,
                                              )
                                            : null,
                                      ),
                                    ),
                                  ),
                                );
                              },
                            ),
                        ],
                      ),
                    ],
                  ),
                );
              }

              return constraints.maxWidth < 680
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [for (var i = 0; i < 3; i++) matrix(i)],
                    )
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (var i = 0; i < 3; i++) Expanded(child: matrix(i)),
                      ],
                    );
            },
          ),
        ],
      ),
    );
  }
}

/// One linear scale shared by every series, with evenly spaced score ticks.
class RsiScoreScale {
  const RsiScoreScale(this.minimum, this.maximum, this.step);
  final double minimum, maximum, step;

  factory RsiScoreScale.fromRecords(List<Map<String, Object?>> records) {
    final values = <double>[
      for (final record in records)
        for (final split in ['training', 'validation', 'test'])
          if (!(split == 'test' && record['valid'] == false))
            if (_map(record['scores'])[split] case final num value)
              if (value.isFinite) value.clamp(0, 1).toDouble(),
    ];
    if (values.isEmpty) return const RsiScoreScale(0, 1, .25);
    final low = values.reduce(math.min);
    final high = values.reduce(math.max);
    final padding = math.max(.02, (high - low) * .12);
    final lower = math.max(0.0, low - padding);
    final upper = math.min(1.0, high + padding);
    final targetStep = (upper - lower) / 4;
    final magnitude = math
        .pow(10, (math.log(targetStep) / math.ln10).floor())
        .toDouble();
    final fraction = targetStep / magnitude;
    final step =
        (fraction <= 1
            ? 1
            : fraction <= 2
            ? 2
            : fraction <= 5
            ? 5
            : 10) *
        magnitude;
    return RsiScoreScale(
      ((lower / step + 1e-9).floor() * step).clamp(0, 1).toDouble(),
      ((upper / step - 1e-9).ceil() * step).clamp(0, 1).toDouble(),
      step,
    );
  }

  List<double> get ticks => [
    for (var i = 0; i <= ((maximum - minimum) / step).round(); i++)
      minimum + i * step,
  ];
  double fraction(num value) =>
      (value.clamp(minimum, maximum) - minimum) / (maximum - minimum);
  String label(double value) =>
      value.toStringAsFixed(3).replaceFirst(RegExp(r'\.?0+$'), '');
}

/// Compact overview of measured scores; absent or invalid test scores stay absent.
class RsiScoreTrend extends StatelessWidget {
  const RsiScoreTrend({
    super.key,
    required this.records,
    required this.chinese,
  });
  final List<Map<String, Object?>> records;
  final bool chinese;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    final colors = [
      dark ? const Color(0xFF55D5EB) : const Color(0xFF007C91),
      dark ? const Color(0xFFBFA0FF) : const Color(0xFF7440C0),
      dark ? const Color(0xFFFFCB75) : const Color(0xFF986000),
    ];
    final points = [...records]
      ..sort((a, b) => (a['round'] as num).compareTo(b['round'] as num));
    final scale = RsiScoreScale.fromRecords(points);
    final ticks = scale.ticks.reversed.toList();
    final splits = ['training', 'validation', 'test'];
    final names = chinese
        ? ['训练集', '验证集', '测试集']
        : ['Training', 'Validation', 'Test'];
    String score(Map<String, Object?> record, String split) {
      final value = _map(record['scores'])[split];
      return value is num &&
              value.isFinite &&
              !(split == 'test' && record['valid'] == false)
          ? value.toStringAsFixed(3)
          : '—';
    }

    String round(Object? value) => value == 0
        ? (chinese ? '基线' : 'Baseline')
        : (chinese ? '第 $value 轮' : 'Round $value');
    return Semantics(
      key: const ValueKey('rsi-score-trend'),
      label: points
          .map(
            (p) =>
                '${round(p['round'])}: ${splits.indexed.map((s) => '${names[s.$1]} ${score(p, s.$2)}').join(', ')}',
          )
          .join('; '),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Wrap(
            spacing: 16,
            runSpacing: 6,
            children: [
              for (final (index, split) in splits.indexed)
                Text(
                  '${names[index]} ${points.isEmpty ? '—' : score(points.last, split)}',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: colors[index],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              SizedBox(
                width: 42,
                height: 110,
                child: Stack(
                  children: [
                    for (final (index, tick) in ticks.indexed)
                      Positioned(
                        top: 1 + 94 * index / (ticks.length - 1),
                        right: 5,
                        height: 14,
                        child: Text(
                          scale.label(tick),
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
              Expanded(
                child: SizedBox(
                  height: 110,
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      double x(int index) {
                        final first = (points.first['round'] as num).toDouble();
                        final last = (points.last['round'] as num).toDouble();
                        return 8 +
                            math.max(0, constraints.maxWidth - 16) *
                                (first == last
                                    ? .5
                                    : ((points[index]['round'] as num) -
                                              first) /
                                          (last - first));
                      }

                      String details(Map<String, Object?> point) => [
                        round(point['round']),
                        for (final (index, split) in splits.indexed)
                          '${names[index]}：${split == 'test' && point['valid'] == false
                              ? (chinese ? '结果无效' : 'Invalid result')
                              : score(point, split) == '—'
                              ? (chinese ? '未评估' : 'Not evaluated')
                              : score(point, split)}',
                      ].join('\n');
                      return Stack(
                        fit: StackFit.expand,
                        children: [
                          CustomPaint(
                            painter: _ScoreLines(
                              points,
                              colors,
                              theme.colorScheme.onSurface.withValues(
                                alpha: .12,
                              ),
                              scale: scale,
                            ),
                          ),
                          for (var i = 0; i < points.length; i++)
                            Positioned(
                              left: i == 0 ? 0 : (x(i - 1) + x(i)) / 2,
                              right: i == points.length - 1
                                  ? 0
                                  : constraints.maxWidth -
                                        (x(i) + x(i + 1)) / 2,
                              top: 0,
                              bottom: 0,
                              child: Tooltip(
                                key: ValueKey(
                                  'rsi-trend-column-${points[i]['round']}',
                                ),
                                message: details(points[i]),
                                waitDuration: const Duration(milliseconds: 150),
                                excludeFromSemantics: true,
                                child: const SizedBox.expand(),
                              ),
                            ),
                        ],
                      );
                    },
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.only(left: 50, right: 8),
            child: Row(
              mainAxisAlignment: points.length > 1
                  ? MainAxisAlignment.spaceBetween
                  : MainAxisAlignment.center,
              children: [
                if (points.isNotEmpty)
                  Text(
                    'R${points.first['round']}',
                    style: theme.textTheme.labelSmall,
                  ),
                if (points.length > 1)
                  Text(
                    'R${points.last['round']}',
                    style: theme.textTheme.labelSmall,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ScoreLines extends CustomPainter {
  _ScoreLines(
    this.records,
    this.colors,
    this.grid, {
    this.scale = const RsiScoreScale(0, 1, .25),
  });
  final List<Map<String, Object?>> records;
  final List<Color> colors;
  final Color grid;
  final RsiScoreScale scale;
  @override
  void paint(Canvas canvas, Size size) {
    const pad = 8.0;
    final area = Rect.fromLTWH(
      pad,
      pad,
      size.width - 2 * pad,
      size.height - 2 * pad,
    );
    for (final tick in scale.ticks) {
      final y = area.bottom - area.height * scale.fraction(tick);
      canvas.drawLine(
        Offset(area.left, y),
        Offset(area.right, y),
        Paint()..color = grid,
      );
    }
    if (records.isEmpty) return;
    final minRound = (records.first['round'] as num).toDouble();
    final maxRound = (records.last['round'] as num).toDouble();
    for (final (i, split) in ['training', 'validation', 'test'].indexed) {
      Offset? previous;
      for (final record in records) {
        final score = _map(record['scores'])[split];
        if (score is! num ||
            !score.isFinite ||
            (split == 'test' && record['valid'] == false)) {
          previous = null;
          continue;
        }
        final point = Offset(
          area.left +
              area.width *
                  (maxRound == minRound
                      ? .5
                      : ((record['round'] as num) - minRound) /
                            (maxRound - minRound)),
          area.bottom - area.height * scale.fraction(score),
        );
        if (previous != null) {
          canvas.drawLine(
            previous,
            point,
            Paint()
              ..color = colors[i]
              ..strokeWidth = 2,
          );
        }
        canvas.drawCircle(point, 3.5, Paint()..color = colors[i]);
        previous = point;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ScoreLines oldDelegate) => true;
}
