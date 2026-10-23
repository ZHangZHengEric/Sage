import 'package:flutter/material.dart';

class RsiDatasetBadge extends StatelessWidget {
  const RsiDatasetBadge({
    required this.label,
    this.icon,
    this.color,
    super.key,
  });
  final String label;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final foreground = color ?? Theme.of(context).colorScheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: foreground.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: foreground),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Text(
              label,
              style: TextStyle(fontSize: 12, color: foreground),
            ),
          ),
        ],
      ),
    );
  }
}

/// Human-facing import report. Never included in optimizer input.
class RsiDatasetSummary extends StatelessWidget {
  const RsiDatasetSummary({
    required this.report,
    required this.chinese,
    super.key,
  });
  final Map<String, Object?> report;
  final bool chinese;
  String t(String zh, String en) => chinese ? zh : en;
  Map<String, Object?> map(Object? value) =>
      value is Map ? Map<String, Object?>.from(value) : const {};
  List<Map<String, Object?>> rows(Object? value) => value is List
      ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
      : const [];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final dark = theme.brightness == Brightness.dark;
    final trainColor = dark ? const Color(0xFF61CFC2) : const Color(0xFF137D72);
    final devColor = dark ? const Color(0xFFB6A2F2) : const Color(0xFF7252B4);
    final testColor = dark ? const Color(0xFFE6C783) : const Color(0xFF936A18);
    final splits = map(report['split_counts']);
    final modes = map(report['mode_counts']);
    final dialogue = map(report['dialogue']);
    final environment = map(report['environment']);
    final checkRows = rows(report['checks']);
    final passed = checkRows.where((v) => v['status'] == 'passed').length;
    final pending = checkRows
        .where((v) => !{'passed', 'not_required'}.contains(v['status']))
        .length;
    final checkNames = {
      'protocol': t('数据协议', 'Protocol'),
      'required_fields': t('必填字段', 'Required fields'),
      'unique_case_ids': t('ID 唯一', 'Unique IDs'),
      'splits': t('分集', 'Splits'),
      'environment_binding': t('环境绑定', 'Environment'),
    };
    final splitInfo = [
      ('training', t('训练集', 'Training'), 'TRAIN', trainColor),
      ('validation', t('验证集', 'Validation'), 'DEV', devColor),
      ('test', t('测试集', 'Test'), 'TEST', testColor),
    ];
    final splitTotal = splitInfo.fold<num>(
      0,
      (sum, v) => sum + (splits[v.$1] as num? ?? 0),
    );
    final detailsStyle = theme.textTheme.bodySmall?.copyWith(
      color: colors.onSurfaceVariant,
      height: 1.6,
    );
    return Material(
      type: MaterialType.transparency,
      child: Column(
        key: const ValueKey('rsi-dataset-summary'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                t('数据集校验与总结', 'Dataset validation and summary'),
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              RsiDatasetBadge(
                label: pending > 0
                    ? t('$pending 项待检查', '$pending pending')
                    : t('校验通过', 'Validation passed'),
                icon: pending > 0
                    ? Icons.schedule_rounded
                    : Icons.check_circle_outline_rounded,
                color: pending > 0 ? testColor : trainColor,
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text('${report['name'] ?? ''}', style: detailsStyle),
          const SizedBox(height: 20),
          LayoutBuilder(
            builder: (context, constraints) {
              final width =
                  (constraints.maxWidth -
                      (constraints.maxWidth >= 620 ? 36 : 12)) /
                  (constraints.maxWidth >= 620 ? 4 : 2);
              Widget metric(
                String label,
                String caption,
                Object? value,
                Color color,
              ) => SizedBox(
                width: width,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: colors.onSurface.withValues(alpha: .035),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 6,
                            height: 6,
                            decoration: BoxDecoration(
                              color: color,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 7),
                          Flexible(child: Text(label, style: detailsStyle)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${value ?? 0}',
                        style: theme.textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: color,
                          height: 1.1,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        caption,
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: colors.onSurfaceVariant,
                          letterSpacing: .8,
                        ),
                      ),
                    ],
                  ),
                ),
              );
              return Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  metric(
                    t('参与题目', 'Active cases'),
                    t('题目总数', 'TOTAL CASES'),
                    report['case_count'],
                    colors.onSurface,
                  ),
                  for (final split in splitInfo)
                    metric(split.$2, split.$3, splits[split.$1], split.$4),
                ],
              );
            },
          ),
          if (splitTotal > 0) ...[
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: SizedBox(
                height: 4,
                child: Row(
                  children: [
                    for (final split in splitInfo)
                      if ((splits[split.$1] as num? ?? 0) > 0)
                        Expanded(
                          flex: (splits[split.$1] as num).toInt(),
                          child: ColoredBox(
                            color: split.$4,
                            child: const SizedBox.expand(),
                          ),
                        ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              RsiDatasetBadge(
                label:
                    '${t('单轮 / 多轮', 'Single turn / dialogue')}  ${modes['single_turn'] ?? 0} / ${modes['dialogue'] ?? 0}',
              ),
              if ((dialogue['count'] as num? ?? 0) > 0)
                RsiDatasetBadge(
                  label:
                      '${t('最多轮数', 'Turn limit')}  ${dialogue['min_turns'] == dialogue['max_turns'] ? dialogue['max_turns'] : '${dialogue['min_turns']}–${dialogue['max_turns']}'}',
                ),
              RsiDatasetBadge(
                label:
                    '${t('参考答案', 'References')}  ${report['reference_count'] ?? 0}',
              ),
              if (environment.isNotEmpty)
                RsiDatasetBadge(
                  icon: Icons.hub_outlined,
                  label:
                      '${(environment['mcp_servers'] as List? ?? []).join(', ')} · ${environment['tool_count'] ?? '—'} ${t('工具', 'tools')}',
                ),
            ],
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                t('校验结果', 'Checks'),
                style: theme.textTheme.labelMedium?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              for (final check in checkRows)
                RsiDatasetBadge(
                  label:
                      '${checkNames[check['name']] ?? check['name']}${check['status'] == 'not_required'
                          ? t(' · 无需绑定', ' · not required')
                          : check['status'] == 'passed'
                          ? ''
                          : t(' · 待检查', ' · pending')}',
                  icon: check['status'] == 'passed'
                      ? Icons.check_rounded
                      : check['status'] == 'not_required'
                      ? Icons.remove_rounded
                      : Icons.schedule_rounded,
                  color: check['status'] == 'passed'
                      ? trainColor
                      : check['status'] == 'not_required'
                      ? null
                      : testColor,
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            t(
              '$passed 项通过 · 评分器需单独自测',
              '$passed checks passed · Scorer self-test is separate',
            ),
            style: detailsStyle,
          ),
          if (pending > 0)
            Text(
              t(
                '尚未检查的环境将在启动前重新校验。',
                'Pending environment checks run again before start.',
              ),
              style: detailsStyle,
            ),
          for (final warning in rows(report['warnings']))
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: testColor.withValues(alpha: .08),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      t('待人工检查（非确定性错误）', 'Advisory for human review'),
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: testColor,
                      ),
                    ),
                    const SizedBox(height: 4),
                    SelectableText(
                      '${warning['message']}\n${(warning['case_ids'] as List? ?? []).join(', ')}',
                      style: detailsStyle,
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
          Theme(
            data: theme.copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 8),
              title: Text(
                t('覆盖标签与预审策略', 'Coverage and review policy'),
                style: theme.textTheme.bodyMedium,
              ),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final tag in rows(report['coverage_tags']))
                      RsiDatasetBadge(label: '${tag['tag']} · ${tag['count']}'),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  t(
                    '评分器需单独自测；数据校验通过不代表评分器已通过。',
                    'Dataset validation does not validate the scorer.',
                  ),
                  style: detailsStyle,
                ),
                Text(
                  t(
                    '语义预审仅提供诊断意见；导入的固定集仍按原题、原评分器评测。',
                    'Semantic review is advisory; imported fixed datasets keep their original cases and scorer.',
                  ),
                  style: detailsStyle,
                ),
              ],
            ),
          ),
          if (rows(report['examples']).isNotEmpty)
            Theme(
              data: theme.copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text(
                  t('题目示例（仅用户可见）', 'Examples (human only)'),
                  style: theme.textTheme.bodyMedium,
                ),
                children: [
                  for (final example in rows(report['examples']))
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text('${example['id']} · ${example['split']}'),
                      subtitle: SelectableText('${example['input']}'),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
