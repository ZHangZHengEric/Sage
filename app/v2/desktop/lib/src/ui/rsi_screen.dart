import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import '../localization/app_localizations.dart';
import 'rsi_observatory.dart';
import 'rsi_dataset_revision.dart';
import 'rsi_dataset_details.dart';
import 'rsi_activity.dart';
import 'rsi_diff.dart';
import 'rsi_pairwise_summary.dart';
import 'rsi_scorer_guide.dart';
import 'rsi_save_agent_dialog.dart';
import '../state/workspace_controller.dart';
import '../services/scorer_import.dart';

class RsiScreen extends StatefulWidget {
  const RsiScreen({
    required this.controller,
    required this.agentId,
    required this.agentName,
    this.onBack,
    this.frameBuilder,
    this.fieldBuilder,
    this.historyOnly = false,
    this.onOpenFolder,
    super.key,
  });
  final WorkspaceController controller;
  final String agentId;
  final String agentName;
  final VoidCallback? onBack;
  final Widget Function(String, Widget, Widget)? frameBuilder;
  final Widget Function(String, Widget)? fieldBuilder;
  final bool historyOnly;
  final Future<void> Function(String path)? onOpenFolder;
  @override
  State<RsiScreen> createState() => _RsiScreenState();
}

class _RsiScreenState extends State<RsiScreen> {
  final _goal = TextEditingController();
  final _userSimulatorInstructions = TextEditingController();
  final _rounds = TextEditingController(text: '5');
  final _initialTrainingCount = TextEditingController(text: '6');
  final _trainingIncrement = TextEditingController(text: '6');
  final _systemPromptLimit = TextEditingController(text: '64000');
  final _skillLengthLimit = TextEditingController(text: '32000');
  final _skillCountLimit = TextEditingController(text: '5');
  final _editRepairLimit = TextEditingController(text: '3');
  final _testCount = TextEditingController(text: '24');
  final _humanTestCount = TextEditingController(text: '12');
  final _concurrency = TextEditingController(text: '8');
  final _evaluationRepeats = TextEditingController(text: '2');
  final _humanTestRepeats = TextEditingController(text: '2');
  final _cases = TextEditingController();
  final _parts = <String>{'instructions', 'skills'};
  Map<String, Object?> _history = {};
  Map<String, Object?>? _datasetVersion;
  bool _configurationRestored = false;
  bool _configurationEdited = false;
  bool _restoringConfiguration = false;
  Map<String, Object?>? _run;
  Map<String, Object?>? _version;
  String? _selectedVersionId;
  bool _versionLoading = false;
  String? _selectedRun, _model, _requestId, _error, _requestOptions;
  String? _caseFilename;
  String? _scorerId;
  String? _userSimulatorId;
  String _builtinScoring = 'quality';

  String builtinScorerName(String mode) => switch (mode) {
    'pairwise' => t('配对比较', 'Pairwise comparison'),
    'quality_cost' => t('质量与成本', 'Quality & cost'),
    'quality_latency' => t('质量与耗时', 'Quality & time'),
    'quality_tokens' => t('质量与 Token 用量', 'Quality & tokens'),
    _ => t('质量', 'Quality'),
  };
  Timer? _poll;
  int? _loadingRevision;
  bool _mutating = false;
  bool _confirmingCancellation = false;
  bool _showConfiguration = false;
  bool _showRunHistory = false;
  bool _versionMode = false;
  bool get _versions => widget.historyOnly || _versionMode;
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

  bool get _canResumeTests {
    final run = _run;
    if (run == null ||
        run['status'] != 'completed' ||
        run['external_host'] == true ||
        ((run['human_test_count'] as num?) ?? 0) == 0 &&
            rows(map(run['human_test_suite'])['cases']).isEmpty) {
      return false;
    }
    final checkpoints = rows(run['test_observations']);
    if (checkpoints.any(
          (record) => record['valid'] == false || record['status'] == 'invalid',
        ) ||
        checkpoints.any(
          (record) => rows(record['cases']).any(
            (item) => rows(item['trials']).any(
              (trial) =>
                  trial['status'] != 'completed' &&
                  trial['grade'] != null &&
                  run['human_test_phase_recovery'] != true,
            ),
          ),
        )) {
      return false;
    }
    final expected = <int>{
      0,
      ...rows(run['iterations'])
          .map((record) => record['iteration'])
          .whereType<num>()
          .map((number) => number.toInt()),
    };
    final measured = checkpoints
        .map((record) => record['round'])
        .whereType<num>()
        .map((number) => number.toInt())
        .toSet();
    return !measured.containsAll(expected) ||
        checkpoints.any(
          (record) =>
              {'queued', 'running', 'cancelled'}.contains(record['status']),
        ) ||
        checkpoints.any(
          (record) => rows(record['cases']).any(
            (item) => rows(item['trials']).any(
              (trial) =>
                  trial['status'] != 'completed' &&
                  (trial['grade'] == null ||
                      run['human_test_phase_recovery'] == true),
            ),
          ),
        );
  }

  @override
  void initState() {
    super.initState();
    for (final controller in _configurationFields.values) {
      var previous = controller.text;
      controller.addListener(() {
        if (controller.text != previous) {
          previous = controller.text;
          _configurationChanged();
        }
      });
    }
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    unawaited(_refresh());
  }

  Map<String, TextEditingController> get _configurationFields => {
    'goal': _goal,
    'user_simulator_instructions': _userSimulatorInstructions,
    'rounds': _rounds,
    'initial_training_case_count': _initialTrainingCount,
    'training_cases_per_round': _trainingIncrement,
    'max_system_prompt_chars': _systemPromptLimit,
    'max_skill_chars': _skillLengthLimit,
    'max_skill_count': _skillCountLimit,
    'max_edit_repairs': _editRepairLimit,
    'validation_case_count': _testCount,
    'human_test_count': _humanTestCount,
    'max_concurrency': _concurrency,
    'evaluation_repeats': _evaluationRepeats,
    'human_test_repeats': _humanTestRepeats,
  };

  void _configurationChanged() {
    if (!_restoringConfiguration) _configurationEdited = true;
  }

