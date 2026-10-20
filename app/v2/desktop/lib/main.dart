import 'dart:async';

import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'src/app.dart';

// Keep a conservative glass quality ceiling on macOS.
// ignore: experimental_member_use
const sageGlassConfig = GlassAdaptiveScopeConfig(
  initialQuality: GlassQuality.standard,
  maxQuality: GlassQuality.standard,
  allowStepUp: false,
);

Widget sageGlassRoot(Widget child) => LiquidGlassWidgets.wrap(
  adaptiveQuality: true,
  adaptiveConfig: sageGlassConfig,
  theme: GlassThemeData.simple(
    blur: 2,
    thickness: 4,
    quality: GlassQuality.standard,
  ),
  child: child,
);

Future<void> main() async {
  await runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();
      await LiquidGlassWidgets.initialize();
      runApp(sageGlassRoot(const SageDesktopV2App()));
    },
    (error, stackTrace) {
      debugPrint('Unhandled Sage Desktop v2 error: $error\n$stackTrace');
    },
  );
}
