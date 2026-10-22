import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/cupertino.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

Map<String, Object?> _map(Object? value) =>
    value is Map ? value.cast<String, Object?>() : {};
List<Map<String, Object?>> _rows(Object? value) => value is List
    ? value.whereType<Map>().map((v) => v.cast<String, Object?>()).toList()
    : [];

class RsiChange {
  const RsiChange(this.kind, this.name, this.before, this.after);
  final String kind, name, before, after;
  bool get added => before.isEmpty;
  bool get removed => after.isEmpty;
}

class RsiRoundDiff {
  const RsiRoundDiff({
    required this.round,
    required this.parentRound,
    required this.parentAvailable,
    required this.accepted,
    required this.reused,
    required this.changes,
    this.candidateMissing = false,
  });
  final int round;
  final int? parentRound;
  final bool parentAvailable, reused, candidateMissing;
  final bool? accepted;
  final List<RsiChange> changes;
}

String _json(Object? value) =>
    const JsonEncoder.withIndent('  ').convert(value);
Map<String, Object?> _definition(Map<String, Object?> package) {
  final manifest = _map(package['manifest']);
  return _map(_map(manifest['agents'])[_map(manifest['entrypoint'])['agent']]);
}

String _instructions(Map<String, Object?> package) {
  final instruction = _map(_definition(package)['instructions']);
  return (instruction['inline'] ??
          _map(package['files'])[instruction['path']] ??
          '')
      .toString();
}

List<RsiChange> _changes(
  Map<String, Object?> before,
  Map<String, Object?> after,
) {
  final changes = <RsiChange>[];
  void add(String kind, String name, String old, String next) {
    if (old != next) changes.add(RsiChange(kind, name, old, next));
  }

  add('instructions', '', _instructions(before), _instructions(after));
  final oldAgent = _definition(before), newAgent = _definition(after);
  for (final kind in ['tools', 'skills']) {
    final oldNames = (oldAgent[kind] as List? ?? [])
        .map((v) => v.toString())
        .toSet();
    final newNames = (newAgent[kind] as List? ?? [])
        .map((v) => v.toString())
        .toSet();
    for (final name in {...oldNames, ...newNames}.toList()..sort()) {
      if (oldNames.contains(name) != newNames.contains(name)) {
        changes.add(
          RsiChange(
            kind,
            name,
            oldNames.contains(name) ? name : '',
            newNames.contains(name) ? name : '',
          ),
        );
      }
    }
  }
  final oldBudgets = _map(oldAgent['budgets']),
      newBudgets = _map(newAgent['budgets']);
  for (final key in {...oldBudgets.keys, ...newBudgets.keys}.toList()..sort()) {
    add(
      'budgets',
      key,
      oldBudgets.containsKey(key) ? _json(oldBudgets[key]) : '',
      newBudgets.containsKey(key) ? _json(newBudgets[key]) : '',
    );
  }
  final oldFiles = _map(before['files']), newFiles = _map(after['files']);
  for (final path in {...oldFiles.keys, ...newFiles.keys}.toList()..sort()) {
    var old = oldFiles[path]?.toString() ?? '',
        next = newFiles[path]?.toString() ?? '';
    if (old == next) continue;
    final kind = path.startsWith('tools/rsi/')
        ? 'tools'
        : path.contains('skills/') || path.endsWith('SKILL.md')
        ? 'skills'
        : 'files';
    if (path.startsWith('tools/rsi/')) {
      try {
        if (old.isNotEmpty) old = _json(jsonDecode(old));
      } on FormatException {
        /* Preserve the real source. */
      }
      try {
        if (next.isNotEmpty) next = _json(jsonDecode(next));
      } on FormatException {
        /* Preserve the real source. */
      }
    }
    add(kind, path, old, next);
  }
  return changes;
}

