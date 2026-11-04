// ignore_for_file: invalid_use_of_internal_member

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_highlighting/themes/github-dark.dart';
import 'package:flutter_highlighting/themes/github.dart';
import 'package:flutter_html/flutter_html.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:highlighting/highlighting.dart' as syntax;
import 'package:webview_flutter/webview_flutter.dart';

import '../localization/app_localizations.dart';
import '../models.dart';

enum WorkspaceFilePreviewMode { rendered, source }

class WorkspaceFilePreview extends StatelessWidget {
  const WorkspaceFilePreview({
    required this.node,
    required this.content,
    required this.onReferenceSelection,
    this.mode = WorkspaceFilePreviewMode.rendered,
    super.key,
  });

  final WorkspaceFileNode? node;
  final WorkspaceFileContent? content;
  final ValueChanged<String> onReferenceSelection;
  final WorkspaceFilePreviewMode mode;

  @override
  Widget build(BuildContext context) {
    final node = this.node;
    if (node == null) {
      return Center(
        key: const ValueKey('file-preview-empty'),
        child: Icon(
          CupertinoIcons.doc_text_search,
          size: 28,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      );
    }

    final content = this.content;
    if (content == null) {
      return const Center(child: CupertinoActivityIndicator());
    }

    final text = _decodeText(content);
    final renderable = text != null && _isRenderable(node.name);
    final effectiveMode = renderable ? mode : WorkspaceFilePreviewMode.source;

    return SizedBox.expand(
      key: ValueKey('file-preview:${node.path}'),
      child: _PreviewContent(
        node: node,
        content: content,
        text: text,
        mode: effectiveMode,
        onReferenceSelection: onReferenceSelection,
      ),
    );
  }
}

class _PreviewContent extends StatelessWidget {
  const _PreviewContent({
    required this.node,
    required this.content,
    required this.text,
    required this.mode,
    required this.onReferenceSelection,
  });

  final WorkspaceFileNode node;
  final WorkspaceFileContent content;
  final String? text;
  final WorkspaceFilePreviewMode mode;
  final ValueChanged<String> onReferenceSelection;

  @override
  Widget build(BuildContext context) {
    if (_isRasterImage(node.name, content.mediaType)) {
      return InteractiveViewer(
        key: const ValueKey('file-preview-image'),
        child: Center(child: Image.memory(content.bytes, fit: BoxFit.contain)),
      );
    }

    final source = text;
    if (source == null) {
      return Center(
        key: const ValueKey('file-preview-unsupported'),
        child: Icon(
          CupertinoIcons.doc,
          size: 30,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      );
    }

    if (mode == WorkspaceFilePreviewMode.rendered && _isMarkdown(node.name)) {
      return SingleChildScrollView(
        key: const ValueKey('file-preview-rendered'),
        padding: const EdgeInsets.fromLTRB(24, 18, 24, 28),
        child: _ReferenceableMarkdown(
          data: source,
          onReferenceSelection: onReferenceSelection,
        ),
      );
    }

    if (mode == WorkspaceFilePreviewMode.rendered &&
        workspaceFileIsHtml(node.name)) {
      if (WebViewPlatform.instance != null) {
        return _InteractiveHtmlPreview(
          key: ValueKey('file-preview-webview:${node.path}'),
          source: source,
          onReferenceSelection: onReferenceSelection,
        );
      }
      return _StaticHtmlPreview(
        key: const ValueKey('file-preview-rendered'),
        source: source,
        onReferenceSelection: onReferenceSelection,
      );
    }

    return _CodePreview(
      key: const ValueKey('file-preview-source'),
      source: _formattedSource(source, node.name),
      languageId: _languageId(node.name),
      onReferenceSelection: onReferenceSelection,
    );
  }
}

class _InteractiveHtmlPreview extends StatefulWidget {
  const _InteractiveHtmlPreview({
    required this.source,
    required this.onReferenceSelection,
    super.key,
  });

  final String source;
  final ValueChanged<String> onReferenceSelection;

  @override
  State<_InteractiveHtmlPreview> createState() =>
      _InteractiveHtmlPreviewState();
}

class _InteractiveHtmlPreviewState extends State<_InteractiveHtmlPreview> {
  late final WebViewController _controller;
  var _loading = true;
  String? _loadError;
  String _selection = '';
  Future<void> _updates = Future.value();

