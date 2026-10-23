import 'dart:convert';
import 'package:flutter/material.dart';

/// Human confirmation only. This dialog returns a proposal, never changes a run.
class RsiDatasetRevisionDialog extends StatefulWidget {
  const RsiDatasetRevisionDialog({
    required this.version,
    required this.chinese,
    this.issue = const {},
    super.key,
  });
  final Map<String, Object?> version;
  final Map<String, Object?> issue;
  final bool chinese;
  @override
  State<RsiDatasetRevisionDialog> createState() => _RevisionState();
}

class _RevisionState extends State<RsiDatasetRevisionDialog> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _caseId;
  late final TextEditingController _reason;
  late final TextEditingController _evidence;
  bool _confirmed = false;
  String _code = 'invalid_fixture';
  String t(String zh, String en) => widget.chinese ? zh : en;
  Map<String, Object?> map(Object? value) =>
      value is Map ? value.cast<String, Object?>() : {};
  List<Map<String, Object?>> get cases =>
      (map(widget.version['dataset'])['cases'] as List? ?? [])
          .whereType<Map>()
          .map((value) => value.cast<String, Object?>())
          .toList();
  Map<String, Object?> get selected =>
      cases.where((item) => item['id'] == _caseId.text.trim()).firstOrNull ??
      {};
  @override
  void initState() {
    super.initState();
    final ids = widget.issue['case_ids'] as List? ?? [];
    _caseId = TextEditingController(text: ids.firstOrNull?.toString() ?? '');
    _reason = TextEditingController();
    _evidence = TextEditingController(
      text: (widget.issue['evidence'] as List? ?? []).join('\n'),
    );
  }

  @override
  void dispose() {
    _caseId.dispose();
    _reason.dispose();
    _evidence.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final manifest = map(widget.version['manifest']);
    final excluded = (manifest['exclusions'] as List? ?? [])
        .whereType<Map>()
        .map((value) => value['case_id'])
        .toSet();
    return AlertDialog(
      title: Text(t('审核题目并创建修订集', 'Review case and create revised dataset')),
      content: SizedBox(
        width: 660,
        child: SingleChildScrollView(
          child: Form(
            key: _form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  t(
                    '模型意见不是已确认的数据错误。低分、失败、波动和暂时不会解，都不是排除依据。',
                    'A model opinion is not a confirmed data error. Low scores, failures, variance and model inability do not justify exclusion.',
                  ),
                ),
                const SizedBox(height: 12),
                SelectableText(
                  '${t('来源版本', 'Source version')}: ${manifest['source_version']}',
                ),
                Text(
                  '${t('原始 / 已排除 / 参与', 'Original / excluded / active')}: ${manifest['original_count']} / ${manifest['excluded_count']} / ${manifest['active_count']}',
                ),
                if (widget.issue.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    '${t('疑似问题', 'Suspected issue')}: ${widget.issue['rationale'] ?? ''}',
                  ),
                  Text(
                    '${t('影响', 'Impact')}: ${widget.issue['impact'] ?? widget.issue['suggested_fix'] ?? ''}',
                  ),
                ],
                TextFormField(
                  key: const ValueKey('dataset-revision-case'),
                  controller: _caseId,
                  decoration: InputDecoration(
                    labelText: t('Case ID', 'Case ID'),
                  ),
                  onChanged: (_) => setState(() {}),
                  validator: (value) =>
                      selected.isEmpty || excluded.contains(value?.trim())
                      ? t(
                          '请输入当前版本中尚未排除的 case ID',
                          'Enter an existing, active case ID',
                        )
                      : null,
                ),
                if (selected.isNotEmpty)
                  ExpansionTile(
                    title: Text(t('原始题目与评分要求', 'Original case and rubric')),
                    children: [
                      SelectableText(
                        const JsonEncoder.withIndent('  ').convert(selected),
                      ),
                    ],
                  ),
                DropdownButtonFormField<String>(
                  initialValue: _code,
                  items: [
                    for (final entry in <String, String>{
                      'missing_information': t(
                        '缺少必要信息',
                        'Missing required information',
                      ),
                      'invalid_fixture': t('环境或题目配置错误', 'Invalid fixture'),
                      'invalid_reference': t('参考或评分配置错误', 'Invalid reference'),
                      'policy_conflict': t('明确政策矛盾', 'Policy contradiction'),
                      'protocol_error': t('协议错误', 'Protocol error'),
                    }.entries)
                      DropdownMenuItem(
                        value: entry.key,
                        child: Text(entry.value),
                      ),
                  ],
                  onChanged: (value) => setState(() => _code = value!),
                  decoration: InputDecoration(
                    labelText: t('人工确认的问题类型', 'Human-confirmed defect type'),
                  ),
                ),
                TextFormField(
                  key: const ValueKey('dataset-revision-reason'),
                  controller: _reason,
                  minLines: 2,
                  maxLines: 4,
                  decoration: InputDecoration(
                    labelText: t(
                      '排除原因（由你确认）',
                      'Reason for exclusion (your assessment)',
                    ),
                  ),
                  validator: (value) => value?.trim().isNotEmpty == true
                      ? null
                      : t('请填写具体原因', 'Enter a concrete reason'),
                ),
                TextFormField(
                  key: const ValueKey('dataset-revision-evidence'),
                  controller: _evidence,
                  minLines: 3,
                  maxLines: 6,
                  decoration: InputDecoration(
                    labelText: t(
                      '具体证据（原文字段、政策条款或配置证据）',
                      'Evidence (case fields, policy clauses or configuration)',
                    ),
                  ),
                  validator: (value) => value?.trim().isNotEmpty == true
                      ? null
                      : t('请提供证据', 'Provide evidence'),
                ),
                const SizedBox(height: 12),
                Text(
                  t(
                    '确认后仅创建新版本并标注“修订集”。原始数据和当前实验不变；需要用新版本开启新实验。完整原始 test 的目标仍按原始题数计算。',
                    'Confirmation creates a new version labeled revised. Original data and the current run remain unchanged. Start a new run to use it. Complete-source test targets retain the original denominator.',
                  ),
                ),
                Text(
                  '${t('排除后参与题数', 'Active cases after exclusion')}: ${(manifest['active_count'] as num? ?? cases.length) - 1}',
                ),
                CheckboxListTile(
                  key: const ValueKey('dataset-revision-confirm'),
                  contentPadding: EdgeInsets.zero,
                  value: _confirmed,
                  title: Text(
                    t(
                      '我已核对证据，确认这是数据问题，并同意创建修订集',
                      'I reviewed the evidence, confirm a data defect, and approve a revised dataset',
                    ),
                  ),
                  onChanged: (value) =>
                      setState(() => _confirmed = value == true),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(t('取消', 'Cancel')),
        ),
        FilledButton(
          key: const ValueKey('dataset-revision-submit'),
          onPressed: !_confirmed
              ? null
              : () {
                  if (!_form.currentState!.validate()) return;
                  Navigator.pop(context, <String, Object?>{
                    'expected_version': widget.version['id'],
                    'confirmed': true,
                    'exclusions': [
                      {
                        'case_id': _caseId.text.trim(),
                        'reason_code': _code,
                        'reason': _reason.text.trim(),
                        'evidence': _evidence.text
                            .split('\n')
                            .map((line) => line.trim())
                            .where((line) => line.isNotEmpty)
                            .toList(),
                      },
                    ],
                  });
                },
          child: Text(t('确认排除并创建新版本', 'Confirm exclusion and create version')),
        ),
      ],
    );
  }
}
