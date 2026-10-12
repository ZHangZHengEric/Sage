import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import '../localization/app_localizations.dart';
import '../state/workspace_controller.dart';

class RsiScreen extends StatefulWidget {
  const RsiScreen({
    required this.controller,
    required this.agentId,
    required this.agentName,
    this.onBack,
    this.frameBuilder,
    this.fieldBuilder,
    this.historyOnly = false,
    super.key,
  });
  final WorkspaceController controller;
  final String agentId;
  final String agentName;
  final VoidCallback? onBack;
  final Widget Function(String, Widget, Widget)? frameBuilder;
  final Widget Function(String, Widget)? fieldBuilder;
  final bool historyOnly;
  @override
  State<RsiScreen> createState() => _RsiScreenState();
}

class _RsiScreenState extends State<RsiScreen> {
  final _goal = TextEditingController();
  final _rounds = TextEditingController(text: '3');
  final _cases = TextEditingController();
  final _parts = <String>{'instructions', 'skills'};
  Map<String, Object?> _history = {};
  Map<String, Object?>? _run;
  Map<String, Object?>? _version;
  String? _selectedRun,
      _versionFingerprint,
      _model,
      _requestId,
      _error,
      _requestOptions;
  String? _caseFilename;
  Timer? _poll;
  bool _loading = false, _mutating = false;
  bool _showConfiguration = true;
  int _revision = 0;
  final List<Map<String, Object?>> _events = [];
  String t(String zh, String en) =>
      context.l10n.locale.languageCode == 'zh' ? zh : en;
  Map<String, Object?> map(Object? v) =>
      v is Map ? v.cast<String, Object?>() : {};
  List<Map<String, Object?>> rows(Object? v) => v is List
      ? v.whereType<Map>().map((v) => v.cast<String, Object?>()).toList()
      : [];
  bool active(Object? v) => v == 'queued' || v == 'running';

