import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'openui_image_loader.dart';
export 'openui_image_loader.dart' show openUiPublicImageUrl;

/// Anonymous, bounded, DNS-pinned public image reads. No cookies or credentials.
class OpenUiImage extends StatefulWidget {
  const OpenUiImage({
    super.key,
    required this.url,
    required this.alt,
    required this.height,
    required this.ready,
    this.loadBytes,
  });
  final String url, alt;
  final double height;
  final bool ready;
  final Future<Uint8List> Function(String)? loadBytes;
  @override
  State<OpenUiImage> createState() => _OpenUiImageState();
}

class _OpenUiImageState extends State<OpenUiImage> {
  HttpClient? _client;
  Future<Uint8List>? _bytes;
  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(covariant OpenUiImage old) {
    super.didUpdateWidget(old);
    if (old.url != widget.url || old.ready != widget.ready) {
      _client?.close(force: true);
      _start();
    }
  }

  void _start() {
    _bytes = widget.ready
        ? (widget.loadBytes?.call(widget.url) ??
              openUiLoadImage(
                widget.url,
                onClient: (client) => _client = client,
              ))
        : null;
  }

  @override
  void dispose() {
    _client?.close(force: true);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final fallback = ColoredBox(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.image_outlined),
            if (widget.alt.isNotEmpty)
              Flexible(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    widget.alt,
                    textAlign: TextAlign.center,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: SizedBox(
        height: widget.height,
        width: double.infinity,
        child: FutureBuilder<Uint8List>(
          key: ValueKey(widget.url),
          future: _bytes,
          builder: (context, snapshot) => widget.ready && snapshot.hasData
              ? Image.memory(
                  snapshot.data!,
                  fit: BoxFit.cover,
                  semanticLabel: widget.alt,
                  cacheWidth: 1200,
                  errorBuilder: (_, _, _) => fallback,
                )
              : fallback,
        ),
      ),
    );
  }
}
