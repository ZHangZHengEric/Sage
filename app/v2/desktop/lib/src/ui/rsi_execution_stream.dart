import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'tool_activity_presentation.dart';
import 'rsi_transcript.dart';

/// A tool action and its recorded result share one place in the conversation.
class RsiExecutionTool extends StatelessWidget {
  const RsiExecutionTool({
    required this.name,
    required this.arguments,
    required this.result,
    required this.state,
    required this.chinese,
    required this.settings,
    super.key,
  });

  final String name;
  final String arguments;
  final String? result;
  final String state;
  final bool chinese;
  final LiquidGlassSettings settings;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final failed = state == 'failed';
    final color = failed ? colors.error : colors.primary;
    final status = switch (state) {
      'failed' => chinese ? '失败' : 'Failed',
      'completed' => chinese ? '完成' : 'Completed',
      _ => chinese ? '已调用' : 'Called',
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: GlassCard(
        settings: settings,
        useOwnLayer: true,
        padding: EdgeInsets.zero,
        child: ExpansionTile(
          shape: const Border(),
          collapsedShape: const Border(),
          leading: Icon(
            failed ? Icons.error_outline : Icons.build_outlined,
            size: 18,
            color: color,
          ),
          title: Text(localizedToolName(name, chinese ? 'zh' : 'en')),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(status, style: TextStyle(color: color, fontSize: 12)),
              const SizedBox(width: 8),
              const Icon(Icons.expand_more, size: 18),
            ],
          ),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (arguments.isNotEmpty) ...[
              Text(
                chinese ? '参数' : 'Arguments',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              const SizedBox(height: 6),
              SelectableText(arguments, key: const PageStorageKey('arguments')),
            ],
            if (result != null) ...[
              const SizedBox(height: 12),
              Text(
                chinese ? '结果' : 'Result',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              const SizedBox(height: 6),
              SelectableText(result!, key: const PageStorageKey('result')),
            ],
          ],
        ),
      ),
    );
  }
}

/// Deduplicate cumulative resumed-run snapshots while preserving item order.
List<Map<String, Object?>> rsiExecutionEntries(
  Iterable<Map<String, Object?>> turns, {
  bool includeInput = true,
}) {
  final recorded = turns.toList();
  if (!recorded.any((turn) {
    final evidence = turn['evidence'];
    return evidence is Map &&
        evidence['execution_transcript'] is List &&
        (evidence['execution_transcript'] as List).isNotEmpty;
  })) {
    return [];
  }
  final entries = <Map<String, Object?>>[];
  final seen = <String>{};
  final calls = <String, Map<String, Object?>>{};
  for (final turn in recorded) {
    final evidence = turn['evidence'];
    final transcript = evidence is Map
        ? evidence['execution_transcript']
        : null;
    if (transcript is! List || transcript.isEmpty) {
      final output = turn['output']?.toString() ?? '';
      final legacy = rsiTranscript(output);
      if (includeInput &&
          turn['input'] != null &&
          !legacy.any((m) => m.role == 'user')) {
        entries.add({'role': 'user', 'text': turn['input'].toString()});
      }
      if (legacy.isNotEmpty) {
        entries.addAll(legacy.map((m) => {'role': m.role, 'text': m.text}));
      } else if (output.isNotEmpty) {
        entries.add({'role': 'assistant', 'text': output});
      }
      continue;
    }
    if (includeInput &&
        turn['input'] != null &&
        !transcript.whereType<Map>().any((e) => e['role'] == 'user')) {
      entries.add({'role': 'user', 'text': turn['input'].toString()});
    }
    for (final raw in transcript.whereType<Map>()) {
      final entry = Map<String, Object?>.from(raw);
      final id = entry['id']?.toString();
      if (id != null && id != ':' && !seen.add(id)) continue;
      final callId = entry['call_id']?.toString();
      if (entry['kind'] == 'tool_result' && calls.containsKey(callId)) {
        calls[callId]!.addAll({
          'result': [
            entry['text'],
            entry['error'],
          ].whereType<String>().where((s) => s.isNotEmpty).join('\n'),
          'state': entry['state'],
        });
      } else {
        entries.add(entry);
        if (entry['kind'] == 'tool_call' && callId != null) {
          calls[callId] = entry;
        }
      }
    }
  }
  return entries;
}
