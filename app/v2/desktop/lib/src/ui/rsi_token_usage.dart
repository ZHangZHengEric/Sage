import 'package:flutter/material.dart';

/// Whole-experiment totals; independent of the selected round or split.
class RsiTokenUsage extends StatelessWidget {
  const RsiTokenUsage({required this.usage, required this.chinese, super.key});
  final Map<String, Object?> usage;
  final bool chinese;
  String t(String zh, String en) => chinese ? zh : en;
  Map<String, Object?> map(Object? value) =>
      value is Map ? Map<String, Object?>.from(value) : const {};
  String count(Object? value) => value is num ? value.toInt().toString() : '—';
  String compact(Object? value) {
    if (value is! num) return '—';
    if (value >= 1000000) return '${(value / 1000000).toStringAsFixed(2)}M';
    if (value >= 1000) return '${(value / 1000).toStringAsFixed(1)}K';
    return value.toInt().toString();
  }

  String rate(Object? value) =>
      value is num ? '${(value * 100).toStringAsFixed(1)}%' : '—';

  @override
  Widget build(BuildContext context) {
    final total = map(usage['total']);
    final stages = map(usage['stages']);
    final theme = Theme.of(context);
    final labels = {
      'execution': t('执行', 'Execution'),
      'evaluation': t('评测', 'Evaluation'),
      'design': t('出题', 'Design'),
      'tuning': t('调优', 'Tuning'),
      'review': t('审查', 'Review'),
      'dialogue': t('用户模拟', 'User simulation'),
      if ((map(stages['other'])['total_tokens'] as num? ?? 0) > 0 ||
          (map(stages['other'])['unreported_records'] as num? ?? 0) > 0)
        'other': t('其他', 'Other'),
    };
    final records =
        (total['reported_records'] as num? ?? 0) +
        (total['unreported_records'] as num? ?? 0);
    Widget metric(String label, String text, String key) => Text(
      '$label $text',
      key: ValueKey(key),
      style: theme.textTheme.bodySmall?.copyWith(
        color: theme.colorScheme.onSurfaceVariant,
      ),
    );
    return Material(
      type: MaterialType.transparency,
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          key: const ValueKey('rsi-token-usage'),
          tilePadding: const EdgeInsets.symmetric(horizontal: 12),
          title: Wrap(
            spacing: 12,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                t('Token 用量', 'Token usage'),
                style: theme.textTheme.titleSmall,
              ),
              Text(
                records == 0
                    ? t('待回传', 'Awaiting usage')
                    : compact(total['total_tokens']),
                key: const ValueKey('rsi-token-total'),
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                usage['coverage'] == 'partial_legacy' ||
                        (total['unreported_records'] as num? ?? 0) > 0
                    ? t('已知用量 · 记录不完整', 'Known usage · incomplete records')
                    : t('本实验已回传累计', 'Reported experiment usage'),
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 16,
                  runSpacing: 4,
                  children: [
                    metric(
                      t('输入', 'Input'),
                      compact(total['input_tokens']),
                      'rsi-token-input',
                    ),
                    metric(
                      t('缓存命中', 'Cached'),
                      compact(total['cached_input_tokens']),
                      'rsi-token-cached',
                    ),
                    metric(
                      t('输出', 'Output'),
                      compact(total['output_tokens']),
                      'rsi-token-output',
                    ),
                    metric(
                      t('缓存率', 'Cache rate'),
                      rate(total['cache_rate']),
                      'rsi-token-cache-rate',
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 16,
                  runSpacing: 4,
                  children: [
                    for (final entry in labels.entries)
                      metric(
                        entry.value,
                        compact(map(stages[entry.key])['total_tokens']),
                        'rsi-token-stage-${entry.key}',
                      ),
                  ],
                ),
              ],
            ),
          ),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columnSpacing: 24,
                horizontalMargin: 0,
                columns: [
                  DataColumn(label: Text(t('阶段', 'Stage'))),
                  for (final label in [
                    t('输入', 'Input'),
                    t('缓存命中', 'Cached'),
                    t('输出', 'Output'),
                    t('合计', 'Total'),
                    t('缓存率', 'Cache rate'),
                  ])
                    DataColumn(label: Text(label), numeric: true),
                ],
                rows: [
                  for (final entry in {
                    ...labels,
                    'total': t('总计', 'All stages'),
                  }.entries)
                    DataRow(
                      cells: [
                        DataCell(
                          Text(
                            entry.value,
                            style: TextStyle(
                              fontWeight: entry.key == 'total'
                                  ? FontWeight.w600
                                  : FontWeight.normal,
                            ),
                          ),
                        ),
                        for (final field in [
                          'input_tokens',
                          'cached_input_tokens',
                          'output_tokens',
                          'total_tokens',
                          'cache_rate',
                        ])
                          DataCell(
                            Text(
                              field == 'cache_rate'
                                  ? rate(
                                      (entry.key == 'total'
                                          ? total
                                          : map(stages[entry.key]))[field],
                                    )
                                  : count(
                                      (entry.key == 'total'
                                          ? total
                                          : map(stages[entry.key]))[field],
                                    ),
                            ),
                          ),
                      ],
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Text(
              t(
                '输入已包含缓存命中；合计 = 输入 + 输出，缓存率 = 缓存命中 ÷ 输入。',
                'Input includes cached tokens. Total = input + output; cache rate = cached / input.',
              ),
              style: theme.textTheme.bodySmall,
            ),
            if ((total['unreported_records'] as num? ?? 0) > 0)
              Text(
                t(
                  '${total['unreported_records']} 条调用未回传用量，当前显示已知用量。',
                  '${total['unreported_records']} calls have no reported usage; showing known usage.',
                ),
                style: theme.textTheme.bodySmall,
              ),
            if (usage['coverage'] == 'partial_legacy')
              Text(
                t(
                  '历史实验按可用记录回补，可能缺少早期内部调用或测试用量。',
                  'Historical totals are reconstructed and may omit earlier internal or test calls.',
                ),
                style: theme.textTheme.bodySmall,
              ),
          ],
        ),
      ),
    );
  }
}
