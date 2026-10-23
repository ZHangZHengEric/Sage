import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_transcript.dart';

void main() {
  test('host conversation renders actual messages and tool calls in order', () {
    final messages = rsiTranscript(
      jsonEncode({
        'conversation': [
          {'role': 'user', 'content': 'Please check my order.'},
          {
            'role': 'assistant',
            'tool_calls': [
              {
                'id': 'call',
                'name': 'lookup',
                'arguments': {'order': '1'},
              },
            ],
          },
          {'role': 'tool', 'id': 'call', 'content': 'Order located.'},
          {'role': 'assistant', 'content': 'Your order has shipped.'},
        ],
        'official_reward': {'reward': 1},
      }),
    );
    expect(messages.map((m) => m.role), ['user', 'tool', 'tool', 'assistant']);
    expect(messages.first.text, 'Please check my order.');
    expect(messages[2].text, 'lookup\nOrder located.');
    expect(messages.last.text, 'Your order has shipped.');
    expect(messages.any((m) => m.text.contains('official_reward')), isFalse);
  });
  test('ordinary output and unrelated JSON preserve fallback rendering', () {
    expect(rsiTranscript('plain answer'), isEmpty);
    expect(rsiTranscript('{"result": 3}'), isEmpty);
    expect(
      rsiTranscript(
        '{"conversation":[{"role":"unknown","content":"retain raw"}]}',
      ),
      isEmpty,
    );
  });
}