  @override
  void initState() {
    super.initState();
    _controller =
        WebViewController(onPermissionRequest: (request) => request.deny())
          ..setJavaScriptMode(JavaScriptMode.unrestricted)
          ..addJavaScriptChannel(
            'SagePreviewSelection',
            onMessageReceived: (message) {
              if (!mounted) return;
              final selection = message.message.trim();
              if (selection == _selection) return;
              setState(() => _selection = selection);
            },
          )
          ..setNavigationDelegate(
            NavigationDelegate(
              onPageStarted: (_) {
                if (!mounted) return;
                setState(() {
                  _loading = true;
                  _loadError = null;
                });
              },
              onPageFinished: (_) {
                if (!mounted) return;
                setState(() => _loading = false);
              },
              onWebResourceError: (error) {
                if (!mounted || error.isForMainFrame == false) return;
                setState(() {
                  _loading = false;
                  _loadError = error.description;
                });
              },
              onNavigationRequest: (request) {
                if (!request.isMainFrame ||
                    request.url == 'about:blank' ||
                    request.url.startsWith('data:text/html')) {
                  return NavigationDecision.navigate;
                }
                return NavigationDecision.prevent;
              },
            ),
          );
    unawaited(_load());
  }

  @override
  void didUpdateWidget(covariant _InteractiveHtmlPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    final next = widget.source;
    if (oldWidget.source != next) {
      _updates = _updates.then((_) => _update(oldWidget.source, next));
    }
  }

  Future<void> _update(String previous, String next) async {
    if (!mounted) return;
    if (!_loading &&
        _loadError == null &&
        previous.contains('data-sage-live-region') &&
        next.contains('data-sage-live-region')) {
      try {
        final arguments = jsonEncode([previous, next]);
        final applied = await _controller.runJavaScriptReturningResult(
          '($_liveRegionUpdate)(...$arguments)',
        );
        if (applied == true || applied == 'true') return;
      } on Object {
        // A navigated or unavailable WebView needs a complete document load.
      }
    }
    if (mounted) await _load(next);
  }

  Future<void> _load([String? source]) async {
    if (mounted) {
      setState(() {
        _loading = true;
        _loadError = null;
        _selection = '';
      });
    }
    try {
      await _controller.loadHtmlString(
        workspaceInteractiveHtmlDocument(source ?? widget.source),
      );
    } on Object catch (exception) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = exception.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final error = _loadError;
    if (error != null) {
      return _StaticHtmlPreview(
        key: const ValueKey('file-preview-rendered'),
        source: widget.source,
        onReferenceSelection: widget.onReferenceSelection,
      );
    }
    return Stack(
      key: const ValueKey('file-preview-rendered'),
      fit: StackFit.expand,
      children: [
        WebViewWidget(
          key: const ValueKey('file-preview-interactive-html'),
          controller: _controller,
        ),
        if (_loading)
          const Center(
            child: CupertinoActivityIndicator(
              key: ValueKey('file-preview-webview-loading'),
            ),
          ),
        if (_selection.isNotEmpty)
          Positioned(
            right: 18,
            bottom: 18,
            child: FilledButton.tonalIcon(
              key: const ValueKey('file-preview-webview-reference'),
              onPressed: () => widget.onReferenceSelection(_selection),
              icon: const Icon(CupertinoIcons.at, size: 15),
              label: Text(context.l10n.text('workspace.referenceSelection')),
            ),
          ),
      ],
    );
  }
}

class _StaticHtmlPreview extends StatelessWidget {
  const _StaticHtmlPreview({
    required this.source,
    required this.onReferenceSelection,
    super.key,
  });

  final String source;
  final ValueChanged<String> onReferenceSelection;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
      child: _ReferenceableSelectionArea(
        key: const ValueKey('file-preview-html-selection'),
        onReferenceSelection: onReferenceSelection,
        child: Html(
          data: source,
          shrinkWrap: true,
          doNotRenderTheseTags: const {
            'script',
            'iframe',
            'object',
            'embed',
            'form',
            'input',
            'button',
            'textarea',
            'select',
          },
          style: {
            'body': Style(
              margin: Margins.zero,
              color: Theme.of(context).colorScheme.onSurface,
              backgroundColor: Colors.transparent,
            ),
          },
        ),
      ),
    );
  }
}

// Opt-in content regions keep their live elements (and their runtime state).
// The document outside those regions must stay identical.
const _liveRegionUpdate = r'''
(previous, next) => {
  const marker = '[data-sage-live-region]';
  const parse = source => new DOMParser().parseFromString(source, 'text/html');
  const collect = doc => {
    const regions = new Map();
    for (const element of doc.querySelectorAll(marker)) {
      const id = element.dataset.sageLiveRegion;
      if (!id || regions.has(id) || element.parentElement.closest(marker)) return null;
      regions.set(id, element);
    }
    return regions;
  };
  const before = parse(previous);
  const after = parse(next);
  const oldRegions = collect(before);
  const newRegions = collect(after);
  const liveRegions = collect(document);
  if (!oldRegions?.size || !newRegions || !liveRegions ||
      oldRegions.size !== newRegions.size || oldRegions.size !== liveRegions.size) return false;

  const patches = [];
  for (const [id, old] of oldRegions) {
    const replacement = newRegions.get(id);
    const live = liveRegions.get(id);
    if (!replacement || !live || live.tagName !== old.tagName) return false;
    if (old.innerHTML !== replacement.innerHTML) {
      if (replacement.querySelector('script, style, link, iframe, object, embed, base, meta')) return false;
      if (live.contains(document.activeElement)) return false;
      patches.push([live, [...replacement.childNodes]]);
    }
    old.replaceChildren();
    replacement.replaceChildren();
  }
  if (before.documentElement.outerHTML !== after.documentElement.outerHTML ||
      before.doctype?.name !== after.doctype?.name) return false;

  const x = window.scrollX;
  const y = window.scrollY;
  const animate = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  for (const [live, children] of patches) {
    live.replaceChildren(...children);
    if (animate && !live.hidden) {
      const rect = live.getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < window.innerHeight) {
        live.animate([{opacity: 0.76}, {opacity: 1}], {duration: 180});
      }
    }
  }
  window.scrollTo({left: x, top: y, behavior: 'instant'});
  return true;
}
''';

