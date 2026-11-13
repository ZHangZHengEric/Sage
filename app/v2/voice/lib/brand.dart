import 'package:flutter/material.dart';

const sageVoiceName = 'Sage Voice';
const sageLogoAsset = 'assets/sage_logo.png';
const voiceTitleBarHeight = 32.0;

class SageBrand extends StatelessWidget {
  const SageBrand({super.key, this.size = 25});

  final double size;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Image.asset(sageLogoAsset, width: size, height: size),
      const SizedBox(width: 8),
      const Text(sageVoiceName, style: TextStyle(fontWeight: FontWeight.w600)),
    ],
  );
}
