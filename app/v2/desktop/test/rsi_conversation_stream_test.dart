import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_conversation_stream.dart';

Widget stream(String id, int count) => SizedBox(
  width: 240,
  height: 200,
  child: RsiConversationStream(
    key: ValueKey(id),
    revision: count,
    children: [
      for (var i = 0; i < count; i++)
        SizedBox(height: 48, child: Text('$id message $i')),
    ],
  ),
);

Widget page(int count, {bool reducedMotion = false}) => MaterialApp(
  home: MediaQuery(
    data: MediaQueryData(disableAnimations: reducedMotion),
    child: Scaffold(
      body: Row(children: [stream('left', count), stream('right', count)]),
    ),
  ),
);

ScrollableState scrolling(WidgetTester tester, String id) =>
    tester.state<ScrollableState>(
      find
          .descendant(
            of: find.byKey(ValueKey(id)),
            matching: find.byType(Scrollable),
          )
          .first,
    );

void main() {
  testWidgets('variable height conversation bubbles settle at the actual end', (
    tester,
  ) async {
    Widget variable(int count) => MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 240,
          height: 240,
          child: RsiConversationStream(
            revision: count,
            children: [
              for (var i = 0; i < count; i++)
                SizedBox(
                  height: i % 5 == 0 ? 240 : 48,
                  child: Text('Variable message $i'),
                ),
            ],
          ),
        ),
      ),
    );
    await tester.pumpWidget(variable(30));
    await tester.pumpAndSettle();
    final state = tester.state<ScrollableState>(find.byType(Scrollable).first);
    expect(state.position.extentAfter, lessThan(1));
    expect(find.text('Variable message 29').hitTestable(), findsOneWidget);
    await tester.pumpWidget(variable(45));
    await tester.pumpAndSettle();
    expect(state.position.extentAfter, lessThan(1));
    expect(find.text('Variable message 44').hitTestable(), findsOneWidget);
  });
  testWidgets(
    'rapid updates follow the latest message while earlier scrolling is still active',
    (tester) async {
      await tester.pumpWidget(page(12));
      await tester.pump();
      await tester.pumpWidget(page(14));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pumpWidget(page(18));
      await tester.pumpAndSettle();
      expect(scrolling(tester, 'left').position.extentAfter, lessThan(1));
      await tester.pumpWidget(page(20));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.drag(
        find.byKey(const ValueKey('left')),
        const Offset(0, 150),
      );
      await tester.pumpAndSettle();
      final historyOffset = scrolling(tester, 'left').position.pixels;
      await tester.pumpWidget(page(22));
      await tester.pumpAndSettle();
      expect(
        scrolling(tester, 'left').position.pixels,
        closeTo(historyOffset, 1),
      );
    },
  );
  testWidgets(
    'each conversation follows new messages independently and preserves history reading',
    (tester) async {
      await tester.pumpWidget(page(12));
      await tester.pump();
      expect(scrolling(tester, 'left').position.extentAfter, lessThan(1));
      expect(scrolling(tester, 'right').position.extentAfter, lessThan(1));
      await tester.drag(
        find.byKey(const ValueKey('left')),
        const Offset(0, 160),
      );
      await tester.pumpAndSettle();
      final historyOffset = scrolling(tester, 'left').position.pixels;
      expect(scrolling(tester, 'left').position.extentAfter, greaterThan(24));
      await tester.pumpWidget(page(14));
      await tester.pumpAndSettle();
      expect(
        scrolling(tester, 'left').position.pixels,
        closeTo(historyOffset, 1),
      );
      expect(scrolling(tester, 'right').position.extentAfter, lessThan(1));
      await tester.drag(
        find.byKey(const ValueKey('left')),
        const Offset(0, -1000),
      );
      await tester.pumpAndSettle();
      await tester.pumpWidget(page(16));
      await tester.pumpAndSettle();
      expect(scrolling(tester, 'left').position.extentAfter, lessThan(1));
      expect(scrolling(tester, 'right').position.extentAfter, lessThan(1));
    },
  );

  testWidgets(
    'reduced motion follows immediately and pending callbacks tolerate disposal',
    (tester) async {
      await tester.pumpWidget(page(12, reducedMotion: true));
      await tester.pump();
      await tester.pumpWidget(page(13, reducedMotion: true));
      await tester.pump();
      expect(scrolling(tester, 'left').position.extentAfter, lessThan(1));
      await tester.pumpWidget(page(14));
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
    },
  );
}
