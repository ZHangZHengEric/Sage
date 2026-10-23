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
    this.incomplete = false,
    this.rationale = '',
  });
  final int round;
  final String rationale;
  final int? parentRound;
  final bool parentAvailable, reused, candidateMissing, incomplete;
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
  final promptPaths = {
    _map(oldAgent['instructions'])['path'],
    _map(newAgent['instructions'])['path'],
  };
  for (final path in {...oldFiles.keys, ...newFiles.keys}.toList()..sort()) {
    if (promptPaths.contains(path)) continue;
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
      // Remeasuring an unchanged package does not create a new parent version.
      hashes.putIfAbsent(hash, () => index);
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
  // Terminal decisions reach the live snapshot before journal pagination catches
  // up. Update known proposals without inventing packages that are still loading.
  for (final value in _rows(run?['iterations'])) {
    final index = (value['round'] as num?)?.toInt();
    if (records.containsKey(index)) record(value);
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
        rationale: _map(item['patch'])['rationale']?.toString() ?? '',
        parentRound: parent,
        parentAvailable: available,
        accepted: item['accepted'] as bool?,
        reused: reused,
        candidateMissing: missing,
        incomplete:
            item['accepted'] == null &&
            const [
              'cancelled',
              'interrupted',
              'failed',
              'completed',
            ].contains(run?['status']),
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
String _status(RsiRoundDiff diff, bool zh) => diff.incomplete
    ? (zh ? '未完成' : 'Incomplete')
    : diff.reused && diff.changes.isEmpty && diff.parentAvailable
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
              child: _RsiDiffBrowser(diff: diff, chinese: chinese),
            ),
          ],
        ),
      ),
    ),
  ),
);

class _RsiDiffBrowser extends StatefulWidget {
  const _RsiDiffBrowser({required this.diff, required this.chinese});
  final RsiRoundDiff diff;
  final bool chinese;
  @override
  State<_RsiDiffBrowser> createState() => _RsiDiffBrowserState();
}

class _RsiDiffBrowserState extends State<_RsiDiffBrowser> {
  int selected = 0;
  final _scroll = ScrollController();
  String title(RsiChange change) =>
      change.name.isEmpty ? _kind(change.kind, widget.chinese) : change.name;
  String status(RsiChange change) => change.added
      ? (widget.chinese ? '新增' : 'Added')
      : change.removed
      ? (widget.chinese ? '删除' : 'Deleted')
      : (widget.chinese ? '修改' : 'Modified');
  Color color(RsiChange change) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return change.removed
        ? (dark ? const Color(0xFFFF9AA5) : const Color(0xFFAA1430))
        : change.added
        ? (dark ? const Color(0xFF70DFB0) : const Color(0xFF08653C))
        : Theme.of(context).colorScheme.primary;
  }

  void select(int index) {
    if (_scroll.hasClients) _scroll.jumpTo(0);
    setState(() => selected = index);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final diff = widget.diff;
    if (diff.candidateMissing ||
        !diff.parentAvailable ||
        diff.changes.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          diff.candidateMissing
              ? (widget.chinese ? '未生成有效候选' : 'No valid candidate generated')
              : !diff.parentAvailable
              ? (widget.chinese ? '父版本尚未载入' : 'Parent version not loaded')
              : (widget.chinese
                    ? '本轮未修改 Agent 配置'
                    : 'No Agent configuration changes'),
        ),
      );
    }
    final change = diff.changes[selected];
    final colors = Theme.of(context).colorScheme;
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(
            children: [
              Expanded(
                child: SelectableText(
                  title(change),
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              const SizedBox(width: 12),
              Text(
                status(change),
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(color: color(change)),
              ),
            ],
          ),
        ),
        Divider(height: 1, color: colors.outlineVariant),
        Expanded(
          child: Scrollbar(
            controller: _scroll,
            child: SingleChildScrollView(
              key: ValueKey('rsi-diff-content-$selected'),
              controller: _scroll,
              padding: const EdgeInsets.only(top: 8),
              child: _LineDiff(
                key: ValueKey(selected),
                before: change.before,
                after: change.after,
                chinese: widget.chinese,
              ),
            ),
          ),
        ),
      ],
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 640;
        final files = ListView.separated(
          key: const ValueKey('rsi-diff-files'),
          padding: const EdgeInsets.all(8),
          scrollDirection: compact ? Axis.horizontal : Axis.vertical,
          itemCount: diff.changes.length,
          separatorBuilder: (_, index) =>
              SizedBox(width: compact ? 8 : 0, height: compact ? 0 : 4),
          itemBuilder: (context, index) {
            final item = diff.changes[index];
            final tile = ListTile(
              key: ValueKey('rsi-diff-file-$index'),
              selected: selected == index,
              selectedTileColor: colors.primary.withValues(alpha: .1),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 4,
              ),
              leading: Text(
                item.added
                    ? '+'
                    : item.removed
                    ? '−'
                    : 'M',
                style: TextStyle(
                  color: color(item),
                  fontWeight: FontWeight.w600,
                ),
              ),
              title: Text(
                title(item),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              onTap: () => select(index),
            );
            return compact ? SizedBox(width: 220, child: tile) : tile;
          },
        );
        return compact
            ? Column(
                children: [
                  SizedBox(height: 88, child: files),
                  Divider(height: 1, color: colors.outlineVariant),
                  Expanded(child: content),
                ],
              )
            : Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(width: 270, child: files),
                  VerticalDivider(width: 1, color: colors.outlineVariant),
                  Expanded(child: content),
                ],
              );
      },
    );
  }
}