  Future<void> _restoreConfiguration(
    Map<String, Object?>? run,
    int revision,
  ) async {
    if (_configurationRestored || run == null || widget.historyOnly) return;
    _configurationRestored = true;
    if (_configurationEdited || _mutating) return;
    // A failed run has the same durable input snapshot as a successful one.
    // Restore once; subsequent polling must never reset the user's new edits.
    setState(() {
      _restoringConfiguration = true;
      try {
        for (final entry in _configurationFields.entries) {
          if (run[entry.key] != null) {
            entry.value.text = run[entry.key].toString();
          }
        }
        _model =
            (run.containsKey('requested_model_provider_id')
                    ? run['requested_model_provider_id']
                    : run['model_provider_id'])
                ?.toString();
        _scorerId = run['scorer_id']?.toString();
        _userSimulatorId = run['user_simulator_id']?.toString();
        _builtinScoring =
            map(run['builtin_scoring'])['mode']?.toString() ?? 'quality';
        if (run['optimization_scope'] is List) {
          _parts
            ..clear()
            ..addAll((run['optimization_scope'] as List).whereType<String>());
        }
        _requestId = null;
        _requestOptions = null;
      } finally {
        _restoringConfiguration = false;
      }
    });
    Map<String, Object?>? dataset;
    if (run['dataset_version_id'] != null) {
      dataset = await widget.controller.rsiDataset(
        widget.agentId,
        run['dataset_version_id'].toString(),
      );
    } else if (run['dataset_manifest'] != null ||
        run['suite'] != null ||
        run['dataset'] != null) {
      dataset = await widget.controller.rsiRunDataset(
        widget.agentId,
        run['id'].toString(),
      );
    }
    final restoredDataset = dataset;
    if (!mounted ||
        revision != _revision ||
        _configurationEdited ||
        _mutating ||
        restoredDataset == null) {
      return;
    }
    setState(() {
      _datasetVersion = restoredDataset;
      _cases.text = jsonEncode(restoredDataset['dataset']);
      _caseFilename =
          map(restoredDataset['manifest'])['name']?.toString() ??
          map(restoredDataset['dataset'])['name']?.toString();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _goal.dispose();
    _userSimulatorInstructions.dispose();
    _rounds.dispose();
    _initialTrainingCount.dispose();
    _trainingIncrement.dispose();
    _systemPromptLimit.dispose();
    _skillLengthLimit.dispose();
    _skillCountLimit.dispose();
    _editRepairLimit.dispose();
    _testCount.dispose();
    _humanTestCount.dispose();
    _concurrency.dispose();
    _evaluationRepeats.dispose();
    _humanTestRepeats.dispose();
    _cases.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_loadingRevision == _revision || !mounted) return;
    final revision = _revision;
    _loadingRevision = revision;
    try {
      final history = await widget.controller.rsiHistory(widget.agentId);
      if (!mounted || revision != _revision) return;
      setState(() {
        _history = history;
        if (!_versions) {
          _selectedRun ??= rows(history['runs']).firstOrNull?['id']?.toString();
        }
      });
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
      await _restoreConfiguration(run, revision);
      if (_versions && _selectedVersionId == null) {
        final latest = rows(history['versions']).firstOrNull;
        if (latest != null) await _openVersion(latest);
      }
    } on Object catch (e) {
      if (mounted && revision == _revision) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (_loadingRevision == revision) _loadingRevision = null;
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

  Future<void> _confirmCancellation() async {
    if (_mutating || _confirmingCancellation || !active(_run?['status'])) {
      return;
    }
    final runId = _run!['id'].toString();
    _confirmingCancellation = true;
    bool? confirmed;
    try {
      confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => Dialog(
          backgroundColor: Theme.of(context).colorScheme.surface,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: GlassCard(
              settings: glass,
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    t('确认取消优化？', 'Cancel this optimization?'),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 24),
                  Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      action(
                        t('继续运行', 'Keep running'),
                        CupertinoIcons.play_arrow_solid,
                        () => Navigator.pop(dialogContext, false),
                        key: const ValueKey('rsi-cancel-dismiss'),
                        width: 124,
                      ),
                      action(
                        t('确认取消', 'Confirm cancellation'),
                        CupertinoIcons.stop,
                        () => Navigator.pop(dialogContext, true),
                        key: const ValueKey('rsi-cancel-confirm'),
                        width: 144,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    } finally {
      _confirmingCancellation = false;
    }
    if (confirmed != true ||
        !mounted ||
        _run?['id'] != runId ||
        !active(_run?['status'])) {
      return;
    }
    await _mutate(() => widget.controller.cancelRsi(widget.agentId, runId));
  }

  Future<void> _start() async {
    if (_goal.text.trim().isEmpty) {
      setState(() => _showConfiguration = true);
      return;
    }
    await _mutate(() async {
      final count = int.tryParse(_rounds.text);
      final initialTrainingCount = int.tryParse(_initialTrainingCount.text);
      final trainingIncrement = int.tryParse(_trainingIncrement.text);
      final systemPromptLimit = int.tryParse(_systemPromptLimit.text);
      final skillLengthLimit = int.tryParse(_skillLengthLimit.text);
      final skillCountLimit = int.tryParse(_skillCountLimit.text);
      final editRepairLimit = int.tryParse(_editRepairLimit.text);
      final testCount = int.tryParse(_testCount.text);
      final humanTestCount = int.tryParse(_humanTestCount.text);
      final concurrency = int.tryParse(_concurrency.text);
      final evaluationRepeats = int.tryParse(_evaluationRepeats.text);
      final humanTestRepeats = int.tryParse(_humanTestRepeats.text);
      if (_goal.text.trim().isEmpty ||
          count == null ||
          count < 1 ||
          count > 100 ||
          initialTrainingCount == null ||
          initialTrainingCount < 1 ||
          initialTrainingCount > 100 ||
          trainingIncrement == null ||
          trainingIncrement < 0 ||
          trainingIncrement > 100 ||
          systemPromptLimit == null ||
          systemPromptLimit < 1 ||
          systemPromptLimit > 1000000 ||
          skillLengthLimit == null ||
          skillLengthLimit < 1 ||
          skillLengthLimit > 1000000 ||
          skillCountLimit == null ||
          skillCountLimit < 0 ||
          skillCountLimit > 256 ||
          editRepairLimit == null ||
          editRepairLimit < 0 ||
          editRepairLimit > 10 ||
          testCount == null ||
          testCount < 1 ||
          testCount > 100 ||
          humanTestCount == null ||
          humanTestCount < 0 ||
          humanTestCount > 100 ||
          concurrency == null ||
          concurrency < 1 ||
          concurrency > 16 ||
          evaluationRepeats == null ||
          evaluationRepeats < 1 ||
          evaluationRepeats > 10 ||
          humanTestRepeats == null ||
          humanTestRepeats < 1 ||
          humanTestRepeats > 10 ||
          _parts.isEmpty) {
        throw FormatException(
          t(
            '请输入目标、1–1000000 字符的指令和 Skill 长度上限、0–256 个 Skill、1–100 道初始训练题、0–100 道每轮新增训练题、1–100 轮、1–100 道验证题、0–100 道测试题、1–16 并行上限、1–10 次评测与测试集重复和优化范围',
            'Enter a goal, 1–1000000 character prompt and Skill limits, 0–256 Skills, 1–100 initial training cases, 0–100 new training cases per round, 1–100 rounds, 1–100 validation cases, 0–100 test cases, 1–16 concurrency, 1–10 evaluation and test set repeats and optimization parts',
          ),
        );
      }
      final suite = _cases.text.trim().isEmpty ? null : jsonDecode(_cases.text);
      final options = jsonEncode([
        _datasetVersion?['id'],
        _goal.text.trim(),
        count,
        initialTrainingCount,
        trainingIncrement,
        systemPromptLimit,
        skillLengthLimit,
        skillCountLimit,
        editRepairLimit,
        testCount,
        humanTestCount,
        concurrency,
        evaluationRepeats,
        humanTestRepeats,
        _parts.toList(),
        _model,
        suite,
        _scorerId,
        _builtinScoring,
        _userSimulatorId,
        _userSimulatorInstructions.text.trim(),
      ]);
      if (_requestOptions != options) {
        _requestId = null;
        _requestOptions = options;
      }
      _requestId ??= 'desktop-${DateTime.now().microsecondsSinceEpoch}';
      final started = await widget.controller.startRsi(widget.agentId, {
        'goal': _goal.text.trim(),
        if (_userSimulatorId != null)
          'user_simulator_id': _userSimulatorId
        else if (_userSimulatorInstructions.text.trim().isNotEmpty)
          'user_simulator_instructions': _userSimulatorInstructions.text.trim(),
        'rounds': count,
        'max_system_prompt_chars': systemPromptLimit,
        'max_skill_chars': skillLengthLimit,
        'max_skill_count': skillCountLimit,
        'max_edit_repairs': editRepairLimit,
        'initial_training_case_count': initialTrainingCount,
        'training_cases_per_round': trainingIncrement,
        'validation_case_count': testCount,
        'human_test_count': humanTestCount,
        'max_concurrency': concurrency,
        'evaluation_repeats': evaluationRepeats,
        'human_test_repeats': humanTestRepeats,
        'optimization_scope': _parts.toList(),
        'model_provider_id': _model,
        'request_id': _requestId,
        'scorer_id': ?_scorerId,
        'builtin_scoring': {'mode': _builtinScoring},
        if (_builtinScoring == 'pairwise') 'evaluation_aggregation': 'mean',
        if (_datasetVersion != null)
          'dataset_version_id': _datasetVersion!['id']
        else
          (suite is Map && suite['format_version'] == 'sage.rsi.dataset/v1'
                  ? 'dataset'
                  : 'suite'):
              ?suite,
      });
      _requestId = null;
      _requestOptions = null;
      _showConfiguration = false;
      _selectedRun = started['id']?.toString();
      _events.clear();
      _version = null;
      _run = null;
      _revision++;
    });
  }

  Future<void> _openVersion(Map<String, Object?> item) async {
    final revision = ++_revision;
    setState(() {
      _selectedVersionId = item['id'].toString();
      _versionMode = true;
      _version = null;
      _versionLoading = true;
      _error = null;
    });
    try {
      final value = await widget.controller.rsiVersion(
        widget.agentId,
        item['id'].toString(),
      );
      if (mounted && revision == _revision) {
        setState(() {
          _version = value;
          _versionMode = true;
          _error = null;
        });
      }
    } on Object catch (e) {
      if (mounted && revision == _revision) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted && revision == _revision) {
        setState(() => _versionLoading = false);
      }
    }
  }

  Future<void> _saveVersionAsAgent() => _mutate(() async {
    final version = _version;
    if (version == null) return;
    final savedName = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (_) => RsiSaveAgentDialog(
        initialName:
            '${version['name'] ?? widget.agentName} · ${versionLabel(version)}',
        chinese: context.l10n.locale.languageCode == 'zh',
        settings: glass,
        onSave: (name, requestId) async {
          await widget.controller.saveRsiVersionAsAgent(
            widget.agentId,
            version['id'].toString(),
            name,
            requestId,
          );
        },
      ),
    );
    if (mounted && savedName != null) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text(t('已保存为 $savedName', 'Saved as $savedName'))),
      );
    }
  });

