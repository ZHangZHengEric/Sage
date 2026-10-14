import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';

// Opt-in: use the actual repaired surface from the live self-check probe.
void main() {
  const path = String.fromEnvironment('SELF_CHECK_LIVE_SURFACE');
  for (final brightness in Brightness.values) {
    testWidgets(
      'real-model repaired calculator remains local $brightness',
      (tester) async {
        final surface = Map<String, Object?>.from(
          jsonDecode(File(path).readAsStringSync()) as Map,
        );
        tester.view.physicalSize = const Size(800, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var submissions = 0;
        await tester.pumpWidget(
          MaterialApp(
            theme: sageDesktopTheme(brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: OpenUiSurface(
                  surface: surface,
                  enabled: true,
                  onSubmit: (_, _) async {
                    submissions++;
                  },
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        String revenue() => tester
            .widget<Text>(find.byKey(const ValueKey('openui-computed:Revenue')))
            .data!;
        expect(revenue(), contains('2500'));
        final field = find.descendant(
          of: find.byKey(const ValueKey('openui-field:cups')),
          matching: find.byType(EditableText),
        );
        await tester.ensureVisible(field);
        await tester.enterText(field, '200');
        await tester.pumpAndSettle();
        expect(revenue(), contains('5000'));
        await tester.enterText(field, '40');
        await tester.pumpAndSettle();
        expect(revenue(), contains('1000'));
        expect(
          submissions,
          0,
          reason: 'Local arithmetic must not submit to an agent',
        );
        expect(tester.takeException(), isNull);
      },
      skip: path.isEmpty,
    );
  }
}
