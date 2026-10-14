import '../models.dart';

/// Earlier UI messages in the same run are process artifacts, not final answers.
/// This projection also works for persisted histories without changing sources.
Set<String> supersededOpenUiMessages(List<ChatMessage> messages) {
  final seenRuns = <String>{};
  final hidden = <String>{};
  for (final message in messages.reversed) {
    if (message.role == 'user') {
      seenRuns.clear();
      continue;
    }
    if (message.role != 'assistant' || message.openUiSurfaces.isEmpty) continue;
    final runs = <String>{};
    for (final surface in message.openUiSurfaces) {
      final run = surface['run_id']?.toString() ?? '';
      if (run.isNotEmpty && surface['tree'] is Map) runs.add(run);
    }
    if (runs.isEmpty) continue;
    if (runs.every(seenRuns.contains)) hidden.add(message.id);
    seenRuns.addAll(runs);
  }
  return hidden;
}
