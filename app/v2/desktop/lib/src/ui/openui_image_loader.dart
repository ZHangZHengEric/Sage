import 'dart:io';
import 'dart:typed_data';

bool openUiPublicImageUrl(Uri uri) =>
    uri.scheme == 'https' &&
    uri.host.contains('.') &&
    uri.userInfo.isEmpty &&
    (!uri.hasPort || uri.port == 443) &&
    ![
      '.local',
      '.localhost',
      '.internal',
      '.test',
    ].any(uri.host.toLowerCase().endsWith) &&
    (InternetAddress.tryParse(uri.host) == null ||
        _publicAddress(InternetAddress.tryParse(uri.host)!));
bool _publicAddress(InternetAddress address) {
  final b = address.rawAddress;
  if (b.length == 4) {
    return b[0] != 0 &&
        b[0] != 10 &&
        b[0] != 127 &&
        b[0] < 224 &&
        !(b[0] == 169 && b[1] == 254) &&
        !(b[0] == 172 && b[1] >= 16 && b[1] <= 31) &&
        !(b[0] == 192 && b[1] == 168) &&
        !(b[0] == 100 && b[1] >= 64 && b[1] <= 127) &&
        !(b[0] == 198 && (b[1] == 18 || b[1] == 19));
  }
  return b.length == 16 &&
      (b[0] & 0xe0) == 0x20 &&
      !(b[0] == 0x20 && b[1] == 1 && b[2] == 0x0d && b[3] == 0xb8);
}

Future<Uint8List> openUiLoadImage(
  String source, {
  void Function(HttpClient)? onClient,
}) async {
  var uri = Uri.parse(source);
  if (!openUiPublicImageUrl(uri)) {
    throw const FormatException('Invalid image URL');
  }
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 8)
    ..findProxy = (_) => 'DIRECT';
  onClient?.call(client);
  client.connectionFactory = (uri, proxyHost, proxyPort) async {
    if (!openUiPublicImageUrl(uri)) {
      throw const FormatException('Private image host');
    }
    final addresses = await InternetAddress.lookup(
      uri.host,
    ).timeout(const Duration(seconds: 8));
    // Transparent proxy DNS can return synthetic 198.18/15 routes for public
    // hostnames. IP literals remain rejected, and TLS verifies the original host.
    final syntheticProxy =
        InternetAddress.tryParse(uri.host) == null &&
        addresses.isNotEmpty &&
        addresses.every((address) {
          final bytes = address.rawAddress;
          return bytes.length == 4 &&
              bytes[0] == 198 &&
              (bytes[1] == 18 || bytes[1] == 19);
        });
    if (addresses.isEmpty ||
        !syntheticProxy &&
            addresses.any((address) => !_publicAddress(address))) {
      throw const FormatException('Private image address');
    }
    final task = await Socket.startConnect(addresses.first, 443);
    final secure = task.socket.then((socket) async {
      try {
        return await SecureSocket.secure(
          socket,
          host: uri.host,
          supportedProtocols: ['http/1.1'],
        );
      } catch (_) {
        socket.destroy();
        rethrow;
      }
    });
    return ConnectionTask.fromSocket(secure, task.cancel);
  };
  try {
    for (var redirect = 0; redirect < 4; redirect++) {
      if (!openUiPublicImageUrl(uri)) {
        throw const FormatException('Invalid image redirect');
      }
      final request = await client
          .getUrl(uri)
          .timeout(const Duration(seconds: 8));
      request.followRedirects = false;
      final response = await request.close().timeout(
        const Duration(seconds: 8),
      );
      if ([301, 302, 303, 307, 308].contains(response.statusCode)) {
        final target = response.headers.value('location');
        if (target == null) {
          throw const FormatException('Missing image redirect');
        }
        uri = uri.resolve(target);
        continue;
      }
      if (response.statusCode != 200 ||
          response.contentLength > 8 * 1024 * 1024 ||
          ![
            'image/png',
            'image/jpeg',
            'image/webp',
            'image/gif',
          ].contains(response.headers.contentType?.mimeType)) {
        throw const FormatException('Unsupported image response');
      }
      final bytes = BytesBuilder(copy: false);
      await for (final part in response.timeout(const Duration(seconds: 8))) {
        if (bytes.length + part.length > 8 * 1024 * 1024) {
          throw const FormatException('Image too large');
        }
        bytes.add(part);
      }
      return bytes.takeBytes();
    }
    throw const FormatException('Too many image redirects');
  } finally {
    client.close(force: true);
  }
}
