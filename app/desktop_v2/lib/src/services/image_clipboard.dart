import 'package:flutter/services.dart';

/// Reads images only in response to an explicit paste operation.
class ImageClipboard {
  static const channel = MethodChannel('sage_desktop_v2/image_clipboard');

  static Future<Uint8List?> readPng() async {
    try {
      return await channel.invokeMethod<Uint8List>('readImage');
    } on MissingPluginException {
      // Platforms without an image bridge retain normal text paste.
      return null;
    }
  }
}
