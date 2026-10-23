import 'dart:convert';

/// Decode a host-recorded conversation without exposing its envelope as prose.
/// Ordinary outputs and unrelated JSON retain their original rendering.
List<({String role, String text})> rsiTranscript(String source) {
  Object? decoded;
  try {
    decoded = jsonDecode(source);
  } on FormatException {
    return [];
  }
  final messages = decoded is Map ? decoded['conversation'] : null;
  if (messages is! List) return [];
  final result = <({String role, String text})>[];
  final toolNames = <String, String>{};
  for (final message in messages.whereType<Map>()) {
    final role = message['role']?.toString() ?? '';
    if (!const {'user', 'assistant', 'tool'}.contains(role)) return [];
    final content = message['content'];
    final text = content is String
        ? content
        : content is List
        ? content
              .whereType<Map>()
              .map((block) => block['text'] ?? '')
              .join('\n')
        : '';
    if (text.trim().isNotEmpty) {
      final name = role == 'tool' ? toolNames[message['id']] : null;
      result.add((role: role, text: name == null ? text : '$name\n$text'));
    }
    for (final call
        in (message['tool_calls'] is List
                ? message['tool_calls'] as List
                : const [])
            .whereType<Map>()) {
      final name = call['name']?.toString() ?? '';
      if (name.isEmpty) continue;
      toolNames[call['id']?.toString() ?? ''] = name;
      result.add((
        role: 'tool',
        text: '$name\n${jsonEncode(call['arguments'] ?? {})}',
      ));
    }
  }
  return result;
}