  Future<void> _versionDiff() => _mutate(() async {
    final version = _version;
    if (version == null || version['run_id'] == null) return;
    final runId = version['run_id'].toString();
    var detail = await widget.controller.rsiRun(widget.agentId, runId);
    final events = rows(detail['events']);
    while (map(detail['result']).isEmpty &&
        events.isNotEmpty &&
        (events.last['sequence'] as num).toInt() <
            ((detail['sequence'] as num?)?.toInt() ?? 0)) {
      detail = await widget.controller.rsiRun(
        widget.agentId,
        runId,
        afterSequence: (events.last['sequence'] as num).toInt(),
      );
      final batch = rows(detail['events']);
      if (batch.isEmpty) break;
      events.addAll(batch);
    }
    final diff = collectRsiRoundDiffs(
      detail,
      events,
    ).where((d) => d.round == version['iteration']).firstOrNull;
    if (mounted && diff != null) {
      await showRsiRoundDiff(
        context,
        diff,
        glass,
        context.l10n.languageCode == 'zh',
      );
    }
  });

  Future<void> _export(Object value, String filename) => _mutate(() async {
    final location = await getSaveLocation(suggestedName: filename);
    if (location != null) {
      await File(
        location.path,
      ).writeAsString(const JsonEncoder.withIndent('  ').convert(value));
    }
  });
  String versionLabel(Map<String, Object?> v) => v['source'] == 'rsi'
      ? ((v['iteration'] as num?) == 0
            ? t('基线', 'Baseline')
            : '${t('迭代', 'Iteration')} ${v['iteration']}')
      : v['source'] == 'activation'
      ? t('已应用版本', 'Applied version')
      : t('配置保存', 'Configuration save');
  String timestamp(Object? value) {
    final parsed = DateTime.tryParse(value?.toString() ?? '')?.toLocal();
    if (parsed == null) return value?.toString() ?? '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(parsed.month)}-${two(parsed.day)} ${two(parsed.hour)}:${two(parsed.minute)}';
  }

