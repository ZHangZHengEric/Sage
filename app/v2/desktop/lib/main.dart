import 'dart:async';

import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'src/app.dart';

// Keep the same conservative glass quality ceiling as Yiii on macOS.
// ignore: experimental_member_use
const sageGlassConfig = GlassAdaptiveScopeConfig(
  initialQuality: GlassQuality.standard,
  maxQuality: GlassQuality.standard,
  allowStepUp: false,
);

Future<void> main() async {
  await runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();
      await LiquidGlassWidgets.initialize();
      runApp(
        LiquidGlassWidgets.wrap(
          adaptiveQuality: false,
          adaptiveConfig: sageGlassConfig,
          theme: GlassThemeData.simple(
            blur: 2,
            thickness: 4,
            quality: GlassQuality.standard,
          ),
          child: const SageDesktopV2App(),
        ),
      );
    },
    (error, stackTrace) {
      debugPrint('Unhandled Sage Desktop v2 error: $error\n$stackTrace');
    },
  );
}
