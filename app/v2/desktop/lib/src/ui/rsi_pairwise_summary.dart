import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

Map<String, Object?> _map(Object? value) =>
    value is Map ? value.cast<String, Object?>() : {};

bool isRsiPairwiseGrade(Map<String, Object?> grade) {
  final details = _map(grade['scorer_details']);
  return details.containsKey('pairwise') ||
      details.containsKey('pairwise_summary');
}

Map<String, int> rsiPairwiseCounts(Map<String, Object?> grade) {
  final details = _map(grade['scorer_details']);
  final summary = _map(details['pairwise_summary']);
  final outcome = _map(details['pairwise'])['outcome'];
  return {
    for (final entry in {
      'wins': 'win',
      'ties': 'tie',
      'losses': 'loss',
    }.entries)
      entry.key:
          (summary[entry.key] as num?)?.toInt() ??
          (outcome == entry.value ? 1 : 0),
  };
}

String rsiPairwiseLabel(Map<String, Object?> grade, bool chinese) {
  final pair = _map(_map(grade['scorer_details'])['pairwise']);
  if (pair['reference'] == true) return chinese ? '基线' : 'Baseline';
  final counts = rsiPairwiseCounts(grade);
  final n = counts.values.fold<int>(0, (a, b) => a + b);
  if (n == 0) return chinese ? '待比较' : 'Awaiting comparison';
  if (n == 1) {
    return counts['wins'] == 1
        ? (chinese ? '胜' : 'Win')
        : counts['ties'] == 1
        ? (chinese ? '平' : 'Tie')
        : (chinese ? '负' : 'Loss');
  }
  return chinese
      ? "胜 ${counts['wins']} / 平 ${counts['ties']} / 负 ${counts['losses']}"
      : "Wins ${counts['wins']} / Ties ${counts['ties']} / Losses ${counts['losses']}";
}

class RsiPairwiseSummary extends StatelessWidget {
  const RsiPairwiseSummary({
    super.key,
    this.grades = const [],
    this.summary,
    this.label,
    required this.settings,
    required this.chinese,
    this.expectedPairs,
    this.errors = 0,
    this.embedded = false,
  });
  final List<Map<String, Object?>> grades;
  final Map<String, Object?>? summary;
  final String? label;
  final LiquidGlassSettings settings;
  final bool chinese;
  final int? expectedPairs;
  final int errors;
  final bool embedded;

  @override
  Widget build(BuildContext context) {
    final records = grades
        .map((g) => _map(_map(g['scorer_details'])['pairwise']))
        .where((g) => g.isNotEmpty)
        .toList();
    if (records.isEmpty && (summary == null || summary!.isEmpty)) {
      return const SizedBox.shrink();
    }
    String tr(String zh, String en) => chinese ? zh : en;
    final wins =
        (summary?['wins'] as num?)?.toInt() ??
        records.where((g) => g['outcome'] == 'win').length;
    final ties =
        (summary?['ties'] as num?)?.toInt() ??
        records.where((g) => g['outcome'] == 'tie').length;
    final losses =
        (summary?['losses'] as num?)?.toInt() ??
        records.where((g) => g['outcome'] == 'loss').length;
    final count = wins + ties + losses;
    final reference =
        records.isNotEmpty && records.every((g) => g['reference'] == true);
    final complete = errors == 0 && count == (expectedPairs ?? count);
    String percent(double value) => '${(100 * value).toStringAsFixed(1)}%';
    if (embedded) {
      final theme = Theme.of(context);
      final dark = theme.brightness == Brightness.dark;
      final muted = theme.colorScheme.onSurfaceVariant;
      Widget metric(String name, String value, Color color) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            style: theme.textTheme.titleLarge?.copyWith(
              color: color,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 3),
          Text(name, style: theme.textTheme.labelSmall?.copyWith(color: muted)),
        ],
      );
      return Padding(
        key: const ValueKey('rsi-pairwise-summary'),
        padding: const EdgeInsets.only(bottom: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (label != null) ...[
              Text(
                label!,
                style: theme.textTheme.labelMedium?.copyWith(color: muted),
              ),
              const SizedBox(height: 10),
            ],
            Wrap(
              spacing: 24,
              runSpacing: 10,
              children: [
                metric(
                  tr('胜', 'Wins'),
                  '$wins',
                  dark ? const Color(0xFF64E8DD) : const Color(0xFF006C68),
                ),
                metric(tr('平', 'Ties'), '$ties', muted),
                metric(
                  tr('负', 'Losses'),
                  '$losses',
                  dark ? const Color(0xFFFF8895) : const Color(0xFFAD263E),
                ),
                metric(
                  tr('胜率', 'Win rate'),
                  complete && count > 0 ? percent(wins / count) : '—',
                  theme.colorScheme.onSurface,
                ),
              ],
            ),
            if (!complete || errors > 0) ...[
              const SizedBox(height: 8),
              Text(
                '${tr('已配对', 'Pairs')} $count / ${expectedPairs ?? count}${errors > 0 ? " · ${tr('测量错误', 'Measurement errors')} $errors" : ""}',
                style: theme.textTheme.labelSmall?.copyWith(color: muted),
              ),
            ],
          ],
        ),
      );
    }
    return GlassCard(
      key: const ValueKey('rsi-pairwise-summary'),
      settings: settings,
      padding: const EdgeInsets.all(16),
      child: Wrap(
        spacing: 20,
        runSpacing: 8,
        children: [
          if (label != null) Text(label!),
          if (reference)
            Text(tr('基线', 'Baseline'))
          else ...[
            Text(
              '${tr('胜 / 平 / 负', 'Win / Tie / Loss')}  $wins / $ties / $losses',
            ),
            Text(
              '${tr('胜率', 'Win rate')}  ${complete && count > 0 ? percent(wins / count) : '—'}',
            ),
            Text('${tr('已配对', 'Pairs')}  $count / ${expectedPairs ?? count}'),
            if (errors > 0)
              Text('${tr('测量错误', 'Measurement errors')}  $errors'),
          ],
        ],
      ),
    );
  }
}