class RsiRoundChanges extends StatelessWidget {
  const RsiRoundChanges({
    required this.run,
    required this.events,
    required this.settings,
    required this.chinese,
    this.diffs,
    this.selectedRound,
    super.key,
  });
  final Map<String, Object?>? run;
  final List<Map<String, Object?>> events;
  final LiquidGlassSettings settings;
  final bool chinese;
  final List<RsiRoundDiff>? diffs;
  final int? selectedRound;
  @override
  Widget build(BuildContext context) {
    final rounds = (diffs ?? collectRsiRoundDiffs(run, events))
        .where((diff) => selectedRound == null || diff.round == selectedRound)
        .toList();
    if (rounds.isEmpty && selectedRound == null) return const SizedBox.shrink();
    return GlassCard(
      width: double.infinity,
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
          if (rounds.isEmpty)
            Text(
              selectedRound == 0
                  ? (chinese ? '基线轮，无进化改动' : 'Baseline · No evolution changes')
                  : (chinese ? '本轮暂无改动记录' : 'No change record for this round'),
            ),
          LayoutBuilder(
            builder: (context, constraints) => Column(
              children: [
                for (final diff in rounds) ...[
                  if (diff != rounds.first) const SizedBox(height: 8),
                  GlassButton.custom(
                    key: ValueKey('rsi-round-diff-${diff.round}'),
                    settings: settings,
                    shape: const LiquidRoundedRectangle(borderRadius: 10),
                    width: constraints.maxWidth,
                    height: 48,
                    onTap: () =>
                        showRsiRoundDiff(context, diff, settings, chinese),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      child: Row(
                        children: [
                          Text(
                            'R${diff.round}',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(fontWeight: FontWeight.w600),
                          ),
                          const SizedBox(width: 16),
                          Text(
                            _status(diff, chinese),
                            style: Theme.of(context).textTheme.labelMedium
                                ?.copyWith(
                                  color: diff.accepted == true
                                      ? Theme.of(context).colorScheme.primary
                                      : diff.accepted == false
                                      ? Theme.of(context).colorScheme.error
                                      : Theme.of(
                                          context,
                                        ).colorScheme.onSurfaceVariant,
                                ),
                          ),
                          const SizedBox(width: 20),
                          Expanded(
                            child: Text(
                              !diff.parentAvailable
                                  ? (chinese ? '父版本尚未载入' : 'Parent not loaded')
                                  : diff.candidateMissing
                                  ? (chinese ? '未生成有效候选' : 'No valid candidate')
                                  : diff.changes.isEmpty
                                  ? (chinese ? '无改动' : 'No changes')
                                  : {
                                      for (final change in diff.changes)
                                        _kind(change.kind, chinese),
                                    }.join(' · '),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: Theme.of(
                                      context,
                                    ).colorScheme.onSurfaceVariant,
                                  ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Icon(
                            CupertinoIcons.chevron_right,
                            size: 14,
                            color: Theme.of(
                              context,
                            ).colorScheme.onSurfaceVariant,
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (diff.rationale.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: SelectableText(diff.rationale),
                    ),
                  ],
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LineDiff extends StatefulWidget {
  const _LineDiff({
    super.key,
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
                  fontFamily: 'monospace',
                  height: 1.6,
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
