import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/main.dart' show sageGlassRoot;
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';

void main() {
  testWidgets(
    'production root actually installs its standard quality ceiling',
    (tester) async {
      GlassQuality? ceiling;
      await tester.pumpWidget(
        sageGlassRoot(
          MaterialApp(
            home: Builder(
              builder: (context) {
                ceiling = GlassAdaptiveScopeData.maybeOf(
                  context,
                )?.effectiveQuality;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );
      // Scope is intentionally used to verify the production quality ceiling.
    // ignore: experimental_member_use
    expect(find.byType(GlassAdaptiveScope), findsOneWidget);
      expect(ceiling, GlassQuality.standard);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'streaming native surfaces use minimal and completed use standard $brightness',
      (tester) async {
        final tree = {
          'component': 'Card',
          'props': {
            'title': 'Plan',
            'children': [
              {
                'component': 'Input',
                'props': {'name': 'name', 'label': 'Name', 'value': ''},
              },
              {
                'component': 'Metric',
                'props': {'label': 'Same', 'value': '1'},
              },
              {
                'component': 'Accordion',
                'props': {
                  'children': [
                    {
                      'component': 'Section',
                      'props': {
                        'title': 'Details',
                        'children': [
                          {
                            'component': 'Text',
                            'props': {'content': 'Streaming'},
                          },
                        ],
                      },
                    },
                  ],
                },
              },
            ],
          },
        };
        for (final complete in [false, true, false]) {
          await tester.pumpWidget(
            GlassTheme(
              data: GlassThemeData.simple(quality: GlassQuality.premium),
              child: MaterialApp(
                theme: ThemeData(brightness: brightness),
                home: Scaffold(
                  body: SingleChildScrollView(
                    child: OpenUiSurface(
                      surface: {'tree': tree, 'complete': complete},
                    ),
                  ),
                ),
              ),
            ),
          );
          final expected = complete
              ? GlassQuality.standard
              : GlassQuality.minimal;
          expect(
            tester
                .widgetList<GlassCard>(find.byType(GlassCard))
                .map((w) => w.quality),
            everyElement(expected),
          );
          expect(
            tester.widget<GlassTextField>(find.byType(GlassTextField)).quality,
            expected,
          );
          expect(tester.takeException(), isNull);
        }
      },
    );
  }
}