/// Resolve actual parent hashes; rejected proposals never become the next parent.
List<RsiRoundDiff> collectRsiRoundDiffs(
  Map<String, Object?>? run,
  List<Map<String, Object?>> events,
) {
  final result = _map(run?['result']), report = _map(result['report']);
  final records = <int, Map<String, Object?>>{};
  final packages = <int, Map<String, Object?>>{};
  final hashes = <String, int>{};
  final iterations = _rows(result['iterations']);
  for (final item in iterations) {
    final index = (item['iteration'] as num?)?.toInt();
    if (index != null && _map(item['package']).isNotEmpty) {
      packages[index] = _map(item['package']);
    }
  }
  void record(Map<String, Object?> value) {
    final index = (value['round'] as num?)?.toInt();
    if (index == null) return;
    records[index] = {...?records[index], ...value};
    if (_map(value['candidate_package']).isNotEmpty) {
      packages[index] = _map(value['candidate_package']);
    }
    final hash = _map(value['evaluation'])['package_hash']?.toString();
    if (hash != null && value['evaluation_reused'] != true) {
      hashes[hash] = index;
    }
  }

  for (final value in _rows(report['rounds'])) {
    record(value);
  }
  for (final event in events) {
    final data = _map(event['data']);
    if (event['event'] == 'operation_started') {
      packages[0] = _map(data['package']);
    }
    if (event['event'] == 'candidate_created') {
      final index = (data['round'] as num?)?.toInt();
      if (index != null) {
        packages[index] = _map(data['package']);
        records[index] = {...data, ...?records[index]};
      }
    }
    if (event['event'] == 'round_completed') record(_map(data['record']));
    if (event['event'] == 'evaluation_completed' && data['round'] == 0) {
      final hash = _map(data['evaluation'])['package_hash']?.toString();
      if (hash != null) hashes[hash] = 0;
    }
  }
  final baselineHash = _map(report['baseline'])['package_hash']?.toString();
  if (baselineHash != null) hashes[baselineHash] = 0;
  final output = <RsiRoundDiff>[];
  int retained = 0;
  for (final index in records.keys.toList()..sort()) {
    final item = records[index]!;
    final parentHash = item['parent_hash']?.toString();
    final parent = parentHash == null ? retained : hashes[parentHash];
    final before = packages[parent], after = packages[index];
    final reused = item['evaluation_reused'] == true;
    final available = before != null;
    final missing = after == null && !reused && item['accepted'] == false;
    output.add(
      RsiRoundDiff(
        round: index,
        parentRound: parent,
        parentAvailable: available,
        accepted: item['accepted'] as bool?,
        reused: reused,
        candidateMissing: missing,
        changes: available && after != null ? _changes(before, after) : [],
      ),
    );
    if (item['accepted'] == true) retained = index;
  }
  return output;
}

class RsiDiffLine {
  const RsiDiffLine(this.kind, this.text);
  final String kind, text;
}

