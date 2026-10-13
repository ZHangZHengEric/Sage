import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';

Map<String, Object?> node(String component, Map<String, Object?> props) => {
  'component': component,
  'props': props,
};

void main() {
  test('fences split across tokens hide source and preserve prose', () {
    const text = 'Before\n```openui\nroot = Text("Hello")\n```\nAfter';
    for (var i = text.indexOf('root'); i <= text.length; i++) {
      final parts = splitOpenUiMessage(text.substring(0, i), streaming: true);
      expect(parts.where((part) => part.blockIndex != null), hasLength(1));
      expect(
        parts
            .where((part) => part.blockIndex == null)
            .map((part) => part.markdown)
            .join(),
        isNot(contains('root =')),
      );
    }
    expect(
      splitOpenUiMessage(
        '````markdown\n```openui\nroot = Text("X")\n```\n````',
      ).where((part) => part.blockIndex != null),
      isEmpty,
    );
    expect(splitOpenUiMessage(text).last.markdown, contains('After'));
  });

  test('surface and draft state survive message persistence', () {
    final message = ChatMessage(
      id: 'm',
      role: 'assistant',
      text: '```openui\nroot = Text("Hi")\n```',
      openUiSurfaces: [
        {
          'message_id': 'm',
          'block_index': 0,
          'surface_id': 'surface',
          'tree': node('Text', {'content': 'Hi'}),
          'draft_values': {'city': 'Shanghai'},
        },
      ],
    );
    expect(
      ChatMessage.fromJson(
        message.toJson(),
      ).openUiSurfaces.single['draft_values'],
      {'city': 'Shanghai'},
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'partial native tree updates before completion in ${brightness.name}',
      (tester) async {
        Future<void> pump(String text, {bool complete = false}) =>
            tester.pumpWidget(
              MaterialApp(
                theme: ThemeData(brightness: brightness),
                home: Scaffold(
                  body: OpenUiSurface(
                    key: const ValueKey('stream'),
                    enabled: complete,
                    surface: {
                      'complete': complete,
                      'tree': node('Card', {
                        'title': 'Trip',
                        'children': [
                          node('Text', {'content': text}),
                          node('Button', {'action': 'go', 'label': 'Continue'}),
                        ],
                      }),
                    },
                    onSubmit: (_, _) async {},
                  ),
                ),
              ),
            );
        await pump('He');
        expect(find.text('He'), findsOneWidget);
        expect(find.byType(GlassCard), findsOneWidget);
        expect(
          tester
              .widget<GlassButton>(
                find.byKey(const ValueKey('openui-action:go')),
              )
              .enabled,
          isFalse,
        );
        await pump('Hello', complete: true);
        expect(find.text('Hello'), findsOneWidget);
        expect(find.text('He'), findsNothing);
        expect(
          tester
              .widget<GlassButton>(
                find.byKey(const ValueKey('openui-action:go')),
              )
              .enabled,
          isTrue,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'failed final validation keeps a disabled preview in ${brightness.name}',
      (tester) async {
        var submitted = 0;
        final tree = node('Card', {
          'title': 'Preview',
          'children': [
            node('Text', {'content': 'Existing content'}),
            node('Button', {'action': 'go', 'label': 'Continue'}),
          ],
        });
        Future<void> pump({bool failed = false}) => tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: OpenUiSurface(
                key: const ValueKey('preview'),
                surface: {
                  'tree': tree,
                  'complete': false,
                  if (failed) 'error': 'Invalid reference',
                },
                enabled: failed,
                onSubmit: (_, _) async {
                  submitted++;
                },
              ),
            ),
          ),
        );
        await pump();
        expect(find.text('Existing content'), findsOneWidget);
        await pump(failed: true);
        expect(find.text('Existing content'), findsOneWidget);
        expect(
          find.text('Generated content failed validation · read-only preview'),
          findsOneWidget,
        );
        final button = find.byKey(const ValueKey('openui-action:go'));
        expect(tester.widget<GlassButton>(button).enabled, isFalse);
        await tester.tap(button);
        expect(submitted, 0);
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'required fields prevent submission and typed state survives tree updates',
    (tester) async {
      var submissions = 0;
      Map<String, Object?>? submitted;
      final surface = {
        'complete': true,
        'tree': node('Stack', {
          'children': [
            node('Input', {
              'name': 'city',
              'label': 'City',
              'value': '',
              'required': true,
            }),
            node('Button', {'action': 'go', 'label': 'Continue'}),
          ],
        }),
      };
      Future<void> pump() => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OpenUiSurface(
              key: const ValueKey('form'),
              surface: surface,
              enabled: true,
              onSubmit: (action, values) async {
                submissions++;
                submitted = values;
              },
            ),
          ),
        ),
      );
      await pump();
      await tester.tap(find.byKey(const ValueKey('openui-action:go')));
      await tester.pump();
      expect(submissions, 0);
      await tester.enterText(
        find.descendant(
          of: find.byKey(const ValueKey('openui-field:city')),
          matching: find.byType(EditableText),
        ),
        'Shanghai',
      );
      await pump();
      expect(find.text('Shanghai'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('openui-action:go')));
      await tester.pump();
      expect(submissions, 1);
      expect(submitted, {'city': 'Shanghai'});
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('streamed defaults advance and user edits survive updates', (
    tester,
  ) async {
    Future<void> pump(String value, bool complete) => tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: OpenUiSurface(
            key: const ValueKey('defaults'),
            enabled: complete,
            surface: {
              'complete': complete,
              'tree': node('Stack', {
                'children': [
                  node('Input', {
                    'name': 'city',
                    'label': 'City',
                    'value': value,
                  }),
                  node('Button', {'action': 'go', 'label': 'Go'}),
                ],
              }),
            },
            onSubmit: (_, _) async {},
          ),
        ),
      ),
    );
    await pump('S', false);
    await pump('Shanghai', true);
    expect(find.text('Shanghai'), findsOneWidget);
    final editable = find.descendant(
      of: find.byKey(const ValueKey('openui-field:city')),
      matching: find.byType(EditableText),
    );
    await tester.enterText(editable, 'Beijing');
    await pump('Shenzhen', true);
    expect(find.text('Beijing'), findsOneWidget);
    expect(find.text('Shenzhen'), findsNothing);
  });
  testWidgets(
    'streaming field name fragments are excluded from submitted values',
    (tester) async {
      Map<String, Object?>? values;
      Future<void> pump(String name, bool complete) => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OpenUiSurface(
              key: const ValueKey('fragments'),
              enabled: complete,
              surface: {
                'complete': complete,
                'tree': node('Stack', {
                  'children': [
                    node('Input', {
                      'name': name,
                      'label': 'City',
                      'value': 'Shanghai',
                    }),
                    node('Button', {'action': 'go', 'label': 'Go'}),
                  ],
                }),
              },
              onSubmit: (_, submitted) async {
                values = submitted;
              },
            ),
          ),
        ),
      );
      await pump('c', false);
      await pump('ci', false);
      await pump('city', true);
      await tester.tap(find.byKey(const ValueKey('openui-action:go')));
      await tester.pump();
      expect(values, {'city': 'Shanghai'});
    },
  );

  testWidgets('select toggle and expand preserve typed state and user intent', (
    tester,
  ) async {
    Map<String, Object?>? values;
    var expanded = 0;
    final surface = {
      'complete': true,
      'tree': node('Card', {
        'title': 'Trip',
        'children': [
          node('Select', {
            'name': 'transport',
            'label': 'Transport',
            'options': ['Train', 'Plane'],
            'value': 'Train',
            'required': true,
          }),
          node('Toggle', {
            'name': 'reimburse',
            'label': 'Reimburse',
            'value': true,
          }),
          node('Button', {'action': 'go', 'label': 'Go'}),
        ],
      }),
    };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: OpenUiSurface(
            surface: surface,
            enabled: true,
            onExpand: () => expanded++,
            onSubmit: (_, submitted) async {
              values = submitted;
            },
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('openui-field:transport')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Plane').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('openui-field:reimburse')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byWidgetPredicate(
        (widget) => widget is GlassButton && widget.label == 'Open in sidebar',
      ),
    );
    await tester.pump();
    expect(expanded, 1);
    await tester.tap(find.byKey(const ValueKey('openui-action:go')));
    await tester.pump();
    expect(values, {'transport': 'Plane', 'reimburse': false});
    expect(tester.takeException(), isNull);
  });
  for (final brightness in Brightness.values) {
    testWidgets(
      'all components handle long content at compact widths in ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final long = List.filled(20, 'Long content 长内容').join(' ');
        final tree = node('Stack', {
          'children': [
            node('Card', {
              'title': long,
              'children': [
                node('Row', {
                  'children': [
                    node('Text', {'content': long}),
                    node('Text', {'content': 'Second'}),
                  ],
                }),
                node('Table', {
                  'columns': List.generate(20, (i) => 'Column $i'),
                  'rows': [List.generate(20, (i) => i), List.filled(20, long)],
                }),
                node('Input', {'name': 'city', 'label': long, 'value': long}),
                node('Select', {
                  'name': 'option',
                  'label': long,
                  'options': [long],
                  'value': long,
                }),
                node('Toggle', {
                  'name': 'enabled',
                  'label': long,
                  'value': true,
                }),
                node('Button', {'action': 'go', 'label': long}),
              ],
            }),
          ],
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: OpenUiSurface(
                  surface: {'complete': true, 'tree': tree},
                  enabled: true,
                  onSubmit: (_, _) async {},
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(GlassTextField), findsOneWidget);
        expect(find.byType(GlassSwitch), findsOneWidget);
        expect(find.byType(DataTable), findsOneWidget);
      },
    );
  }
}
