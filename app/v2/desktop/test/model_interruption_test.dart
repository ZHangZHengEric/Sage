import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/models.dart';

void main() {
  test('interrupted output retains its state without changing canonical text', () {
    final message = ChatMessage(id: 'partial', role: 'assistant', text: 'partial', interrupted: true);
    final restored = ChatMessage.fromJson(message.toJson());
    expect(restored.interrupted, isTrue);
    expect(restored.text, 'partial');
    expect(restored.streaming, isFalse);
    expect(ChatMessage.fromJson({'id': 'old', 'text': 'answer'}).interrupted, isFalse);
  });
}