/// Exact line diff with bounded LCS memory; large changed blocks use replacement.
List<RsiDiffLine> rsiLineDiff(String before, String after) {
  final old = before.isEmpty ? <String>[] : before.split('\n');
  final next = after.isEmpty ? <String>[] : after.split('\n');
  var prefix = 0, suffix = 0;
  while (prefix < old.length &&
      prefix < next.length &&
      old[prefix] == next[prefix]) {
    prefix++;
  }
  while (suffix < old.length - prefix &&
      suffix < next.length - prefix &&
      old[old.length - 1 - suffix] == next[next.length - 1 - suffix]) {
    suffix++;
  }
  final a = old.sublist(prefix, old.length - suffix),
      b = next.sublist(prefix, next.length - suffix);
  final lines = <RsiDiffLine>[];
  if (prefix > 3) lines.add(RsiDiffLine('context', '… ${prefix - 3} …'));
  for (final line in old.sublist(prefix > 3 ? prefix - 3 : 0, prefix)) {
    lines.add(RsiDiffLine('equal', line));
  }
  if (a.length * b.length > 200000) {
    lines.addAll(a.map((s) => RsiDiffLine('remove', s)));
    lines.addAll(b.map((s) => RsiDiffLine('add', s)));
  } else {
    final table = List.generate(
      a.length + 1,
      (_) => List<int>.filled(b.length + 1, 0),
    );
    for (var i = a.length - 1; i >= 0; i--) {
      for (var j = b.length - 1; j >= 0; j--) {
        table[i][j] = a[i] == b[j]
            ? table[i + 1][j + 1] + 1
            : (table[i + 1][j] >= table[i][j + 1]
                  ? table[i + 1][j]
                  : table[i][j + 1]);
      }
    }
    var i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] == b[j]) {
        lines.add(RsiDiffLine('equal', a[i++]));
        j++;
      } else if (j < b.length &&
          (i == a.length || table[i][j + 1] > table[i + 1][j])) {
        lines.add(RsiDiffLine('add', b[j++]));
      } else {
        lines.add(RsiDiffLine('remove', a[i++]));
      }
    }
  }
  for (final line in old.sublist(
    old.length - suffix,
    old.length - suffix + (suffix > 3 ? 3 : suffix),
  )) {
    lines.add(RsiDiffLine('equal', line));
  }
  if (suffix > 3) lines.add(RsiDiffLine('context', '… ${suffix - 3} …'));
  return lines;
}

String _kind(String kind, bool zh) => switch (kind) {
  'instructions' => zh ? '指令' : 'Instructions',
  'tools' => zh ? '工具' : 'Tools',
  'skills' => 'Skills',
  'budgets' => zh ? '预算' : 'Budgets',
  _ => zh ? '文件' : 'Files',
};
String _status(RsiRoundDiff diff, bool zh) =>
    diff.reused && diff.changes.isEmpty && diff.parentAvailable
    ? (zh ? '未修改' : 'No changes')
    : diff.accepted == true
    ? (zh ? '已采纳' : 'Accepted')
    : diff.accepted == false
    ? (zh ? '未采纳' : 'Rejected')
    : (zh ? '评测中' : 'Evaluating');

Future<void> showRsiRoundDiff(
  BuildContext context,
  RsiRoundDiff diff,
  LiquidGlassSettings settings,
  bool chinese,
) => showDialog<void>(
  context: context,
  builder: (context) => Dialog(
    backgroundColor: Colors.transparent,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 1000, maxHeight: 800),
      child: GlassCard(
        settings: LiquidGlassSettings(
          glassColor: Theme.of(context).colorScheme.surface,
          visibility: 1,
          blur: 0,
          thickness: 4,
          standardOpacityMultiplier: 1,
          lightIntensity: 0,
          glowIntensity: 0,
          chromaticAberration: 0,
        ),
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${chinese ? '第' : 'Round'} ${diff.round}${chinese ? ' 轮改动' : ' changes'} · ${_status(diff, chinese)}',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  tooltip: chinese ? '关闭' : 'Close',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(CupertinoIcons.xmark, size: 18),
                ),
              ],
            ),
            Text(
              diff.parentAvailable
                  ? '${diff.parentRound == 0 ? (chinese ? '基线' : 'Baseline') : '${chinese ? '第' : 'Round'} ${diff.parentRound}${chinese ? ' 轮' : ''}'} → R${diff.round}'
                  : chinese
                  ? '父版本尚未载入'
                  : 'Parent version not loaded',
            ),
            const SizedBox(height: 14),
            Flexible(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (diff.candidateMissing)
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(
                          chinese ? '未生成有效候选' : 'No valid candidate generated',
                        ),
                      ),
                    if (diff.parentAvailable &&
                        !diff.candidateMissing &&
                        diff.changes.isEmpty)
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(
                          chinese
                              ? '本轮未修改 Agent 配置'
                              : 'No Agent configuration changes',
                        ),
                      ),
                    for (final change in diff.changes)
                      ExpansionTile(
                        initiallyExpanded: change == diff.changes.first,
                        title: Text(
                          '${_kind(change.kind, chinese)}${change.name.isEmpty ? '' : ' · ${change.name}'}',
                        ),
                        trailing: Text(
                          change.added
                              ? '+'
                              : change.removed
                              ? '−'
                              : '±',
                          style: TextStyle(
                            color: change.removed
                                ? Theme.of(context).colorScheme.error
                                : Theme.of(context).colorScheme.primary,
                          ),
                        ),
                        children: [
                          _LineDiff(
                            before: change.before,
                            after: change.after,
                            chinese: chinese,
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    ),
  ),
);

