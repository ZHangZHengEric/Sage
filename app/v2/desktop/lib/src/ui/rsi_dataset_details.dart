import 'dart:convert';
import 'package:flutter/material.dart';
import 'rsi_dataset_summary.dart';

/// Read-only human view of one immutable dataset version.
class RsiDatasetDetailsDialog extends StatefulWidget {
  const RsiDatasetDetailsDialog({
    required this.version,
    required this.chinese,
    super.key,
  });
  final Map<String, Object?> version;
  final bool chinese;
  @override
  State<RsiDatasetDetailsDialog> createState() => _DetailsState();
}

class _DetailsState extends State<RsiDatasetDetailsDialog> {
  String _query = '';
  String _split = 'all';
  String t(String zh, String en) => widget.chinese ? zh : en;
  Map<String, Object?> map(Object? value) =>
      value is Map ? Map<String, Object?>.from(value) : const {};
  List<Map<String, Object?>> rows(Object? value) => value is List
      ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
      : const [];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dataset = map(widget.version['dataset']);
    final manifest = map(widget.version['manifest']);
    final marks = rows(manifest['exclusions']);
    final removed = marks.map((v) => v['case_id']).toSet();
    final allCases = rows(dataset['cases']);
    final cases = allCases
        .where(
          (v) =>
              (_split == 'all' || v['split'] == _split) &&
              '${v['id']} ${v['input']}'.toLowerCase().contains(
                _query.toLowerCase(),
              ),
        )
        .toList();
    final secondary = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return Dialog(
      key: const ValueKey('rsi-dataset-details-dialog'),
      insetPadding: const EdgeInsets.all(20),
      clipBehavior: Clip.antiAlias,
      child: SizedBox(
        width: 960,
        height: 820,
        child: DefaultTabController(
          length: 3,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 18, 12, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            t('数据集详情', 'Dataset details'),
                            style: theme.textTheme.titleLarge,
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${dataset['name'] ?? manifest['name'] ?? ''}',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: secondary,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      key: const ValueKey('rsi-dataset-details-close'),
                      tooltip: t('关闭', 'Close'),
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
              ),
              TabBar(
                tabs: [
                  Tab(text: t('概览', 'Overview')),
                  Tab(text: '${t('题目', 'Cases')} (${allCases.length})'),
                  Tab(text: '${t('排除记录', 'Exclusions')} (${marks.length})'),
                ],
              ),
              Expanded(
                child: TabBarView(
                  children: [
                    SingleChildScrollView(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (map(widget.version['validation']).isNotEmpty)
                            RsiDatasetSummary(
                              report: map(widget.version['validation']),
                              chinese: widget.chinese,
                            ),
                          const SizedBox(height: 16),
                          const Divider(),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              RsiDatasetBadge(
                                label: manifest['label'] == 'revised'
                                    ? t('修订集', 'Revised dataset')
                                    : t('原始集', 'Original dataset'),
                                icon: Icons.lock_outline_rounded,
                              ),
                              RsiDatasetBadge(
                                label:
                                    '${t('原始 / 排除 / 参与', 'Original / excluded / active')}  ${manifest['original_count']} / ${manifest['excluded_count']} / ${manifest['active_count']}',
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Text(
                            '${t('完整原始 test 题数', 'Complete-source test count')}: ${map(map(manifest['counts'])['test'])['original'] ?? 0}',
                            style: secondary,
                          ),
                          if (manifest['label'] == 'revised')
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                t(
                                  '修订集成绩不代表完整官方集成绩。原实验口径保持不变。',
                                  'Revised-set scores do not represent the complete official benchmark. Existing runs keep their frozen scope.',
                                ),
                                style: secondary,
                              ),
                            ),
                          const SizedBox(height: 12),
                          SelectableText(
                            '${t('版本', 'Version')}: ${widget.version['id']}',
                            style: secondary,
                          ),
                          if (manifest['parent_version'] != null)
                            SelectableText(
                              '${t('父版本', 'Parent')}: ${manifest['parent_version']}',
                              style: secondary,
                            ),
                        ],
                      ),
                    ),
                    Column(
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            children: [
                              TextField(
                                key: const ValueKey('rsi-dataset-case-search'),
                                decoration: InputDecoration(
                                  prefixIcon: const Icon(Icons.search_rounded),
                                  hintText: t(
                                    '搜索题目 ID 或内容',
                                    'Search case ID or content',
                                  ),
                                  border: const OutlineInputBorder(),
                                ),
                                onChanged: (v) => setState(() => _query = v),
                              ),
                              const SizedBox(height: 12),
                              Wrap(
                                spacing: 8,
                                runSpacing: 4,
                                children: [
                                  for (final split in [
                                    'all',
                                    'training',
                                    'validation',
                                    'test',
                                  ])
                                    ChoiceChip(
                                      label: Text(
                                        split == 'all'
                                            ? t('全部', 'All')
                                            : {
                                                'training': 'train',
                                                'validation': 'dev',
                                                'test': 'test',
                                              }[split]!,
                                      ),
                                      selected: _split == split,
                                      onSelected: (_) =>
                                          setState(() => _split = split),
                                    ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: cases.isEmpty
                              ? Center(
                                  child: Text(
                                    t('没有匹配的题目', 'No matching cases'),
                                  ),
                                )
                              : ListView.builder(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 16,
                                  ),
                                  itemCount: cases.length,
                                  itemBuilder: (context, index) {
                                    final item = cases[index];
                                    return ExpansionTile(
                                      key: ValueKey(
                                        'dataset-case-${item['id']}',
                                      ),
                                      title: Text('${item['id']}'),
                                      subtitle: Text(
                                        '${item['split']} · ${removed.contains(item['id']) ? t('已排除', 'Excluded') : t('参与评测', 'Active')}',
                                        style: secondary,
                                      ),
                                      expandedCrossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      childrenPadding:
                                          const EdgeInsets.fromLTRB(
                                            16,
                                            0,
                                            16,
                                            16,
                                          ),
                                      children: [
                                        for (final field in [
                                          ('input', t('题目', 'Input')),
                                          ('rubric', t('评分规则', 'Rubric')),
                                          (
                                            'user_context',
                                            t('用户上下文', 'User context'),
                                          ),
                                          (
                                            'environment_context',
                                            t('环境上下文', 'Environment context'),
                                          ),
                                          (
                                            'reference_answer',
                                            t('参考答案', 'Reference answer'),
                                          ),
                                        ])
                                          if (item[field.$1] != null &&
                                              item[field.$1]
                                                  .toString()
                                                  .isNotEmpty) ...[
                                            const SizedBox(height: 12),
                                            Text(
                                              field.$2,
                                              style: theme.textTheme.labelLarge,
                                            ),
                                            const SizedBox(height: 4),
                                            SelectableText(
                                              item[field.$1] is String
                                                  ? item[field.$1] as String
                                                  : const JsonEncoder.withIndent(
                                                      '  ',
                                                    ).convert(item[field.$1]),
                                            ),
                                          ],
                                      ],
                                    );
                                  },
                                ),
                        ),
                      ],
                    ),
                    marks.isEmpty
                        ? Center(
                            child: Text(
                              t('此版本没有排除题目', 'No exclusions in this version'),
                            ),
                          )
                        : ListView(
                            padding: const EdgeInsets.all(24),
                            children: [
                              for (final mark in marks)
                                ExpansionTile(
                                  title: Text(
                                    '${mark['case_id']} · ${mark['reason']}',
                                  ),
                                  subtitle: Text(
                                    '${mark['operator']} · ${mark['confirmed_at']}',
                                  ),
                                  expandedCrossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    SelectableText(
                                      '${(mark['evidence'] as List? ?? []).join('\n')}\n${t('来源版本', 'Source version')}: ${mark['source_version']}',
                                    ),
                                  ],
                                ),
                            ],
                          ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
