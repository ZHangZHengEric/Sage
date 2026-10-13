import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/ui/openui_message_visibility.dart';

ChatMessage ui(String id, String run, {bool failed = false}) => ChatMessage(
  id: id,
  role: 'assistant',
  text: 'UI',
  openUiSurfaces: [
    {
      'run_id': run,
      'block_index': 0,
      if (failed) 'error': 'invalid',
      'tree': {
        'component': 'Deck',
        'props': {'title': id},
      },
    },
  ],
);
void main() {
  test(
    'all intermediate UI messages move to process, including valid versions',
    () {
      final messages = [
        ui('a', 'run', failed: true),
        ui('b', 'run'),
        ui('c', 'run'),
      ];
      expect(supersededOpenUiMessages(messages), {'a', 'b'});
      expect(
        supersededOpenUiMessages(
          messages.map((m) => ChatMessage.fromJson(m.toJson())).toList(),
        ),
        {'a', 'b'},
      );
    },
  );
  test(
    'different runs and user turns stay separate; unparsed updates do not replace previews',
    () {
      expect(
        supersededOpenUiMessages([ui('a', 'one'), ui('b', 'two')]),
        isEmpty,
      );
      expect(
        supersededOpenUiMessages([
          ui('a', 'run'),
          ChatMessage(id: 'u', role: 'user', text: 'next'),
          ui('b', 'run'),
        ]),
        isEmpty,
      );
      expect(
        supersededOpenUiMessages([
          ui('a', 'run'),
          ChatMessage(
            id: 'b',
            role: 'assistant',
            text: '',
            openUiSurfaces: [
              {'run_id': 'run', 'tree': null},
            ],
          ),
        ]),
        isEmpty,
      );
      expect(supersededOpenUiMessages([ui('a', ''), ui('b', '')]), isEmpty);
    },
  );
}