class RsiRoundChanges extends StatelessWidget {
  const RsiRoundChanges({
    required this.run,
    required this.events,
    required this.settings,
    required this.chinese,
    super.key,
  });
  final Map<String, Object?>? run;
  final List<Map<String, Object?>> events;
  final LiquidGlassSettings settings;
  final bool chinese;
  @override
  Widget build(BuildContext context) {
    final rounds = collectRsiRoundDiffs(run, events);
    if (rounds.isEmpty) return const SizedBox.shrink();
    return GlassCard(
      settings: settings,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            chinese ? '进化改动' : 'Evolution changes',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final diff in rounds)
                GlassButton.custom(
                  key: ValueKey('rsi-round-diff-${diff.round}'),
                  settings: settings,
                  width: 240,
                  height: 64,
                  onTap: () =>
                      showRsiRoundDiff(context, diff, settings, chinese),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('R${diff.round} · ${_status(diff, chinese)}'),
                        const SizedBox(height: 4),
                        Text(
                          !diff.parentAvailable
                              ? (chinese ? '父版本尚未载入' : 'Parent not loaded')
                              : diff.candidateMissing
                              ? (chinese ? '未生成有效候选' : 'No valid candidate')
                              : diff.changes.isEmpty
                              ? (chinese ? '无改动' : 'No changes')
                              : {
                                  for (final kind in diff.changes.map(
                                    (c) => c.kind,
                                  ))
                                    _kind(kind, chinese),
                                }.join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LineDiff extends StatefulWidget {
  const _LineDiff({
    required this.before,
    required this.after,
    required this.chinese,
  });
  final String before, after;
  final bool chinese;
  @override
  State<_LineDiff> createState() => _LineDiffState();
}

class _LineDiffState extends State<_LineDiff> {
  int limit = 200;
  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final added = dark ? const Color(0xFF70DFB0) : const Color(0xFF08653C);
    final removed = dark ? const Color(0xFFFF9AA5) : const Color(0xFFAA1430);
    final lines = rsiLineDiff(widget.before, widget.after);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(10),
            child: Row(
              children: [
                Text(
                  '+ ${lines.where((l) => l.kind == 'add').length}',
                  style: TextStyle(color: added),
                ),
                const SizedBox(width: 14),
                Text(
                  '− ${lines.where((l) => l.kind == 'remove').length}',
                  style: TextStyle(color: removed),
                ),
              ],
            ),
          ),
          for (final line in lines.take(limit))
            Container(
              color: line.kind == 'add'
                  ? added.withValues(alpha: .09)
                  : line.kind == 'remove'
                  ? removed.withValues(alpha: .09)
                  : Colors.transparent,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
              child: SelectableText(
                '${line.kind == 'add'
                    ? '+ '
                    : line.kind == 'remove'
                    ? '− '
                    : '  '}${line.text}',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: line.kind == 'add'
                      ? added
                      : line.kind == 'remove'
                      ? removed
                      : null,
                ),
              ),
            ),
          if (lines.length > limit)
            TextButton(
              onPressed: () => setState(() => limit += 200),
              child: Text(widget.chinese ? '显示更多' : 'Show more'),
            ),
        ],
      ),
    );
  }
}