  String status(Object? v) => switch (v) {
    'queued' => t('排队中', 'Queued'),
    'running' => t('优化中', 'Optimizing'),
    'completed' => t('已完成', 'Completed'),
    'failed' => t('失败', 'Failed'),
    'cancelled' => t('已取消', 'Cancelled'),
    'interrupted' => t('已中断', 'Interrupted'),
    _ => v?.toString() ?? '',
  };
  String stage(Object? v, {Object? role, Object? activity}) => rsiActivityLabel(
    v,
    role: role,
    activity: activity,
    chinese: context.l10n.locale.languageCode == 'zh',
  );
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
    bool? expanded,
  }) => Semantics(
    key: key,
    button: true,
    enabled: onTap != null,
    toggled: expanded,
    label: label,
    onTap: onTap,
    excludeSemantics: true,
    child: IgnorePointer(
      ignoring: onTap == null,
      child: Opacity(
        opacity: onTap == null ? 0.45 : 1,
        child: Stack(
          children: [
            GlassButton.custom(
              width: width,
              height: 34,
              settings: glass,
              shape: const LiquidRoundedRectangle(borderRadius: 10),
              onTap: onTap ?? () {},
              child: Padding(
                padding: expanded == null
                    ? EdgeInsets.zero
                    : const EdgeInsets.symmetric(horizontal: 10),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      icon,
                      size: 15,
                      color: expanded == true
                          ? Theme.of(context).colorScheme.primary
                          : null,
                    ),
                    const SizedBox(width: 7),
                    Flexible(
                      child: Text(
                        label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: expanded == true
                              ? Theme.of(context).colorScheme.primary
                              : null,
                        ),
                      ),
                    ),
                    if (expanded != null) ...[
                      const SizedBox(width: 6),
                      AnimatedRotation(
                        turns: expanded ? .5 : 0,
                        duration: const Duration(milliseconds: 180),
                        child: Icon(
                          CupertinoIcons.chevron_down,
                          size: 12,
                          color: expanded
                              ? Theme.of(context).colorScheme.primary
                              : null,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            if (expanded == true)
              Positioned.fill(
                child: IgnorePointer(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: Theme.of(
                        context,
                      ).colorScheme.primary.withValues(alpha: .08),
                      border: Border.all(
                        color: Theme.of(
                          context,
                        ).colorScheme.primary.withValues(alpha: .45),
                      ),
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );

  Widget field(String label, Widget control) =>
      widget.fieldBuilder?.call(label, control) ??
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: LayoutBuilder(
          builder: (context, constraints) => constraints.maxWidth < 760
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
                      width: 220,
                      child: Text(
                        label,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const SizedBox(width: 24),
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerLeft,
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
    final decoded = jsonDecode(await file.readAsString());
    final value = map(decoded is List ? {'cases': decoded} : decoded);
    final registered = await widget.controller.importRsiDataset(
      widget.agentId,
      value,
    );
    _datasetVersion = registered;
    final counts = map(map(registered['manifest'])['counts']);
    _testCount.text = map(counts['validation'])['active'].toString();
    _humanTestCount.text = map(counts['test'])['active'].toString();
    _cases.text = jsonEncode(registered['dataset']);
    _caseFilename = file.name;
    _requestId = null;
    if (mounted) {
      setState(() {});
      await showDatasetDetails(registered);
    }
  });

  Future<void> reviewDatasetIssue([
    Map<String, Object?> issue = const {},
    bool prepared = false,
  ]) => _mutate(() async {
    final version = prepared || _run == null
        ? _datasetVersion
        : await widget.controller.rsiRunDataset(
            widget.agentId,
            _run!['id'].toString(),
          );
    if (version == null || !mounted) return;
    final proposal = await showDialog<Map<String, Object?>>(
      context: context,
      builder: (_) => RsiDatasetRevisionDialog(
        version: version,
        issue: issue,
        chinese: context.l10n.locale.languageCode == 'zh',
      ),
    );
    if (proposal == null) return;
    final revised = await widget.controller.reviseRsiDataset(
      widget.agentId,
      version['id'].toString(),
      proposal,
    );
    if (!mounted) return;
    setState(() {
      _datasetVersion = revised;
      _cases.text = jsonEncode(revised['dataset']);
      _caseFilename =
          '${map(revised['manifest'])['name']} · ${t('修订集', 'Revised dataset')}';
      final counts = map(map(revised['manifest'])['counts']);
      _testCount.text = map(counts['validation'])['active'].toString();
      _humanTestCount.text = map(counts['test'])['active'].toString();
      _requestId = null;
      _showConfiguration = true;
    });
  });

  Future<void> chooseDatasetVersion() => _mutate(() async {
    final selected = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: Text(t('选择数据集版本', 'Choose dataset version')),
        children: [
          for (final version in rows(_history['dataset_versions']))
            ListTile(
              key: ValueKey('rsi-dataset-version-${version['id']}'),
              title: Text(
                '${map(version['manifest'])['name']} · ${map(version['manifest'])['label'] == 'revised' ? t('修订集', 'Revised dataset') : t('原始集', 'Original dataset')}',
              ),
              subtitle: Text(
                '${version['id']}\n${t('原始 / 排除 / 参与', 'Original / excluded / active')}: '
                '${map(version['manifest'])['original_count']} / ${map(version['manifest'])['excluded_count']} / ${map(version['manifest'])['active_count']}',
              ),
              onTap: () => Navigator.pop(context, version['id'].toString()),
            ),
        ],
      ),
    );
    if (selected == null) return;
    final version = await widget.controller.rsiDataset(
      widget.agentId,
      selected,
    );
    if (!mounted) return;
    setState(() {
      _datasetVersion = version;
      _cases.text = jsonEncode(version['dataset']);
      final manifest = map(version['manifest']);
      _caseFilename =
          '${manifest['name']} · ${manifest['label'] == 'revised' ? t('修订集', 'Revised dataset') : t('原始集', 'Original dataset')}';
      _testCount.text = map(
        map(manifest['counts'])['validation'],
      )['active'].toString();
      _humanTestCount.text = map(
        map(manifest['counts'])['test'],
      )['active'].toString();
      _requestId = null;
    });
  });

  Future<void> showDatasetDetails(Map<String, Object?> version) =>
      showDialog<void>(
        context: context,
        builder: (_) => RsiDatasetDetailsDialog(
          version: version,
          chinese: context.l10n.locale.languageCode == 'zh',
        ),
      );

  Map<String, Object?> get _runDatasetManifest =>
      map(_run?['dataset_manifest'] ?? _run?['generated_dataset_manifest']);

  Widget runDatasetDetailsButton({String? label}) => action(
    label ?? t('查看详情', 'View details'),
    CupertinoIcons.doc_text_search,
    _mutating
        ? null
        : () => _mutate(() async {
            final version = await widget.controller.rsiRunDataset(
              widget.agentId,
              _run!['id'].toString(),
            );
            if (mounted) {
              await showDatasetDetails(version);
            }
          }),
    key: const ValueKey('rsi-run-dataset-details'),
    width: 112,
  );

  void selectScorer(Map<String, Object?>? plan) {
    _configurationChanged();
    setState(() {
      _scorerId = plan?['id']?.toString();
      _builtinScoring =
          map(plan?['validation'])['protocol'] == 'sage.rsi.comparison/v1'
          ? 'pairwise'
          : 'quality';
      _requestId = null;
    });
  }

  Future<void> chooseEvaluationMode() => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: GlassCard(
          settings: glass,
          padding: const EdgeInsets.all(8),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final mode in ['quality', 'pairwise'])
                ListTile(
                  key: ValueKey('rsi-evaluation-mode-$mode'),
                  title: Text(mode == 'pairwise'
                      ? t('配对比较', 'Pairwise comparison')
                      : t('绝对评分', 'Absolute scoring')),
                  selected: (_builtinScoring == 'pairwise') == (mode == 'pairwise'),
                  onTap: () {
                    _configurationChanged();
                    setState(() {
                      if ((_builtinScoring == 'pairwise') != (mode == 'pairwise')) {
                        _scorerId = null;
                        _builtinScoring = mode;
                        _requestId = null;
                      }
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

  String scorerLabel(Map<String, Object?> plan) {
    final name = plan['name']?.toString() ?? plan['id'].toString();
    final versions = rows(
      _history['scorers'],
    ).where((p) => p['name'] == plan['name']);
    if (versions.length < 2) return name;
    final version =
        (plan['source_hash'] ??
                map(plan['descriptor'])['version'] ??
                plan['id'])
            .toString();
    return '$name · ${version.length > 10 ? version.substring(0, 10) : version}';
  }

  bool latestScorer(Map<String, Object?> plan) =>
      rows(
        _history['scorers'],
      ).where((p) => p['name'] == plan['name']).firstOrNull?['id'] ==
      plan['id'];

  String? scorerLabelFor(Object? id) {
    final plan = rows(
      _history['scorers'],
    ).where((p) => p['id'] == id).firstOrNull;
    return plan == null ? null : scorerLabel(plan);
  }

  void selectUserSimulator(Map<String, Object?>? module) {
    _configurationChanged();
    setState(() {
      _userSimulatorId = module?['id']?.toString();
      _requestId = null;
    });
  }

  String userSimulatorLabel(Map<String, Object?> module) {
    final name = module['name']?.toString() ?? module['id'].toString();
    final versions = rows(
      _history['user_simulators'],
    ).where((m) => m['name'] == name);
    if (versions.length < 2) return name;
    final version =
        (map(module['descriptor'])['version'] ??
                module['source_hash'] ??
                module['id'])
            .toString();
    return '$name · ${version.length > 10 ? version.substring(0, 10) : version}';
  }

  String get userSimulatorName {
    final module = rows(
      _history['user_simulators'],
    ).where((m) => m['id'] == _userSimulatorId).firstOrNull;
    return module == null
        ? (_userSimulatorId ?? t('RSI 内置模拟用户', 'RSI built-in user'))
        : userSimulatorLabel(module);
  }

  Future<void> importUserSimulator() => _mutate(() async {
    final file = await openFile(
      acceptedTypeGroups: [
        const XTypeGroup(label: 'Python', extensions: ['py']),
      ],
    );
    if (file == null) return;
    final python = await scorerPythonExecutable(file.path);
    final module = await widget.controller
        .importRsiUserSimulator(widget.agentId, {
          'name': file.name,
          'source': await file.readAsString(),
          'python_executable': ?python,
        });
    if (mounted) selectUserSimulator(module);
  });

  Future<void> chooseUserSimulator() => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420, maxHeight: 480),
        child: GlassCard(
          settings: glass,
          padding: const EdgeInsets.all(8),
          child: ListView(
            shrinkWrap: true,
            children: [
              ListTile(
                key: const ValueKey('rsi-user-simulator-default'),
                title: Text(t('RSI 内置模拟用户', 'RSI built-in user')),
                selected: _userSimulatorId == null,
                onTap: () {
                  selectUserSimulator(null);
                  Navigator.pop(dialogContext);
                },
              ),
              for (final module in rows(_history['user_simulators']))
                ListTile(
                  key: ValueKey('rsi-user-simulator-${module['id']}'),
                  title: Text(userSimulatorLabel(module)),
                  subtitle: Text(
                    map(module['validation'])['status'] == 'passed'
                        ? t('自测通过', 'Self-test passed')
                        : t('未验证', 'Unverified'),
                  ),
                  selected: _userSimulatorId == module['id'],
                  onTap: () {
                    selectUserSimulator(module);
                    Navigator.pop(dialogContext);
                  },
                ),
            ],
          ),
        ),
      ),
    ),
  );

  Future<void> importScorer() => _mutate(() async {
    final file = await openFile(
      acceptedTypeGroups: [
        const XTypeGroup(label: 'Python', extensions: ['py']),
      ],
    );
    if (file == null) return;
    final python = await scorerPythonExecutable(file.path);
    final plan = await widget.controller.importRsiScorer(widget.agentId, {
      'name': file.name,
      'source': await file.readAsString(),
      'python_executable': ?python,
    });
    if (mounted) selectScorer(plan);
  });

  Future<void> chooseScorer() => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420, maxHeight: 480),
        child: GlassCard(
          settings: glass,
          padding: const EdgeInsets.all(8),
          child: ListView(
            shrinkWrap: true,
            children: [
              ListTile(
                key: const ValueKey('rsi-scorer-default'),
                title: Text(builtinScorerName('quality')),
                selected: _scorerId == null && _builtinScoring == 'quality',
                onTap: () {
                  selectScorer(null);
                  Navigator.pop(dialogContext);
                },
              ),
              for (final mode in [
                'pairwise',
                'quality_cost',
                'quality_latency',
                'quality_tokens',
              ])
                ListTile(
                  key: ValueKey('rsi-scorer-$mode'),
                  title: Text(builtinScorerName(mode)),
                  selected: _scorerId == null && _builtinScoring == mode,
                  onTap: () {
                    _configurationChanged();
                    selectScorer(null);
                    setState(() => _builtinScoring = mode);
                    Navigator.pop(dialogContext);
                  },
                ),
              for (final plan in rows(_history['scorers']))
                ListTile(
                  key: ValueKey('rsi-scorer-${plan['id']}'),
                  title: Text(scorerLabel(plan)),
                  subtitle: Text(
                    [
                      if (plan['created_at'] != null)
                        timestamp(plan['created_at'])
                      else
                        t('导入时间未记录', 'Import time unavailable'),
                      if (map(plan['validation'])['status'] == 'passed')
                        t('自测通过', 'Self-test passed'),
                    ].join(' · '),
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (latestScorer(plan))
                        Text(
                          t('最新', 'Latest'),
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      if (_scorerId == plan['id']) ...[
                        const SizedBox(width: 8),
                        const Icon(CupertinoIcons.checkmark, size: 16),
                      ],
                    ],
                  ),
                  selected: _scorerId == plan['id'],
                  onTap: () {
                    selectScorer(plan);
                    Navigator.pop(dialogContext);
                  },
                ),
            ],
          ),
        ),
      ),
    ),
  );

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
                      _configurationChanged();
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

  Widget _scorerHelp() => Tooltip(
    message: t('如何编写评分器', 'Writing a scorer'),
    child: GlassIconButton(
      key: const ValueKey('rsi-scorer-help'),
      size: 34,
      iconSize: 18,
      shape: GlassIconButtonShape.roundedSquare,
      borderRadius: 10,
      settings: glass,
      icon: const Icon(CupertinoIcons.question_circle),
      onPressed: () => showRsiScorerGuide(
        context,
        chinese: context.l10n.languageCode == 'zh',
      ),
    ),
  );

  Widget _readOnlyConfiguration() {
    final historyRun =
        rows(
          _history['runs'],
        ).where((r) => r['id'] == _selectedRun).firstOrNull ??
        rows(_history['runs']).where((r) => active(r['status'])).firstOrNull ??
        <String, Object?>{};
    final current = map(_run);
    final started = current.isNotEmpty
        ? map(
            _events
                .where((e) => e['event'] == 'operation_started')
                .firstOrNull?['data'],
          )
        : <String, Object?>{};
    final snapshot = {
      ...started,
      ...map(started['constraints']),
      ...historyRun,
      ...current,
    };
    snapshot.putIfAbsent('human_test_repeats', () => 1);
    if (snapshot['initial_training_case_count'] == null) {
      final fixed = map(
        _events.where((e) => e['event'] == 'suite_fixed').firstOrNull?['data'],
      );
      final cases = rows(map(fixed['suite'] ?? started['suite'])['cases']);
      if (cases.isNotEmpty) {
        snapshot['initial_training_case_count'] = cases
            .where((c) => c['split'] == 'training')
            .length;
      }
    }
    Widget value(String key, Object? content) => SelectableText(
      content?.toString().trim().isNotEmpty == true ? content.toString() : '—',
      key: ValueKey('rsi-readonly-$key'),
      style: Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.5),
    );
    final scorer = map(snapshot['scorer']);
    final scorerName =
        scorerLabelFor(snapshot['scorer_id']) ??
        map(scorer['descriptor'])['name'] ??
        rows(
          _history['scorers'],
        ).where((r) => r['id'] == snapshot['scorer_id']).firstOrNull?['name'] ??
        snapshot['scorer_id'] ??
        (snapshot['external_host'] == true
            ? '—'
            : builtinScorerName(
                map(snapshot['builtin_scoring'])['mode']?.toString() ??
                    'quality',
              ));
    final providerId = snapshot['model_provider_id'];
    final providerName =
        widget.controller.modelProviders
            .where((p) => p.id == providerId)
            .firstOrNull
            ?.name ??
        providerId;
    final partNames = <String, String>{
      'instructions': t('指令', 'Instructions'),
      'skills': 'Skills',
      'tools': t('工具', 'Tools'),
      'budgets': t('步数预算', 'Step budget'),
    };
    final parts = (snapshot['optimization_scope'] as List? ?? [])
        .map((p) => partNames[p] ?? p.toString())
        .join(' · ');
    final fields = [
      field(
        t('评价模式', 'Evaluation mode'),
        Text(
          map(snapshot['builtin_scoring'])['mode'] == 'pairwise'
              ? t('配对比较', 'Pairwise comparison')
              : t('绝对评分', 'Absolute scoring'),
        ),
      ),
      field(
        t('评分器', 'Scorer'),
        Wrap(
          spacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [value('scorer', scorerName), _scorerHelp()],
        ),
      ),
      field(
        t('模拟用户', 'Simulated user'),
        value(
          'user-simulator',
          map(map(snapshot['user_simulator'])['descriptor'])['name'] ??
              snapshot['user_simulator_id'] ??
              (snapshot['user_simulator_instructions'] != null
                  ? t(
                      'RSI 内置模拟用户（自定义指令）',
                      'RSI built-in user (custom instructions)',
                    )
                  : t('RSI 内置模拟用户', 'RSI built-in user')),
        ),
      ),
      field(t('优化目标', 'Optimization goal'), value('goal', snapshot['goal'])),
      for (final entry in <String, String>{
        'rounds': t('优化轮数', 'Rounds'),
        'initial_training_case_count': t(
          '初始训练题数',
          'Initial training questions',
        ),
        'training_cases_per_round': t(
          '每轮新增训练题数',
          'New training questions per round',
        ),
        'max_system_prompt_chars': t(
          'System 指令字符上限',
          'System prompt character limit',
        ),
        'max_skill_chars': t('单个 SKILL.md 字符上限', 'SKILL.md character limit'),
        'max_skill_count': t('Skill 数量上限', 'Skill count limit'),
        'max_edit_repairs': t('校验失败修正次数', 'Validation repair attempts'),
        'validation_case_count': t('验证题量 dev', 'Dev questions'),
        'human_test_count': t('测试题量 test', 'Test questions'),
        'max_concurrency': t('并行上限', 'Concurrency limit'),
        'evaluation_repeats': t('评测重复次数', 'Evaluation repeats'),
        'human_test_repeats': t('测试集重复次数', 'Test set repeats'),
      }.entries)
        field(entry.value, value(entry.key, snapshot[entry.key])),
      field(
        t('内部 Agent 模型', 'Internal agent model'),
        value('model', providerName),
      ),
      field(t('优化范围', 'Optimization parts'), value('parts', parts)),
      if (_runDatasetManifest.isNotEmpty)
        field(
          t('数据集', 'Dataset'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              value('dataset', _runDatasetManifest['name']),
              runDatasetDetailsButton(),
            ],
          ),
        ),
    ];
    return Column(
      key: const ValueKey('rsi-configuration-readonly'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final row in fields) ...[
          row,
          Divider(
            height: 1,
            color: Theme.of(context).colorScheme.outlineVariant,
          ),
        ],
      ],
    );
  }

  Widget form(bool busy) {
    if (busy) return _readOnlyConfiguration();
    final enabled = !busy && !_mutating;
    final modelLabel =
        widget.controller.modelProviders
            .where((m) => m.id == _model)
            .firstOrNull
            ?.name ??
        _model ??
        t('目标 Agent 模型', 'Target agent model');
    final fields = [
      field(
        t('评价模式', 'Evaluation mode'),
        GlassPicker(
          key: const ValueKey('rsi-evaluation-mode-picker'),
          value: _builtinScoring == 'pairwise'
              ? t('配对比较', 'Pairwise comparison')
              : t('绝对评分', 'Absolute scoring'),
          width: 260,
          height: 34,
          settings: glass,
          textStyle: Theme.of(context).textTheme.bodyMedium,
          onTap: enabled ? chooseEvaluationMode : null,
        ),
      ),
      field(
        t('评分器', 'Scorer'),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            GlassPicker(
              key: const ValueKey('rsi-scorer-picker'),
              value:
                  scorerLabelFor(_scorerId) ??
                  _scorerId ??
                  builtinScorerName(_builtinScoring),
              width: 260,
              height: 34,
              settings: glass,
              textStyle: Theme.of(context).textTheme.bodyMedium,
              onTap: enabled ? chooseScorer : null,
            ),
            action(
              t('导入评分器', 'Import scorer'),
              CupertinoIcons.folder,
              enabled ? importScorer : null,
              key: const ValueKey('rsi-import-scorer'),
              width: 150,
            ),
            _scorerHelp(),
          ],
        ),
      ),
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
      for (final entry in [
        (
          t('初始训练题数', 'Initial training questions'),
          _initialTrainingCount,
          'rsi-initial-training-count',
        ),
        (
          t('每轮新增训练题数', 'New training questions per round'),
          _trainingIncrement,
          'rsi-training-increment',
        ),
        (
          t('System 指令字符上限', 'System prompt character limit'),
          _systemPromptLimit,
          'rsi-system-prompt-limit',
        ),
        (
          t('单个 SKILL.md 字符上限', 'SKILL.md character limit'),
          _skillLengthLimit,
          'rsi-skill-length-limit',
        ),
        (
          t('Skill 数量上限', 'Skill count limit'),
          _skillCountLimit,
          'rsi-skill-count-limit',
        ),
        (
          t('校验失败修正次数', 'Validation repair attempts'),
          _editRepairLimit,
          'rsi-edit-repair-limit',
        ),
        (t('验证题量 dev', 'Dev questions'), _testCount, 'rsi-test-count'),
        (
          t('测试题量 test', 'Test questions'),
          _humanTestCount,
          'rsi-human-test-count',
        ),
        (t('并行上限', 'Concurrency limit'), _concurrency, 'rsi-concurrency'),
        (
          t('评测重复次数', 'Evaluation repeats'),
          _evaluationRepeats,
          'rsi-evaluation-repeats',
        ),
        (
          t('测试集重复次数', 'Test set repeats'),
          _humanTestRepeats,
          'rsi-human-test-repeats',
        ),
      ])
        field(
          entry.$1,
          SizedBox(
            width: 88,
            child: GlassTextField(
              key: ValueKey(entry.$3),
              controller: entry.$2,
              enabled:
                  enabled &&
                  (entry.$3 != 'rsi-test-count' || _caseFilename == null) &&
                  (entry.$3 != 'rsi-human-test-count' ||
                      (_caseFilename == null ||
                          map(jsonDecode(_cases.text))['format_version'] !=
                              'sage.rsi.dataset/v1')),
              textStyle: Theme.of(context).textTheme.bodyMedium,
              settings: glass,
            ),
          ),
        ),
      field(
        t('模拟用户', 'Simulated user'),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            GlassPicker(
              key: const ValueKey('rsi-user-simulator-picker'),
              value: userSimulatorName,
              width: 260,
              height: 34,
              settings: glass,
              textStyle: Theme.of(context).textTheme.bodyMedium,
              onTap: enabled ? chooseUserSimulator : null,
            ),
            action(
              t('导入模拟用户', 'Import simulated user'),
              CupertinoIcons.folder,
              enabled ? importUserSimulator : null,
              key: const ValueKey('rsi-import-user-simulator'),
              width: 150,
            ),
          ],
        ),
      ),
      field(
        t('模拟用户（留空使用默认）', 'Simulated user (default when empty)'),
        SizedBox(
          width: 340,
          child: GlassTextField(
            key: const ValueKey('rsi-user-simulator-instructions'),
            controller: _userSimulatorInstructions,
            enabled: enabled && _userSimulatorId == null,
            maxLines: 3,
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
            key: const ValueKey('rsi-model-picker'),
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
                        _configurationChanged();
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
        t('数据集', 'Dataset'),
        Wrap(
          spacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            if (_caseFilename != null)
              Text(
                _caseFilename!,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            if (_datasetVersion != null)
              action(
                t('查看详情', 'View details'),
                CupertinoIcons.doc_text_search,
                _mutating
                    ? null
                    : () => _mutate(() async {
                        await showDatasetDetails(_datasetVersion!);
                      }),
                key: const ValueKey('rsi-prepared-dataset-details'),
                width: 112,
              ),
            if (_runDatasetManifest.isNotEmpty &&
                (_datasetVersion == null ||
                    _datasetVersion!['id'] !=
                        _runDatasetManifest['version_id']))
              runDatasetDetailsButton(label: t('本实验详情', 'Run details')),
            action(
              t('导入数据集', 'Import dataset'),
              CupertinoIcons.folder,
              enabled ? importSuite : null,
              key: const ValueKey('rsi-import-suite'),
              width: 126,
            ),
            if (rows(_history['dataset_versions']).isNotEmpty)
              action(
                t('选择版本', 'Choose version'),
                CupertinoIcons.square_stack,
                enabled ? chooseDatasetVersion : null,
                key: const ValueKey('rsi-choose-dataset-version'),
                width: 130,
              ),
            if (_datasetVersion != null)
              action(
                t('审核 / 修订', 'Review / revise'),
                CupertinoIcons.doc_text_search,
                enabled ? () => reviewDatasetIssue(const {}, true) : null,
                key: const ValueKey('rsi-review-dataset'),
                width: 130,
              ),
            if (_caseFilename != null)
              IconButton(
                tooltip: t('清除', 'Clear'),
                icon: const Icon(CupertinoIcons.xmark, size: 15),
                onPressed: !enabled
                    ? null
                    : () => setState(() {
                        _configurationChanged();
                        _cases.clear();
                        _datasetVersion = null;
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

  Future<void> runHistoryMenu(Map<String, Object?> run, Offset position) async {
    final overlay = Overlay.of(context).context.findRenderObject() as RenderBox;
    final point = overlay.globalToLocal(position);
    final blocked = active(run['status']) || _mutating;
    final choice = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        point.dx,
        point.dy,
        overlay.size.width - point.dx,
        overlay.size.height - point.dy,
      ),
      items: [
        PopupMenuItem(
          key: ValueKey('rsi-delete-run-${run['id']}'),
          value: 'delete',
          enabled: !blocked,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                CupertinoIcons.trash,
                size: 16,
                color: blocked ? null : Theme.of(context).colorScheme.error,
              ),
              const SizedBox(width: 8),
              Text(
                active(run['status'])
                    ? t('删除（请先停止实验）', 'Delete (stop experiment first)')
                    : t('删除', 'Delete'),
              ),
            ],
          ),
        ),
      ],
    );
    if (choice != 'delete' || !mounted || _mutating) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(t('删除实验历史？', 'Delete experiment history?')),
        content: Text(
          '${run['goal']}\n${timestamp(run['created_at'])}\n\n${t('此实验将从历史列表移除。运行日志、已保存的 Agent 版本和数据集仍会保留。', 'This experiment will be removed from history. Logs, saved Agent versions and datasets will be retained.')}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(t('取消', 'Cancel')),
          ),
          FilledButton(
            key: const ValueKey('rsi-confirm-delete-run'),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(t('删除', 'Delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await _mutate(() async {
      await widget.controller.deleteRsiRun(
        widget.agentId,
        run['id'].toString(),
      );
      if (!mounted) return;
      setState(() {
        final remaining = rows(
          _history['runs'],
        ).where((r) => r['id'] != run['id']).toList();
        _history = {..._history, 'runs': remaining};
        if (_selectedRun == run['id']) {
          _selectedRun = remaining.firstOrNull?['id']?.toString();
          _run = null;
          _version = null;
          _events.clear();
        }
        _revision++;
      });
    });
  }

  Widget historyList() {
    if (_history.isEmpty && _error == null) {
      return const SizedBox(
        key: ValueKey('rsi-history-loading'),
        height: 80,
        child: Center(child: CupertinoActivityIndicator()),
      );
    }
    final runs = rows(_history['runs']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!_versions) ...[
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
            GestureDetector(
              onSecondaryTapDown: (details) =>
                  runHistoryMenu(run, details.globalPosition),
              onLongPressStart: (details) =>
                  runHistoryMenu(run, details.globalPosition),
              child: ListTile(
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
                  '${t('目标：', 'Goal: ')}${run['goal']}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                subtitle: Text(
                  '${status(run['status'])} · ${run['iteration']}/${run['rounds']}\n${timestamp(run['created_at'])}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                trailing: active(run['status'])
                    ? const CupertinoActivityIndicator(radius: 7)
                    : null,
                onTap: () {
                  if (_selectedRun == run['id']) return;
                  setState(() {
                    _selectedRun = run['id'].toString();
                    _run = null;
                    _version = null;
                    _events.clear();
                    _error = null;
                    _revision++;
                  });
                  unawaited(_refresh());
                },
              ),
            ),
        ] else ...[
          for (final group in versionGroups().entries) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
              child: Text(
                group.key.isEmpty
                    ? t('配置记录', 'Configuration history')
                    : '${t('进化', 'Evolution')} · ${timestamp(runs.where((r) => r['id'] == group.key).firstOrNull?['created_at'] ?? group.value.first['created_at'])}',
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
            for (final v in group.value)
              ListTile(
                key: ValueKey('rsi-version-${v['id']}'),
                contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                selected: _selectedVersionId == v['id'],
                selectedTileColor: Theme.of(
                  context,
                ).colorScheme.primary.withValues(alpha: .1),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
                title: Text(
                  versionLabel(v),
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontWeight: _selectedVersionId == v['id']
                        ? FontWeight.w600
                        : FontWeight.w400,
                  ),
                ),
                trailing: Text(
                  group.key.isEmpty
                      ? timestamp(v['created_at'])
                      : timestamp(v['created_at']).split(' ').last,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
                onTap: () => _openVersion(v),
              ),
          ],
        ],
      ],
    );
  }

  String? get _optimizationFolder {
    final workspace = _run?['workspace_path']?.toString();
    if (workspace == null || workspace.isEmpty) return null;
    return Directory(workspace).parent.path;
  }

  Future<void> _openOptimizationFolder() async {
    final path = _optimizationFolder;
    if (path == null) return;
    try {
      if (widget.onOpenFolder != null) {
        await widget.onOpenFolder!(path);
      } else {
        if (!await Directory(path).exists()) {
          throw StateError(t('优化文件夹不存在', 'Optimization folder does not exist'));
        }
        final result = Platform.isMacOS
            ? await Process.run('/usr/bin/open', [path])
            : Platform.isWindows
            ? await Process.run('explorer.exe', [path])
            : await Process.run('xdg-open', [path]);
        if (result.exitCode != 0) {
          throw StateError(
            t('无法打开优化文件夹', 'Could not open optimization folder'),
          );
        }
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Map<String, List<Map<String, Object?>>> versionGroups() {
    final groups = <String, List<Map<String, Object?>>>{};
    for (final version in rows(_history['versions'])) {
      final run = version['source'] == 'rsi'
          ? version['run_id']?.toString() ?? ''
          : '';
      (groups[run] ??= []).add(version);
    }
    for (final entry in groups.entries) {
      if (entry.key.isNotEmpty) {
        entry.value.sort(
          (a, b) => ((b['iteration'] as num?) ?? 0).compareTo(
            (a['iteration'] as num?) ?? 0,
          ),
        );
      }
    }
    return groups;
  }

  @override
  Widget build(BuildContext context) {
    final busy = rows(_history['runs']).any((r) => active(r['status']));
    final canCancel = active(_run?['status']);
    final back = _versionMode && !widget.historyOnly
        ? () => setState(() {
            _revision++;
            _versionMode = false;
            _version = null;
            _versionLoading = false;
            _selectedVersionId = null;
          })
        : widget.onBack ??
              (Navigator.of(context).canPop()
                  ? () => Navigator.pop(context)
                  : null);
    final actions = Wrap(
      spacing: 8,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (!_versions) ...[
          action(
            _showRunHistory
                ? t('隐藏历史', 'Hide history')
                : t('实验历史', 'Experiments'),
            CupertinoIcons.list_bullet,
            () => setState(() => _showRunHistory = !_showRunHistory),
            key: const ValueKey('rsi-toggle-history'),
            width: 112,
          ),
          action(
            _showConfiguration
                ? t('收起设置', 'Hide setup')
                : t('展开设置', 'Show setup'),
            CupertinoIcons.slider_horizontal_3,
            () => setState(() => _showConfiguration = !_showConfiguration),
            key: const ValueKey('rsi-toggle-setup'),
            expanded: _showConfiguration,
            width: 144,
          ),
          action(
            _mutating
                ? t('处理中…', 'Processing…')
                : canCancel
                ? t('取消优化', 'Cancel optimization')
                : t('开始进化', 'Start evolution'),
            canCancel ? CupertinoIcons.stop : CupertinoIcons.play_arrow_solid,
            _mutating
                ? null
                : canCancel
                ? _confirmCancellation
                : busy
                ? null
                : _start,
            key: ValueKey(canCancel ? 'rsi-cancel' : 'rsi-start'),
            width: 124,
          ),
        ],
        if (!_versions)
          action(
            t('版本管理', 'Versions'),
            CupertinoIcons.clock,
            () => setState(() {
              _versionMode = true;
              _version = null;
            }),
            width: 112,
          ),
        if (!_versions && _optimizationFolder != null)
          action(
            t('打开优化文件夹', 'Open optimization folder'),
            CupertinoIcons.folder_open,
            _openOptimizationFolder,
            key: const ValueKey('rsi-open-folder'),
            width: 164,
          ),
        if (!_versions &&
            _run?['resumable'] == true &&
            _run?['external_host'] != true &&
            {'interrupted', 'cancelled', 'failed'}.contains(_run?['status']))
          action(
            t('恢复进化', 'Resume evolution'),
            CupertinoIcons.play_arrow_solid,
            _mutating
                ? null
                : () => _mutate(
                    () => widget.controller.resumeRsi(
                      widget.agentId,
                      _run!['id'].toString(),
                    ),
                  ),
            key: const ValueKey('rsi-resume'),
            width: 120,
          ),
        if (!_versions && _canResumeTests)
          action(
            t('继续测试', 'Continue tests'),
            CupertinoIcons.play_arrow_solid,
            _mutating || busy
                ? null
                : () => _mutate(
                    () => widget.controller.resumeRsiTests(
                      widget.agentId,
                      _run!['id'].toString(),
                    ),
                  ),
            key: const ValueKey('rsi-resume-tests'),
            width: 120,
          ),
        IconButton(
          tooltip: t('刷新', 'Refresh'),
          onPressed: _refresh,
          icon: const Icon(CupertinoIcons.refresh, size: 18),
        ),
        if (back != null)
          action(
            _versionMode && !widget.historyOnly
                ? t('返回进化', 'Back to evolution')
                : t('返回 Agent', 'Back to agent'),
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
          if (_versions &&
              (_history.isEmpty || _versionLoading) &&
              _error == null)
            SizedBox(
              key: const ValueKey('rsi-version-loading'),
              height: 280,
              child: Center(
                child: Semantics(
                  label: t('加载中', 'Loading'),
                  child: const CupertinoActivityIndicator(),
                ),
              ),
            ),
          if (!_versions &&
              _run == null &&
              _selectedRun != null &&
              _error == null)
            SizedBox(
              key: const ValueKey('rsi-run-loading'),
              height: 280,
              child: Center(
                child: Semantics(
                  label: t('加载中', 'Loading'),
                  child: const CupertinoActivityIndicator(),
                ),
              ),
            )
          else if (!_versions && (_run != null || _error == null))
            RsiObservatory(
              run: _run,
              events: _events,
              settings: glass,
              chinese: context.l10n.locale.languageCode == 'zh',
            ),
          if (_version != null)
            versionDetail()
          else if (!_versions && _run != null)
            runDetail(),
        ];
        if (constraints.maxWidth < 860) {
          return ListView(
            children: [
              if (!_versions && _showConfiguration) form(busy),
              const SizedBox(height: 22),
              if (_versions || _showRunHistory) historyList(),
              ...details,
            ],
          );
        }
        return Column(
          children: [
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_versions || _showRunHistory) ...[
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
                  ],
                  Expanded(
                    child: ListView(
                      children: [
                        if (!_versions && _showConfiguration) ...[
                          card(form(busy)),
                          const SizedBox(height: 12),
                        ],
                        ...details,
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
    final title =
        '${_versions ? t('版本历史', 'Version history') : t('进化', 'Evolution')} · ${widget.agentName}';
    // Each region shares one renderer with the same settings as its children.
    // The settings frame uses a different glass style, so keep it outside these layers.
    final glassActions = AdaptiveLiquidGlassLayer(
      settings: glass,
      child: actions,
    );
    final glassBody = AdaptiveLiquidGlassLayer(settings: glass, child: body);
    if (widget.frameBuilder != null) {
      return widget.frameBuilder!(
        title,
        glassActions,
        Material(type: MaterialType.transparency, child: glassBody),
      );
    }
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 28, 24, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(width: double.infinity, child: glassActions),
              const SizedBox(height: 28),
              Expanded(child: glassBody),
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
    title: Text(
      t('数据集语义诊断（模型意见）', 'Dataset semantic diagnosis (model opinion)'),
    ),
    trailing: Text(
      value['approved'] == true
          ? t('未发现疑点', 'No concerns')
          : t('有疑点，待人工核实', 'Concerns; human review needed'),
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
                '${issue['severity'] == 'blocking' ? t('模型判断：高风险', 'Model opinion: high risk') : t('模型建议', 'Model advice')} · ${(issue['case_ids'] as List? ?? []).join(', ')}',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              text(issue['rationale']?.toString() ?? ''),
              const SizedBox(height: 4),
              text(issue['suggested_fix']?.toString() ?? ''),
              if ((issue['evidence'] as List? ?? []).isNotEmpty)
                SelectableText(
                  '${t('证据', 'Evidence')}: ${(issue['evidence'] as List).join('\n')}',
                ),
              if ((issue['impact']?.toString() ?? '').isNotEmpty)
                text('${t('影响', 'Impact')}: ${issue['impact']}'),
              TextButton(
                key: ValueKey(
                  'rsi-review-case-${(issue['case_ids'] as List? ?? []).join('-')}',
                ),
                onPressed: _mutating ? null : () => reviewDatasetIssue(issue),
                child: Text(
                  t(
                    '人工审核并决定是否创建排除版本',
                    'Review evidence and decide on an exclusion version',
                  ),
                ),
              ),
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
              stage(run['stage'], role: run['role'], activity: run['activity']),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
          if (suiteCheck.isNotEmpty) suiteReview(suiteCheck),
          for (final diagnostic in rows(
            run['dataset_diagnostics'],
          ).where((item) => item['event'] != 'suite_review_completed'))
            ExpansionTile(
              title: Text(
                '${t('题目诊断记录', 'Case diagnosis record')} · ${diagnostic['event']}',
              ),
              children: [
                text(const JsonEncoder.withIndent('  ').convert(diagnostic)),
                TextButton(
                  onPressed: _mutating ? null : () => reviewDatasetIssue(),
                  child: Text(t('人工审核数据集', 'Review dataset')),
                ),
              ],
            ),
          if (run['error_type'] != null)
            Text(switch (run['error_code']) {
              'rsi.cost_unavailable' => t(
                '当前模型未提供费用数据，请选择其他评分器。',
                'This model does not report cost. Choose another scorer.',
              ),
              'rsi.tokens_unavailable' => t(
                '当前模型未提供完整 Token 用量，请选择其他评分器。',
                'This model does not report complete token usage. Choose another scorer.',
              ),
              _ => '${t('运行错误', 'Run error')}: ${run['error_type']}',
            }),
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
                    '${event['sequence']} · ${stage(event['event'], role: map(event['data'])['role'], activity: map(event['data'])['activity'])} · ${event['time']}',
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
  Map<String, Object?> versionDefinition(Map<String, Object?> version) {
    final manifest = map(map(version['package'])['manifest']);
    final agents = map(manifest['agents']);
    return map(
      agents[widget.agentId] ??
          agents[map(manifest['entrypoint'])['agent']] ??
          (agents.length == 1 ? agents.values.first : null),
    );
  }

  Widget versionFields(List<(String, String)> values) => LayoutBuilder(
    builder: (context, constraints) {
      final columns = constraints.maxWidth >= 700 ? 2 : 1;
      final width = (constraints.maxWidth - (columns - 1) * 24) / columns;
      return Wrap(
        spacing: 24,
        children: [
          for (final value in values)
            SizedBox(
              width: width,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(
                      color: Theme.of(
                        context,
                      ).colorScheme.outlineVariant.withValues(alpha: .45),
                    ),
                  ),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 110,
                      child: Text(
                        value.$1,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    Expanded(
                      child: SelectableText(
                        value.$2.isEmpty ? '—' : value.$2,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      );
    },
  );

  Widget versionSection(String title, Widget child, {Key? key}) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: GlassCard(
      key: key,
      width: double.infinity,
      settings: glass,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    ),
  );

  Widget versionDetail() {
    final version = _version!;
    final package = map(version['package']);
    final definition = versionDefinition(version);
    final instructions =
        map(definition['instructions'])['inline']?.toString() ??
        map(
          package['files'],
        )[map(definition['instructions'])['path']]?.toString() ??
        map(version['config'])['systemPrefix']?.toString() ??
        '';
    final samples = rows(map(map(version['record'])['evaluation'])['cases']);
    String mean(String split) {
      final cohort = samples
          .where((c) => map(c['case'])['split'] == split)
          .toList();
      if (cohort.any((c) {
        final details = map(map(c['grade'])['scorer_details']);
        return details['pairwise_pending'] == true ||
            map(details['pairwise'])['pending'] == true;
      })) {
        return '—';
      }
      final scores = cohort
          .map((c) => map(c['grade'])['score'])
          .whereType<num>()
          .toList();
      return scores.isEmpty || scores.length != cohort.length
          ? '—'
          : (scores.fold<double>(0, (sum, value) => sum + value) /
                    scores.length)
                .toStringAsFixed(3);
    }

    Widget tags(Object? values) {
      final names = values is List
          ? values.map((v) => v.toString()).toList()
          : <String>[];
      return names.isEmpty
          ? const Text('—')
          : Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final name in names)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: Theme.of(
                        context,
                      ).colorScheme.onSurface.withValues(alpha: .05),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: SelectableText(
                      name,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
              ],
            );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 16,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              versionLabel(version),
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
            Text(
              timestamp(version['created_at']),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            action(
              t('导出完整版本', 'Export full version'),
              CupertinoIcons.square_arrow_down,
              () => _export(version, 'agent-${version['id']}.json'),
              key: const ValueKey('rsi-export-version'),
              width: 136,
            ),
            action(
              t('另存为新 Agent', 'Save as new Agent'),
              CupertinoIcons.person_badge_plus,
              !_mutating &&
                      (version['source'] != 'rsi' ||
                          version['ready'] == true) &&
                      map(version['review'])['approved'] != false
                  ? _saveVersionAsAgent
                  : null,
              key: const ValueKey('rsi-save-as-agent'),
              width: 180,
            ),
            if (version['source'] == 'rsi' &&
                ((version['iteration'] as num?)?.toInt() ?? 0) > 0)
              action(
                t('查看本轮改动', 'View round changes'),
                CupertinoIcons.arrow_right_arrow_left,
                _mutating ? null : _versionDiff,
                key: const ValueKey('rsi-version-diff'),
                width: 144,
              ),
          ],
        ),
        const SizedBox(height: 20),
        if (samples.isNotEmpty)
          versionSection(
            t('评测分数', 'Evaluation scores'),
            versionFields([
              (t('训练集', 'Training'), mean('training')),
              (t('验证集', 'Validation'), mean('validation')),
              (t('测试集', 'Test'), mean('test')),
            ]),
          ),
        if (map(
              map(map(version['record'])['comparison'])['splits'],
            )['validation']
            is Map)
          versionSection(
            t('候选与当时最佳版本', 'Candidate vs incumbent'),
            RsiPairwiseSummary(
              summary: map(
                map(
                  map(map(version['record'])['comparison'])['splits'],
                )['validation'],
              ),
              settings: glass,
              chinese: context.l10n.locale.languageCode == 'zh',
            ),
          ),
        savedConfiguration(version),
        versionSection(
          t('指令', 'Instructions'),
          instructions.isEmpty
              ? const Text('—')
              : MarkdownBody(data: instructions, selectable: true),
        ),
        versionSection(
          t('工具与 Skills', 'Tools and Skills'),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                t('工具', 'Tools'),
                style: Theme.of(context).textTheme.labelMedium,
              ),
              const SizedBox(height: 8),
              tags(definition['tools']),
              const SizedBox(height: 18),
              Text('Skills', style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 8),
              tags(definition['skills']),
            ],
          ),
        ),
        if (version['review'] != null)
          versionSection(
            t('语义审查', 'Semantic review'),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  map(version['review'])['approved'] == true
                      ? t('通过', 'Approved')
                      : t('拒绝', 'Rejected'),
                  style: TextStyle(
                    color: map(version['review'])['approved'] == true
                        ? Theme.of(context).colorScheme.primary
                        : Theme.of(context).colorScheme.error,
                  ),
                ),
                const SizedBox(height: 8),
                text(map(version['review'])['rationale']?.toString() ?? '—'),
              ],
            ),
          ),
        if (map(
          package['files'],
        ).keys.any((name) => !name.startsWith('desktop/')))
          versionSection(
            t('版本文件', 'Version files'),
            Column(
              children: [
                for (final file in map(
                  package['files'],
                ).entries.where((file) => !file.key.startsWith('desktop/')))
                  ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    title: Text(
                      file.key,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    children: [
                      Align(
                        alignment: Alignment.centerLeft,
                        child: file.key.endsWith('.md')
                            ? MarkdownBody(
                                data: file.value.toString(),
                                selectable: true,
                              )
                            : text(file.value.toString()),
                      ),
                    ],
                  ),
              ],
            ),
          ),
      ],
    );
  }

  Widget savedConfiguration(Map<String, Object?> version) {
    final config = map(version['config']);
    final manifest = map(map(version['package'])['manifest']);
    final definition = versionDefinition(version);
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
          ? (id?.toString() ?? t('默认', 'Default'))
          : '${provider.name} · ${provider.model}';
    }

    final budget =
        map(definition['budgets'])['max_steps'] ??
        map(map(manifest['policies'])['budgets'])['max_steps'] ??
        config['maxLoopCount'];
    return versionSection(
      t('保存的配置', 'Saved configuration'),
      versionFields([
        (t('名称', 'Name'), version['name']?.toString() ?? '—'),
        if (config['description']?.toString().isNotEmpty == true)
          (t('描述', 'Description'), config['description'].toString()),
        (
          t('主模型', 'Primary model'),
          primary['model']?.toString() ??
              modelLabel(
                map(definition['models'])['primary'] ??
                    config['llm_provider_id'],
              ),
        ),
        (t('快速模型', 'Fast model'), modelLabel(config['fast_llm_provider_id'])),
        (t('模式', 'Mode'), config['agentMode']?.toString() ?? 'simple'),
        (t('步数预算', 'Step budget'), budget?.toString() ?? '—'),
        (
          t('深度思考', 'Deep thinking'),
          config['deepThinking'] == true ? t('开启', 'On') : t('关闭', 'Off'),
        ),
        if (config['thinkingLevel'] != null)
          (t('思考强度', 'Reasoning effort'), config['thinkingLevel'].toString()),
        (
          t('运行变量', 'Runtime variables'),
          variables.isEmpty
              ? '—'
              : variables.entries.map((v) => '${v.key}: ${v.value}').join('\n'),
        ),
        (
          t('Shell 授权', 'Shell approvals'),
          (config['approvedShellCommands'] as List?)?.join('\n') ?? '—',
        ),
      ]),
      key: const ValueKey('rsi-saved-configuration'),
    );
  }
}