  @override
  void initState() {
    super.initState();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    unawaited(_refresh());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _goal.dispose();
    _rounds.dispose();
    _cases.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_loading || !mounted) return;
    _loading = true;
    final revision = _revision;
    try {
      final history = await widget.controller.rsiHistory(widget.agentId);
      if (!mounted || revision != _revision) return;
      if (!widget.historyOnly) {
        _selectedRun ??= rows(history['runs']).firstOrNull?['id']?.toString();
      }
      final run = _selectedRun == null
          ? null
          : await widget.controller.rsiRun(
              widget.agentId,
              _selectedRun!,
              afterSequence: _events.isEmpty
                  ? 0
                  : (_events.last['sequence'] as num).toInt(),
            );
      if (!mounted || revision != _revision) return;
      setState(() {
        _history = history;
        _run = run;
        _events.addAll(rows(run?['events']));
      });
    } on Object catch (e) {
      if (mounted && revision == _revision) {
        setState(() => _error = e.toString());
      }
    } finally {
      _loading = false;
    }
  }

  Future<void> _mutate(Future<void> Function() action) async {
    if (_mutating) return;
    setState(() {
      _mutating = true;
      _error = null;
    });
    try {
      await action();
    } on Object catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) {
        setState(() => _mutating = false);
        await _refresh();
      }
    }
  }

  Future<void> _start() => _mutate(() async {
    final count = int.tryParse(_rounds.text);
    if (_goal.text.trim().isEmpty ||
        count == null ||
        count < 1 ||
        count > 100 ||
        _parts.isEmpty) {
      throw FormatException(
        t(
          '请输入目标、1–100 轮和优化范围',
          'Enter a goal, 1–100 rounds and optimization parts',
        ),
      );
    }
    final suite = _cases.text.trim().isEmpty ? null : jsonDecode(_cases.text);
    final options = jsonEncode([
      _goal.text.trim(),
      count,
      _parts.toList(),
      _model,
      suite,
    ]);
    if (_requestOptions != options) {
      _requestId = null;
      _requestOptions = options;
    }
    _requestId ??= 'desktop-${DateTime.now().microsecondsSinceEpoch}';
    await widget.controller.startRsi(widget.agentId, {
      'goal': _goal.text.trim(),
      'rounds': count,
      'optimization_scope': _parts.toList(),
      'model_provider_id': _model,
      'request_id': _requestId,
      'suite': ?suite,
    });
    _requestId = null;
    _requestOptions = null;
    _showConfiguration = false;
    _selectedRun = null;
    _events.clear();
    _version = null;
    _run = null;
    _revision++;
  });
  Future<void> _openVersion(Map<String, Object?> item) async {
    final revision = ++_revision;
    final expected = _history['current_fingerprint']?.toString();
    try {
      final value = await widget.controller.rsiVersion(
        widget.agentId,
        item['id'].toString(),
      );
      if (mounted && revision == _revision) {
        setState(() {
          _version = value;
          _versionFingerprint = expected;
          _error = null;
        });
      }
    } on Object catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _apply() async {
    final version = _version;
    final expected = _versionFingerprint;
    if (version == null || expected == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          t('确认替换 Agent 配置', 'Confirm Agent configuration replacement'),
        ),
        content: Text(
          '${widget.agentName}\n${versionLabel(version)}\n${version['created_at']}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(t('取消', 'Cancel')),
          ),
          FilledButton(
            key: const ValueKey('rsi-confirm-apply'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(t('确认替换', 'Confirm replacement')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await _mutate(() async {
      await widget.controller.applyRsiVersion(
        widget.agentId,
        version['id'].toString(),
        expected,
      );
      if (mounted) setState(() => _version = null);
    });
  }

  Future<void> _export(Object value, String filename) => _mutate(() async {
    final location = await getSaveLocation(suggestedName: filename);
    if (location != null) {
      await File(
        location.path,
      ).writeAsString(const JsonEncoder.withIndent('  ').convert(value));
    }
  });
  String versionLabel(Map<String, Object?> v) => v['source'] == 'rsi'
      ? '${t('迭代', 'Iteration')} ${v['iteration']}'
      : v['source'] == 'activation'
      ? t('已应用版本', 'Applied version')
      : t('配置保存', 'Configuration save');
  String status(Object? v) => switch (v) {
    'queued' => t('排队中', 'Queued'),
    'running' => t('优化中', 'Optimizing'),
    'completed' => t('已完成', 'Completed'),
    'failed' => t('失败', 'Failed'),
    'cancelled' => t('已取消', 'Cancelled'),
    'interrupted' => t('已中断', 'Interrupted'),
    _ => v?.toString() ?? '',
  };
  String stage(Object? v, {Object? role}) => switch (v) {
    'test_generation_started' ||
    'test_generation_completed' ||
    'suite_fixed' => t('生成测试集', 'Designing tests'),
    'final_test_generation_started' ||
    'final_suite_sealed' => t('准备最终测试集', 'Preparing final tests'),
    'suite_review_started' => t('审查测试集', 'Reviewing tests'),
    'suite_review_completed' => t('测试集审查完成', 'Tests reviewed'),
    'baseline_completed' => t('基线评测完成', 'Baseline evaluated'),
    'agent_call_started' || 'agent_call_completed' => switch (role) {
      'tuning' => t('调优 Agent', 'Tuning agent'),
      'evaluation' => t('评价 Agent', 'Evaluation agent'),
      'suite_review' => t('测试集审查 Agent', 'Test review agent'),
      'semantic_review' => t('语义审查 Agent', 'Review agent'),
      'test_design' => t('测试设计 Agent', 'Test designer'),
      'test_dialogue' => t('对话测试 Agent', 'Dialogue agent'),
      _ => t('内部 Agent 处理中', 'Internal agent working'),
    },
    'candidate_created' => t('生成候选版本', 'Candidate created'),
    'semantic_review_completed' => t('语义审查完成', 'Semantic review completed'),
    'round_completed' => t('本轮完成', 'Round completed'),
    'final_verification_completed' ||
    'final_evaluation_completed' => t('最终测试', 'Final tests'),
    'result_completed' || 'operation_finished' => t('结束', 'Finished'),
    'target_call_started' ||
    'target_call_completed' ||
    'case_completed' ||
    'evaluation_completed' => t('测试与评测', 'Testing and evaluating'),
    _ => t('内部 Agent 处理中', 'Internal agent working'),
  };
  Widget card(Widget child) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: GlassCard(
      settings: glass,
      child: Padding(padding: const EdgeInsets.all(16), child: child),
    ),
  );
  Widget heading(String title) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 10),
    child: Text(title, style: Theme.of(context).textTheme.titleMedium),
  );
  Widget text(String value) => SelectableText(value);
  LiquidGlassSettings get glass {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return LiquidGlassSettings(
      visibility: dark ? 0.86 : 0.9,
      glassColor: dark
          ? const Color(0xFF2B2C2E).withValues(alpha: 0.84)
          : Colors.white.withValues(alpha: 0.92),
      thickness: 4,
      blur: 0,
      chromaticAberration: 0,
      lightIntensity: 0.1,
      saturation: 1,
      glowIntensity: 0,
      standardOpacityMultiplier: dark ? 0.88 : 0.92,
      shadowElevation: 0.04,
    );
  }

  Widget action(
    String label,
    IconData icon,
    VoidCallback? onTap, {
    Key? key,
    double width = 112,
  }) => Semantics(
    key: key,
    button: true,
    enabled: onTap != null,
    label: label,
    onTap: onTap,
    excludeSemantics: true,
    child: IgnorePointer(
      ignoring: onTap == null,
      child: Opacity(
        opacity: onTap == null ? 0.45 : 1,
        child: GlassButton.custom(
          width: width,
          height: 34,
          settings: glass,
          shape: const LiquidRoundedRectangle(borderRadius: 10),
          onTap: onTap ?? () {},
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 15),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget field(String label, Widget control) =>
      widget.fieldBuilder?.call(label, control) ??
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: LayoutBuilder(
          builder: (context, constraints) => constraints.maxWidth < 560
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 8),
                    control,
                  ],
                )
              : Row(
                  children: [
                    SizedBox(
                      width: 150,
                      child: Text(
                        label,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerRight,
                        child: control,
                      ),
                    ),
                  ],
                ),
        ),
      );

  Future<void> importSuite() => _mutate(() async {
    final file = await openFile(
      acceptedTypeGroups: [
        const XTypeGroup(label: 'JSON', extensions: ['json']),
      ],
    );
    if (file == null) return;
    final value = jsonDecode(await file.readAsString());
    _cases.text = jsonEncode(value is List ? {'cases': value} : value);
    _caseFilename = file.name;
    _requestId = null;
  });

  Future<void> chooseModel() => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 360, maxHeight: 480),
        child: GlassCard(
          settings: glass,
          padding: const EdgeInsets.all(8),
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final option in <String, String>{
                '': t('目标 Agent 模型', 'Target agent model'),
                for (final model in widget.controller.modelProviders)
                  model.id: model.name,
              }.entries)
                ListTile(
                  title: Text(option.value),
                  selected: (_model ?? '') == option.key,
                  trailing: (_model ?? '') == option.key
                      ? const Icon(CupertinoIcons.checkmark, size: 16)
                      : null,
                  onTap: () {
                    setState(() {
                      _model = option.key.isEmpty ? null : option.key;
                      _requestId = null;
                    });
                    Navigator.pop(dialogContext);
                  },
                ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget form(bool busy) {
    final enabled = !busy && !_mutating;
    final modelLabel =
        widget.controller.modelProviders
            .where((m) => m.id == _model)
            .firstOrNull
            ?.name ??
        t('目标 Agent 模型', 'Target agent model');
    final fields = [
      field(
        t('优化目标', 'Optimization goal'),
        SizedBox(
          width: 600,
          child: GlassTextField(
            key: const ValueKey('rsi-goal'),
            controller: _goal,
            enabled: enabled,
            maxLines: 2,
            textStyle: Theme.of(context).textTheme.bodyMedium,
            settings: glass,
          ),
        ),
      ),
      field(
        t('优化轮数', 'Rounds'),
        SizedBox(
          width: 88,
          child: GlassTextField(
            key: const ValueKey('rsi-rounds'),
            controller: _rounds,
            enabled: enabled,
            textStyle: Theme.of(context).textTheme.bodyMedium,
            settings: glass,
          ),
        ),
      ),
      field(
        t('内部 Agent 模型', 'Internal agent model'),
        SizedBox(
          width: 260,
          child: GlassPicker(
            value: modelLabel,
            height: 34,
            width: 260,
            settings: glass,
            textStyle: Theme.of(context).textTheme.bodyMedium,
            onTap: enabled ? chooseModel : null,
          ),
        ),
      ),
      field(
        t('优化范围', 'Optimization parts'),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final part in {
              'instructions': t('指令', 'Instructions'),
              'skills': 'Skills',
              'tools': t('工具', 'Tools'),
              'budgets': t('步数预算', 'Step budget'),
            }.entries)
              Semantics(
                key: ValueKey('rsi-part-${part.key}'),
                button: true,
                selected: _parts.contains(part.key),
                enabled: enabled,
                label: part.value,
                child: IgnorePointer(
                  ignoring: !enabled,
                  child: Opacity(
                    opacity: enabled ? 1 : 0.45,
                    child: GlassButton.custom(
                      width: part.key == 'budgets'
                          ? 120
                          : part.key == 'instructions'
                          ? 124
                          : 88,
                      height: 34,
                      settings: glass,
                      shape: const LiquidRoundedRectangle(borderRadius: 10),
                      onTap: () => setState(() {
                        _parts.contains(part.key)
                            ? _parts.remove(part.key)
                            : _parts.add(part.key);
                        _requestId = null;
                      }),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            _parts.contains(part.key)
                                ? CupertinoIcons.checkmark_circle_fill
                                : CupertinoIcons.circle,
                            size: 15,
                            color: _parts.contains(part.key)
                                ? Theme.of(context).colorScheme.primary
                                : Theme.of(
                                    context,
                                  ).colorScheme.onSurfaceVariant,
                          ),
                          const SizedBox(width: 6),
                          Flexible(
                            child: Text(
                              part.value,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
      field(
        t('测试集', 'Test suite'),
        Wrap(
          spacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            if (_caseFilename != null)
              Text(
                _caseFilename!,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            action(
              t('导入测试集', 'Import suite'),
              CupertinoIcons.folder,
              enabled ? importSuite : null,
              key: const ValueKey('rsi-import-suite'),
              width: 126,
            ),
            if (_caseFilename != null)
              IconButton(
                tooltip: t('清除', 'Clear'),
                icon: const Icon(CupertinoIcons.xmark, size: 15),
                onPressed: !enabled
                    ? null
                    : () => setState(() {
                        _cases.clear();
                        _caseFilename = null;
                        _requestId = null;
                      }),
              ),
          ],
        ),
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < fields.length; i++) ...[
          fields[i],
          Divider(
            height: 1,
            color: Theme.of(context).colorScheme.outlineVariant,
          ),
        ],
      ],
    );
  }

  Widget historyList() {
    final runs = rows(_history['runs']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!widget.historyOnly) ...[
          if (runs.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 12),
              child: Text(
                t('暂无 RSI 记录', 'No RSI history'),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          for (final run in runs)
            ListTile(
              key: ValueKey('rsi-run-${run['id']}'),
              contentPadding: const EdgeInsets.symmetric(horizontal: 12),
              selected: _selectedRun == run['id'],
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(11),
              ),
              selectedTileColor: Theme.of(
                context,
              ).colorScheme.onSurface.withValues(alpha: 0.08),
              title: Text(
                run['goal'].toString(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              subtitle: Text(
                '${status(run['status'])} · ${run['iteration']}/${run['rounds']}\n${run['created_at']}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              trailing: active(run['status'])
                  ? const CupertinoActivityIndicator(radius: 7)
                  : null,
              onTap: () {
                setState(() {
                  _selectedRun = run['id'].toString();
                  _run = null;
                  _version = null;
                  _events.clear();
                  _revision++;
                });
                unawaited(_refresh());
              },
            ),
        ] else ...[
          for (final v in rows(
            _history['versions'],
          ).where((v) => v['source'] != 'rsi'))
            ListTile(
              key: ValueKey('rsi-version-${v['id']}'),
              contentPadding: const EdgeInsets.symmetric(horizontal: 12),
              selected: _version?['id'] == v['id'],
              selectedTileColor: Theme.of(
                context,
              ).colorScheme.onSurface.withValues(alpha: 0.08),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(11),
              ),
              title: Text(
                '${versionLabel(v)} · ${v['created_at']}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              trailing: map(v['review'])['approved'] == false
                  ? const Icon(CupertinoIcons.exclamationmark_circle, size: 16)
                  : null,
              onTap: () => _openVersion(v),
            ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final busy = rows(_history['runs']).any((r) => active(r['status']));
    final back =
        widget.onBack ??
        (Navigator.of(context).canPop() ? () => Navigator.pop(context) : null);
    final actions = Wrap(
      spacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (!widget.historyOnly) ...[
          action(
            t('运行设置', 'Run setup'),
            CupertinoIcons.slider_horizontal_3,
            () => setState(() => _showConfiguration = !_showConfiguration),
            key: const ValueKey('rsi-toggle-setup'),
            width: 124,
          ),
          action(
            t('开始 RSI', 'Start RSI'),
            CupertinoIcons.play_arrow_solid,
            busy || _mutating ? null : _start,
            key: const ValueKey('rsi-start'),
            width: 120,
          ),
        ],
        IconButton(
          tooltip: t('刷新', 'Refresh'),
          onPressed: _refresh,
          icon: const Icon(CupertinoIcons.refresh, size: 18),
        ),
        if (back != null)
          action(
            t('返回 Agent', 'Back to agent'),
            CupertinoIcons.chevron_left,
            back,
            key: const ValueKey('rsi-back-agent'),
            width: 132,
          ),
      ],
    );
    final body = LayoutBuilder(
      builder: (context, constraints) {
        final details = <Widget>[
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (_version != null)
            versionDetail()
          else if (!widget.historyOnly && _run != null)
            runDetail(),
        ];
        if (constraints.maxWidth < 860) {
          return ListView(
            children: [
              if (!widget.historyOnly && _showConfiguration) form(busy),
              const SizedBox(height: 22),
              historyList(),
              ...details,
            ],
          );
        }
        return Column(
          children: [
            if (!widget.historyOnly && _showConfiguration) form(busy),
            const SizedBox(height: 24),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 280,
                    child: ListView(children: [historyList()]),
                  ),
                  const SizedBox(width: 20),
                  VerticalDivider(
                    width: 1,
                    color: Theme.of(context).colorScheme.outlineVariant,
                  ),
                  const SizedBox(width: 20),
                  Expanded(child: ListView(children: details)),
                ],
              ),
            ),
          ],
        );
      },
    );
    final title =
        '${widget.historyOnly ? t('版本历史', 'Version history') : 'RSI'} · ${widget.agentName}';
    if (widget.frameBuilder != null) {
      return widget.frameBuilder!(
        title,
        actions,
        Material(type: MaterialType.transparency, child: body),
      );
    }
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 28, 24, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              LayoutBuilder(
                builder: (context, constraints) => constraints.maxWidth < 650
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: Theme.of(context).textTheme.headlineSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 12),
                          actions,
                        ],
                      )
                    : Row(
                        children: [
                          Expanded(
                            child: Text(
                              title,
                              style: Theme.of(context).textTheme.headlineSmall
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                          ),
                          actions,
                        ],
                      ),
              ),
              const SizedBox(height: 28),
              Expanded(child: body),
            ],
          ),
        ),
      ),
    );
  }

  Widget suiteReview(Map<String, Object?> value) => ExpansionTile(
    key: const ValueKey('rsi-suite-review'),
    tilePadding: EdgeInsets.zero,
    initiallyExpanded: value['approved'] == false,
    leading: Icon(
      value['approved'] == true
          ? CupertinoIcons.checkmark_shield
          : CupertinoIcons.exclamationmark_shield,
      size: 19,
      color: value['approved'] == true
          ? Theme.of(context).colorScheme.primary
          : Theme.of(context).colorScheme.error,
    ),
    title: Text(t('目标与测试集审查', 'Goal and test review')),
    trailing: Text(
      value['approved'] == true ? t('通过', 'Passed') : t('需修正', 'Needs changes'),
      style: Theme.of(context).textTheme.bodySmall?.copyWith(
        color: value['approved'] == true
            ? Theme.of(context).colorScheme.primary
            : Theme.of(context).colorScheme.error,
      ),
    ),
    children: [
      Align(
        alignment: Alignment.centerLeft,
        child: text(value['rationale']?.toString() ?? ''),
      ),
      for (final issue in rows(value['issues']))
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${issue['severity'] == 'blocking' ? t('阻断', 'Blocking') : t('建议', 'Advisory')} · ${(issue['case_ids'] as List? ?? []).join(', ')}',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              text(issue['rationale']?.toString() ?? ''),
              const SizedBox(height: 4),
              text(issue['suggested_fix']?.toString() ?? ''),
            ],
          ),
        ),
    ],
  );

  Widget runDetail() {
    final run = _run!;
    final result = map(run['result']);
    final iterations = result['iterations'] ?? run['iterations'];
    final suiteCheck = map(
      map(result['report'])['suite_review'] ?? run['suite_review'],
    );
    final report = map(result['report']);
    final finalCheck = map(report['final_verification']);
    return card(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                active(run['status'])
                    ? CupertinoIcons.arrow_2_circlepath
                    : run['status'] == 'completed'
                    ? CupertinoIcons.checkmark_circle
                    : CupertinoIcons.exclamationmark_circle,
                size: 20,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
              const SizedBox(width: 10),
              Expanded(child: heading(status(run['status']))),
              Text(
                '${run['iteration']} / ${run['rounds']}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              stage(run['stage'], role: run['role']),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
          if (active(run['status'])) ...[
            const LinearProgressIndicator(),
            TextButton(
              onPressed: _mutating
                  ? null
                  : () => _mutate(
                      () => widget.controller.cancelRsi(
                        widget.agentId,
                        run['id'].toString(),
                      ),
                    ),
              child: Text(t('取消优化', 'Cancel optimization')),
            ),
          ],
          if (suiteCheck.isNotEmpty) suiteReview(suiteCheck),
          if (run['error_type'] != null && suiteCheck['approved'] != false)
            Text('${t('运行错误', 'Run error')}: ${run['error_type']}'),
          for (final item in rows(iterations))
            ExpansionTile(
              title: Text(
                '${t('迭代', 'Iteration')} ${item['iteration']}${item['recommended'] == true ? t(' · 建议版本', ' · Recommended') : ''}',
              ),
              children: [
                text(item['reason']?.toString() ?? ''),
                if (item['review'] != null) review(map(item['review'])),
                evaluation(map(item['evaluation'])),
                TextButton(
                  key: ValueKey('rsi-open-iteration-${item['iteration']}'),
                  onPressed: () {
                    final v = rows(_history['versions'])
                        .where(
                          (v) =>
                              v['run_id'] == run['id'] &&
                              v['iteration'] == item['iteration'],
                        )
                        .firstOrNull;
                    if (v != null) unawaited(_openVersion(v));
                  },
                  child: Text(t('查看完整版本', 'View full version')),
                ),
              ],
            ),
          if (finalCheck.isNotEmpty)
            ExpansionTile(
              title: Text(
                '${t('独立最终测试', 'Independent final tests')} · ${finalCheck['passed'] == true ? t('通过', 'Passed') : t('未通过', 'Failed')}',
              ),
              children: [
                text(finalCheck['reason']?.toString() ?? ''),
                heading(t('原始版本', 'Original version')),
                evaluation(map(finalCheck['baseline'])),
                heading(t('候选版本', 'Candidate version')),
                evaluation(map(finalCheck['candidate'])),
              ],
            ),
          ExpansionTile(
            title: Text(t('过程记录', 'Process record')),
            children: [
              for (final event in _events)
                ListTile(
                  dense: true,
                  title: Text(
                    '${event['sequence']} · ${stage(event['event'], role: map(event['data'])['role'])} · ${event['time']}',
                  ),
                ),
            ],
          ),
          if (result.isNotEmpty)
            TextButton.icon(
              key: const ValueKey('rsi-export-report'),
              onPressed: () => _export(result, 'rsi-${run['id']}.json'),
              icon: const Icon(CupertinoIcons.square_arrow_down, size: 16),
              label: Text(t('导出完整记录', 'Export full record')),
            ),
        ],
      ),
    );
  }

  Widget review(Map<String, Object?> v) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      heading(
        '${t('语义审查', 'Semantic review')} · ${v['approved'] == true ? t('通过', 'Approved') : t('拒绝', 'Rejected')}',
      ),
      text(v['rationale']?.toString() ?? ''),
      for (final finding in (v['findings'] as List? ?? []))
        text(finding.toString()),
    ],
  );
  Widget evaluation(Map<String, Object?> v) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final test in rows(v['cases']))
        ExpansionTile(
          title: Text(
            '${map(test['case'])['id']} · ${map(test['grade'])['score']} · ${map(test['grade'])['passed'] == true ? t('通过', 'Passed') : t('失败', 'Failed')}',
          ),
          children: [
            heading(t('测试问题', 'Test question')),
            text(map(test['case'])['input']?.toString() ?? ''),
            heading(t('评测标准', 'Rubric')),
            text(map(test['case'])['rubric']?.toString() ?? ''),
            heading(t('回答', 'Response')),
            text(map(test['observation'])['output']?.toString() ?? ''),
            heading(t('评价结果', 'Evaluation')),
            text(map(test['grade'])['rationale']?.toString() ?? ''),
            if (rows(test['trials']).isEmpty) ...dialogue(test),
            for (final trial in rows(test['trials']).asMap().entries)
              ExpansionTile(
                title: Text(
                  '${t('测试次数', 'Trial')} ${trial.key + 1} · ${map(trial.value['grade'])['score']}',
                ),
                children: [
                  text(
                    map(trial.value['observation'])['output']?.toString() ?? '',
                  ),
                  text(
                    map(trial.value['grade'])['rationale']?.toString() ?? '',
                  ),
                  ...dialogue(trial.value),
                ],
              ),
          ],
        ),
    ],
  );
  List<Widget> dialogue(Map<String, Object?> trial) => [
    for (final turn in rows(trial['dialogue'])) ...[
      text('${t('对话轮次', 'Dialogue turn')} ${turn['turn']}'),
      text(turn['input']?.toString() ?? ''),
      text(map(turn['observation'])['output']?.toString() ?? ''),
      text(map(turn['grade'])['rationale']?.toString() ?? ''),
    ],
  ];
  Widget versionDetail() {
    final version = _version!;
    final package = map(version['package']);
    final definition = map(
      map(map(package['manifest'])['agents'])[widget.agentId],
    );
    final reviewed =
        version['ready'] != false &&
        (version['review'] == null ||
            map(version['review'])['approved'] == true);
    return card(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          heading(versionLabel(version)),
          savedConfiguration(version),
          if (version['review'] != null) review(map(version['review'])),
          if (version['source'] == 'rsi')
            text(
              map(version['final_test'])['tested'] == true
                  ? t(
                      '此版本已执行独立最终测试',
                      'This version received independent final tests',
                    )
                  : t(
                      '此版本未执行独立最终测试',
                      'This version has no independent final test result',
                    ),
            ),
          evaluation(map(map(version['record'])['evaluation'])),
          ExpansionTile(
            title: Text(t('指令', 'Instructions')),
            children: [
              text(map(definition['instructions'])['inline']?.toString() ?? ''),
            ],
          ),
          text(
            '${t('工具', 'Tools')}: ${(definition['tools'] as List? ?? []).join(', ')}',
          ),
          text('Skills: ${(definition['skills'] as List? ?? []).join(', ')}'),
          text(
            '${t('步数预算', 'Step budget')}: ${map(definition['budgets'])['max_steps']}',
          ),
          for (final file in map(package['files']).entries)
            ExpansionTile(
              title: Text(file.key),
              children: [text(file.value.toString())],
            ),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              TextButton.icon(
                key: const ValueKey('rsi-export-version'),
                onPressed: () =>
                    _export(version, 'agent-${version['id']}.json'),
                icon: const Icon(CupertinoIcons.square_arrow_down, size: 16),
                label: Text(t('导出完整版本', 'Export full version')),
              ),
              FilledButton(
                key: const ValueKey('rsi-apply-version'),
                onPressed: _mutating || !reviewed ? null : _apply,
                child: Text(t('使用此版本', 'Use this version')),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget savedConfiguration(Map<String, Object?> version) {
    final config = map(version['config']);
    final manifest = map(map(version['package'])['manifest']);
    final primary = map(map(manifest['models'])['primary']);
    final variables = map(
      config['runtimeVariables'] ??
          config['systemContext'] ??
          config['system_context'],
    );
    String modelLabel(Object? id) {
      final provider = widget.controller.modelProviders
          .where((p) => p.id == id)
          .firstOrNull;
      return provider == null
          ? t('默认', 'Default')
          : '${provider.name} · ${provider.model}';
    }

    return ExpansionTile(
      key: const ValueKey('rsi-saved-configuration'),
      title: Text(t('保存的配置', 'Saved configuration')),
      children: [
        field(t('名称', 'Name'), text(version['name']?.toString() ?? '')),
        if (config['description']?.toString().isNotEmpty == true)
          field(t('描述', 'Description'), text(config['description'].toString())),
        field(
          t('主模型', 'Primary model'),
          text(
            primary['model']?.toString() ??
                modelLabel(config['llm_provider_id']),
          ),
        ),
        field(
          t('快速模型', 'Fast model'),
          text(modelLabel(config['fast_llm_provider_id'])),
        ),
        field(
          t('模式', 'Mode'),
          text(config['agentMode']?.toString() ?? 'simple'),
        ),
        field(
          t('深度思考', 'Deep thinking'),
          text(config['deepThinking'] == true ? t('开启', 'On') : t('关闭', 'Off')),
        ),
        if (config['thinkingLevel'] != null)
          field(
            t('思考强度', 'Reasoning effort'),
            text(config['thinkingLevel'].toString()),
          ),
        field(
          t('运行变量', 'Runtime variables'),
          variables.isEmpty
              ? const Text('—')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final variable in variables.entries)
                      text('${variable.key}: ${variable.value}'),
                  ],
                ),
        ),
        field(
          t('Shell 授权', 'Shell approvals'),
          text((config['approvedShellCommands'] as List?)?.join('\n') ?? '—'),
        ),
      ],
    );
  }
}
