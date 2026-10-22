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
  });
  final List<Map<String, Object?>> records;
  final LiquidGlassSettings settings;
  final bool chinese;
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
    final selected =
        records.where((r) => r['round'] == selectedRound).firstOrNull ??
        records.last;
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
          Semantics(
            label: records
                .map(
                  (r) =>
                      '${tr('轮次', 'Round')} ${r['round']}: ${splits.map((s) => '$s ${score(r, s)}').join(', ')}',
                )
                .join('; '),
            child: Row(
              children: [
                SizedBox(
                  width: 28,
                  height: 150,
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      for (final label in ['1', '0.5', '0'])
                        Text(
                          label,
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                    ],
                  ),
                ),
                Expanded(
                  child: SizedBox(
                    height: 150,
                    child: CustomPaint(
                      painter: _ScoreLines(
                        records,
                        colors,
                        Theme.of(
                          context,
                        ).colorScheme.onSurface.withValues(alpha: .12),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
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

class _ScoreLines extends CustomPainter {
  _ScoreLines(this.records, this.colors, this.grid);
  final List<Map<String, Object?>> records;
  final List<Color> colors;
  final Color grid;
  @override
  void paint(Canvas canvas, Size size) {
    const pad = 8.0;
    final area = Rect.fromLTWH(
      pad,
      pad,
      size.width - 2 * pad,
      size.height - 2 * pad,
    );
    for (final fraction in [0.0, .25, .5, .75, 1.0]) {
      final y = area.bottom - area.height * fraction;
      canvas.drawLine(
        Offset(area.left, y),
        Offset(area.right, y),
        Paint()..color = grid,
      );
    }
    final maxRound = (records.last['round'] as num).toDouble();
    for (final (i, split) in ['training', 'validation', 'test'].indexed) {
      Offset? previous;
      for (final record in records) {
        final score = _map(record['scores'])[split];
        if (score is! num || (split == 'test' && record['valid'] == false)) {
          previous = null;
          continue;
        }
        final point = Offset(
          area.left +
              area.width *
                  (maxRound == 0 ? .5 : (record['round'] as num) / maxRound),
          area.bottom - area.height * score.clamp(0, 1),
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