const _interactiveHtmlSecurity = '''
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline' data:; script-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
''';

const _interactiveHtmlSelectionBridge = r'''
<script>
(() => {
  let lastSelection = '';
  const reportSelection = () => {
    const selection = String(window.getSelection ? window.getSelection() : '').trim();
    if (selection === lastSelection) return;
    lastSelection = selection;
    if (window.SagePreviewSelection) {
      window.SagePreviewSelection.postMessage(selection);
    }
  };
  document.addEventListener('selectionchange', () => setTimeout(reportSelection, 0));
  document.addEventListener('mouseup', reportSelection);
  document.addEventListener('keyup', reportSelection);
})();
</script>
''';

String workspaceInteractiveHtmlDocument(String source) {
  final head = RegExp(
    r'<head(?:\s[^>]*)?>',
    caseSensitive: false,
  ).firstMatch(source);
  var document = source;
  if (head != null) {
    document = source.replaceRange(
      head.end,
      head.end,
      _interactiveHtmlSecurity,
    );
  } else {
    final html = RegExp(
      r'<html(?:\s[^>]*)?>',
      caseSensitive: false,
    ).firstMatch(source);
    if (html != null) {
      document = source.replaceRange(
        html.end,
        html.end,
        '<head>$_interactiveHtmlSecurity</head>',
      );
    } else {
      document =
          '''<!doctype html><html><head>
$_interactiveHtmlSecurity
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body>$source</body></html>''';
    }
  }
  final bodyMatches = RegExp(
    r'</body\s*>',
    caseSensitive: false,
  ).allMatches(document);
  final bodyEnd = bodyMatches.isEmpty ? null : bodyMatches.last;
  if (bodyEnd == null) return '$document$_interactiveHtmlSelectionBridge';
  return document.replaceRange(
    bodyEnd.start,
    bodyEnd.start,
    _interactiveHtmlSelectionBridge,
  );
}

class _ReferenceableMarkdown extends StatelessWidget {
  const _ReferenceableMarkdown({
    required this.data,
    required this.onReferenceSelection,
  });

  final String data;
  final ValueChanged<String> onReferenceSelection;

  @override
  Widget build(BuildContext context) {
    return _ReferenceableSelectionArea(
      key: const ValueKey('file-preview-markdown-selection'),
      onReferenceSelection: onReferenceSelection,
      child: MarkdownBody(data: data),
    );
  }
}

class _ReferenceableSelectionArea extends StatefulWidget {
  const _ReferenceableSelectionArea({
    required this.child,
    required this.onReferenceSelection,
    super.key,
  });

  final Widget child;
  final ValueChanged<String> onReferenceSelection;

  @override
  State<_ReferenceableSelectionArea> createState() =>
      _ReferenceableSelectionAreaState();
}

class _ReferenceableSelectionAreaState
    extends State<_ReferenceableSelectionArea> {
  String _selection = '';

  @override
  Widget build(BuildContext context) {
    return SelectionArea(
      onSelectionChanged: (content) => _selection = content?.plainText ?? '',
      contextMenuBuilder: (context, selectableRegionState) {
        final items = List<ContextMenuButtonItem>.of(
          selectableRegionState.contextMenuButtonItems,
        );
        if (_selection.trim().isNotEmpty) {
          items.add(
            ContextMenuButtonItem(
              label: context.l10n.text('workspace.referenceSelection'),
              onPressed: () {
                widget.onReferenceSelection(_selection);
                selectableRegionState.hideToolbar();
              },
            ),
          );
        }
        return AdaptiveTextSelectionToolbar.buttonItems(
          anchors: selectableRegionState.contextMenuAnchors,
          buttonItems: items,
        );
      },
      child: widget.child,
    );
  }
}

class _CodePreview extends StatelessWidget {
  const _CodePreview({
    required this.source,
    required this.languageId,
    required this.onReferenceSelection,
    super.key,
  });

  final String source;
  final String? languageId;
  final ValueChanged<String> onReferenceSelection;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final lineCount = '\n'.allMatches(source).length + 1;
    final numbers = [
      for (var index = 1; index <= lineCount; index++) '$index',
    ].join('\n');
    final baseStyle = TextStyle(
      fontFamily: 'Menlo',
      fontSize: 11.5,
      height: 1.55,
      color: colors.onSurface,
    );
    final spans = _highlightSpans(
      source,
      languageId,
      Theme.of(context).brightness,
    );

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(0, 10, 24, 24),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              constraints: const BoxConstraints(minWidth: 48),
              padding: const EdgeInsets.only(right: 12),
              child: Text(
                numbers,
                textAlign: TextAlign.right,
                style: baseStyle.copyWith(
                  color: colors.onSurfaceVariant.withValues(alpha: 0.66),
                ),
              ),
            ),
            Container(
              width: 1,
              height: max(24, lineCount * 17.8),
              color: colors.outlineVariant,
            ),
            const SizedBox(width: 14),
            _ReferenceableSelectionArea(
              key: const ValueKey('file-preview-source-selection'),
              onReferenceSelection: onReferenceSelection,
              child: Text.rich(TextSpan(style: baseStyle, children: spans)),
            ),
          ],
        ),
      ),
    );
  }
}

List<InlineSpan> _highlightSpans(
  String source,
  String? languageId,
  Brightness brightness,
) {
  if (languageId == null) return [TextSpan(text: source)];
  try {
    final theme = brightness == Brightness.dark ? githubDarkTheme : githubTheme;
    final nodes =
        syntax.highlight
            .highlight(languageId, source.replaceAll('\t', '  '), true)
            .nodes ??
        const <syntax.Node>[];
    return _convertNodes(nodes, theme);
  } on Object {
    return [TextSpan(text: source)];
  }
}

List<InlineSpan> _convertNodes(
  List<syntax.Node> nodes,
  Map<String, TextStyle> theme,
) => [
  for (final node in nodes)
    if (node.value != null)
      TextSpan(text: node.value, style: theme[node.className])
    else
      TextSpan(
        style: theme[node.className],
        children: _convertNodes(node.children, theme),
      ),
];

String? _decodeText(WorkspaceFileContent content) {
  if (!content.isText &&
      !content.mediaType.contains('xml') &&
      !content.mediaType.contains('javascript')) {
    return null;
  }
  return utf8.decode(content.bytes, allowMalformed: true);
}

String _formattedSource(String source, String name) {
  final extension = _extension(name);
  if (extension != 'json') return source;
  try {
    return const JsonEncoder.withIndent('  ').convert(jsonDecode(source));
  } on Object {
    return source;
  }
}

bool _isRenderable(String name) =>
    _isMarkdown(name) || workspaceFileIsHtml(name);

bool workspaceFileSupportsRenderedPreview(String name) => _isRenderable(name);

bool _isMarkdown(String name) =>
    const {'md', 'markdown', 'mdown'}.contains(_extension(name));

bool workspaceFileIsHtml(String name) =>
    const {'html', 'htm'}.contains(_extension(name));

bool _isRasterImage(String name, String mediaType) {
  if (!mediaType.startsWith('image/')) return false;
  return const {
    'png',
    'jpg',
    'jpeg',
    'gif',
    'webp',
    'bmp',
  }.contains(_extension(name));
}

String _extension(String name) {
  final lower = name.toLowerCase();
  final index = lower.lastIndexOf('.');
  return index < 0 ? lower : lower.substring(index + 1);
}

String? _languageId(String name) {
  final lower = name.toLowerCase();
  if (lower == 'dockerfile') return 'dockerfile';
  return switch (_extension(name)) {
    'py' => 'python',
    'dart' => 'dart',
    'js' || 'mjs' || 'cjs' || 'jsx' => 'javascript',
    'ts' || 'tsx' => 'typescript',
    'json' || 'jsonl' => 'json',
    'yaml' || 'yml' => 'yaml',
    'md' || 'markdown' || 'mdown' => 'markdown',
    'html' || 'htm' || 'xml' || 'svg' => 'xml',
    'css' || 'scss' => 'css',
    'sh' || 'bash' || 'zsh' => 'bash',
    'sql' => 'sql',
    'java' => 'java',
    'kt' || 'kts' => 'kotlin',
    'swift' => 'swift',
    'go' => 'go',
    'rs' => 'rust',
    'c' || 'h' => 'c',
    'cc' || 'cpp' || 'cxx' || 'hpp' => 'cpp',
    'cs' => 'csharp',
    'rb' => 'ruby',
    'php' => 'php',
    'diff' || 'patch' => 'diff',
    _ => null,
  };
}
