import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:webview_all/webview_all.dart' as web;

import '../../state/desktop_plugins.dart';
import '../../state/workspace_controller.dart';
import '../shared/desktop_notice.dart';
import 'workspace_panel_plugin.dart';

String pluginText(BuildContext context, String en, String zh) =>
    Localizations.localeOf(context).languageCode == 'zh' ? zh : en;

IconData pluginIcon(DesktopPlugin plugin) => switch (plugin.icon) {
  'checklist' => CupertinoIcons.checkmark_square,
  'chart' => CupertinoIcons.chart_bar,
  'clock' => CupertinoIcons.clock,
  'folder' => CupertinoIcons.folder,
  'calculator' => CupertinoIcons.number,
  _ => CupertinoIcons.square_grid_2x2,
};

class DesktopPluginPanel extends WorkspacePanelPluginBase {
  const DesktopPluginPanel(
    this.plugin,
    this.controller,
    this.onCollapse,
    this.onMount,
  );

  final DesktopPlugin plugin;
  final WorkspaceController controller;
  final VoidCallback onCollapse;
  final ValueChanged<String> onMount;

  @override
  String get id => plugin.id;

  @override
  IconData get icon => pluginIcon(plugin);

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => plugin.title;

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      DesktopPluginView(
        key: ValueKey(plugin.digest),
        plugin: plugin,
        controller: controller,
        active: panelContext.active,
        onCollapse: onCollapse,
        onMount: () => onMount(plugin.id),
      );
}

class DesktopPluginView extends StatefulWidget {
  const DesktopPluginView({
    super.key,
    required this.plugin,
    required this.controller,
    this.active = true,
    this.onMount,
    this.onCollapse,
    this.preview,
  });

  final DesktopPlugin plugin;
  final WorkspaceController controller;
  final bool active;
  final VoidCallback? onMount;
  final VoidCallback? onCollapse;
  final Map<String, Object?>? preview;

  @override
  State<DesktopPluginView> createState() => _DesktopPluginViewState();
}

class _DesktopPluginViewState extends State<DesktopPluginView> {
  web.WebViewSession? _session;
  web.WebViewController? _view;
  Uri? _entry;
  String _token = '';
  int _generation = 0;
  bool _ready = false;
  bool _busy = false;
  bool _failed = false;
  Timer? _timeout;
  final Map<String, Object?> _previewStorage = {};
  DesktopPlugins get _plugins => widget.controller.desktopPlugins;
  DesktopPlugin get _plugin => widget.plugin;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      widget.onMount?.call();
      unawaited(_load());
    });
  }

  @override
  void didUpdateWidget(DesktopPluginView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active != oldWidget.active) _environmentChanged();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _environmentChanged();
  }

  void _environmentChanged() {
    if (!_ready) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _ready) {
        unawaited(_send({'event': 'environment', 'value': _environment()}));
      }
    });
  }

  Map<String, Object?> _environment() {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    String hex(Color color) =>
        '#${(color.toARGB32() & 0xffffff).toRadixString(16).padLeft(6, '0')}';
    return {
      'theme': theme.brightness.name,
      'locale': Localizations.localeOf(context).toLanguageTag(),
      'visible': widget.active,
      'colors': {
        'surface': hex(colors.surface),
        'text': hex(colors.onSurface),
        'control': hex(colors.surfaceContainer),
        'border': hex(colors.outlineVariant),
        'primary': hex(colors.primary),
      },
    };
  }

  Future<void> _close(web.WebViewSession? session) async {
    try {
      await session?.close();
    } on Object catch (error) {
      debugPrint('Desktop plugin view cleanup failed: $error');
    }
  }

  void _fail(int generation) {
    if (!mounted || generation != _generation) return;
    _generation++;
    _timeout?.cancel();
    final session = _session;
    _session = null;
    setState(() {
      _view = null;
      _ready = false;
      _failed = true;
    });
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => unawaited(_close(session)),
    );
  }

  Future<void> _load() async {
    final generation = ++_generation;
    final random = Random.secure();
    final token = base64UrlEncode(
      List.generate(32, (_) => random.nextInt(256)),
    );
    setState(() {
      _failed = false;
      _ready = false;
      _busy = false;
      _token = token;
    });
    _timeout = Timer(const Duration(seconds: 20), () => _fail(generation));
    try {
      final document =
          widget.preview ??
          await _plugins.api.desktopPluginDocument(_plugin.id, _plugin.digest);
      if (!mounted || generation != _generation) return;
      final assets = (document['assets'] as Map).cast<String, Object?>();
      final entryPath = (document['manifest'] as Map)['entry'] as String;
      final session = await web.WebViewSession.create(
        mode: web.WebViewSessionMode.isolatedIncognito,
        onPermissionRequest: (request) => request.deny(),
      );
      if (!mounted || generation != _generation) {
        await _close(session);
        return;
      }
      if (session == null) {
        throw StateError('Isolated plugin WebView unavailable');
      }
      _session = session;
      final view = session.controller;
      await view.setJavaScriptMode(web.JavaScriptMode.unrestricted);
      // CSP controls resource loads. Block peer connections and DNS prefetch
      // separately so these browser features cannot bypass the HTTPS bridge.
      await view.addUserScript(
        const web.WebViewUserScript(
          source: r'''
        for (const key of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport']) {
          Object.defineProperty(globalThis, key, {value: undefined, configurable: false, writable: false});
        }
      ''',
        ),
      );

      await view.setPopupPolicy(web.WebViewPopupWindowPolicy.deny);
      await view.setContextMenuEnabled(false);
      await view.setFileSelector((_) async => []);
      await view.setOnProcessFailed((_) => _fail(generation));
      late final Uri entry;
      late final Uri base;
      await view.setResourceDelegate(
        web.WebViewResourceDelegate(
          onRequest: (request) {
            final path = request.path.startsWith('/')
                ? request.path.substring(1)
                : request.path;
            final asset = assets[path] as Map?;
            if (asset == null || generation != _generation) return null;
            final mime = asset['type'] as String;
            var bytes = base64Decode(asset['data'] as String);
            if (mime == 'text/html') {
              if (path != entryPath) return null;
              final sdk = view.getResourceUri('__sage/sdk.js');
              final css = view.getResourceUri('__sage/theme.css');
              final html = utf8
                  .decode(bytes)
                  .replaceFirst(
                    RegExp(r'^\s*<!doctype html\s*>', caseSensitive: false),
                    '',
                  );
              bytes = Uint8List.fromList(
                utf8.encode(
                  '''<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src $base; style-src $base 'unsafe-inline'; img-src $base data:; font-src $base; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'">
<link rel="stylesheet" href="$css"><script src="$sdk" data-token="$token"></script>$html''',
                ),
              );
            }
            return web.WebViewResourceResponse.bytes(
              bytes,
              mimeType: mime,
              headers: const {
                'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff',
                'X-DNS-Prefetch-Control': 'off',
                'Referrer-Policy': 'no-referrer',
              },
            );
          },
        ),
      );
      entry = view.getResourceUri(entryPath)!;
      base = view.getResourceUri('')!;
      _entry = entry;
      // Use explicit scheme rules because WebKit rejects an unqualified catch-all.
      final blocked = await view.setContentRules([
        for (final scheme in ['http', 'https', 'ws', 'wss', 'file', 'ftp'])
          web.WebViewContentRule(urlPattern: '$scheme:*'),
        web.WebViewContentRule(
          urlPattern: '$base*',
          action: web.WebViewContentRuleAction.allow,
        ),
      ]);
      if (!blocked) throw StateError('Plugin request isolation unavailable');
      await view.setNavigationDelegate(
        web.NavigationDelegate(
          onNavigationRequest: (request) =>
              request.isMainFrame && request.url == entry.toString() && !_ready
              ? web.NavigationDecision.navigate
              : web.NavigationDecision.prevent,
          onWebResourceError: (error) {
            if (error.isForMainFrame == true) _fail(generation);
          },
        ),
      );
      // WKWebView wraps the navigation delegate when enabling downloads.
      await view.setDownloadDelegate(
        web.WebViewDownloadDelegate(
          onDownloadRequest: (_) => const web.WebViewDownloadDecision.cancel(),
        ),
      );
      await view.addJavaScriptChannel(
        'SagePluginBridge',
        onMessageReceived: (message) {
          if (message.isMainFrame != true ||
              message.sourceUrl != entry.toString()) {
            return;
          }
          unawaited(_receive(message.message, generation));
        },
      );
      if (!mounted || generation != _generation) return;
      setState(() => _view = view);
      await view.loadRequest(entry);
    } on Object catch (error) {
      debugPrint('Desktop plugin ${_plugin.id} failed to load: $error');
      _fail(generation);
    }
  }

  Future<void> _send(Map<String, Object?> response) async {
    final view = _view;
    try {
      if (view != null && await view.currentUrl() == _entry.toString()) {
        await view.runJavaScript(
          'window.__sagePluginReceive?.(${jsonEncode(response)})',
        );
      }
    } on Object catch (error) {
      debugPrint('Desktop plugin response failed: $error');
    }
  }

  Future<void> _receive(String raw, int generation) async {
    if (!mounted || generation != _generation || raw.length > 1500000) return;
    String? id;
    try {
      final request = (jsonDecode(raw) as Map).cast<String, Object?>();
      if (request['token'] != _token || request['version'] != 1) return;
      id = request['id'] as String;
      if (!RegExp(r'^\d{1,12}$').hasMatch(id)) return;
      final method = request['method'] as String;
      final params = (request['params'] as Map).cast<String, Object?>();
      final value = await _dispatch(method, params);
      if (mounted && generation == _generation) {
        await _send({'id': id, 'ok': true, 'value': value});
      }
    } on Object catch (error) {
      if (id != null && mounted && generation == _generation) {
        final message = error is FormatException || error is StateError
            ? error.toString()
            : pluginText(context, 'Plugin action failed', '插件操作失败');
        await _send({'id': id, 'ok': false, 'error': message});
      }
    }
  }

  Future<Object?> _dispatch(String method, Map<String, Object?> params) async {
    if (method == 'ready') {
      _timeout?.cancel();
      if (!_ready) debugPrint('Desktop plugin ${_plugin.id} ready');
      setState(() => _ready = true);
      return _environment();
    }
    if (!_ready) throw StateError('Plugin is not ready');
    if (method == 'collapse') {
      if (widget.active) widget.onCollapse?.call();
      return null;
    }
    if (const {
      'storage.get',
      'storage.set',
      'storage.delete',
    }.contains(method)) {
      final operation = method.split('.').last;
      final key = _string(params, 'key', 128);
      if (widget.preview != null) {
        if (operation == 'get') return _previewStorage[key];
        if (operation == 'delete') _previewStorage.remove(key);
        if (operation == 'set') _previewStorage[key] = params['value'];
        return null;
      }
      return _plugins.api.desktopPluginStorage(_plugin.id, _plugin.digest, {
        'operation': operation,
        'key': key,
        if (operation == 'set') 'value': params['value'],
      });
    }
    if (!widget.active || widget.preview != null || _busy) {
      throw StateError('Plugin action is unavailable');
    }
    if (method == 'notify') {
      DesktopNoticeHost.show(context, message: _string(params, 'message', 300));
      return null;
    }
    _busy = true;
    try {
      return await _privileged(method, params);
    } finally {
      _busy = false;
    }
  }

  static String _string(Map<String, Object?> params, String key, int limit) {
    final value = params[key];
    if (value is! String || value.isEmpty || value.length > limit) {
      throw FormatException('Invalid $key');
    }
    return value;
  }

  Future<Object?> _privileged(
    String method,
    Map<String, Object?> params,
  ) async {
    final capability = switch (method) {
      'context.read' => 'context',
      'file.read' => 'file.read',
      'file.export' => 'file.export',
      'draft.insert' => 'draft',
      'https.request' => 'https',
      _ => throw const FormatException('Unknown plugin method'),
    };
    final endpoint = capability == 'https'
        ? _string(params, 'endpoint', 40)
        : null;
    final payload = {'capability': capability, 'endpoint': endpoint};
    final api = _plugins.api;
    final id = _plugin.id;
    final digest = _plugin.digest;
    final scope = widget.controller.selectedGroup;
    final conversation = widget.controller.composerConversation;
    final status = await api.desktopPluginPermission(id, digest, payload);
    if (!mounted || !widget.active) return null;
    final newPermission = status['allowed'] != true;
    final needsBearer = status['needsBearer'] == true;
    final target = status['endpoint'] as Map?;
    if (newPermission ||
        needsBearer ||
        capability == 'draft' ||
        (capability == 'https' && target?['method'] != 'GET')) {
      final label = switch (capability) {
        'context' => pluginText(
          context,
          'Read project and conversation details',
          '读取项目和对话信息',
        ),
        'file.read' => pluginText(
          context,
          'Read a file you select',
          '读取你选择的文件',
        ),
        'file.export' => pluginText(context, 'Export a file', '导出文件'),
        'draft' => pluginText(context, 'Insert text into your draft', '插入对话草稿'),
        _ => '${target?['method']} ${target?['url']}',
      };
      final confirmed = await showDialog<String>(
        context: context,
        builder: (context) => _PluginPermissionDialog(
          title: _plugin.title,
          label: label,
          needsBearer: needsBearer,
        ),
      );
      if (confirmed == null || !mounted || !widget.active) return null;
      if (newPermission || needsBearer) {
        await api.desktopPluginPermission(id, digest, {
          ...payload,
          if (needsBearer) 'bearer': confirmed,
        }, grant: true);
      }
    }
    if (!mounted || !widget.active) return null;
    switch (capability) {
      case 'context':
        return {
          'workspaceId': scope.workspaceId,
          'workspaceName': scope.name,
          'sessionId': conversation?.sessionId,
        };
      case 'draft':
        if (conversation != widget.controller.composerConversation) return null;
        widget.controller.insertPluginDraft(_string(params, 'text', 16000));
        return true;
      case 'file.read':
        final root = widget.controller.workspaceFilesRoot;
        if (!widget.controller.hasLocalWorkspaceFiles || root.isEmpty) {
          throw StateError('There is no local workspace');
        }
        final file = await openFile(initialDirectory: root);
        if (file == null || !mounted || !widget.active) return null;
        if ((await api.desktopPluginPermission(
              id,
              digest,
              payload,
            ))['allowed'] !=
            true) {
          return null;
        }
        final directory = await Directory(root).resolveSymbolicLinks();
        final selected = await File(file.path).resolveSymbolicLinks();
        final resolvedRoot = Platform.isWindows
            ? directory.toLowerCase()
            : directory;
        final resolvedFile = Platform.isWindows
            ? selected.toLowerCase()
            : selected;
        final prefix = resolvedRoot.endsWith(Platform.pathSeparator)
            ? resolvedRoot
            : '$resolvedRoot${Platform.pathSeparator}';
        if (!resolvedFile.startsWith(prefix)) {
          throw const FormatException('Select a file in the current workspace');
        }
        if (await file.length() > 1024 * 1024) {
          throw const FormatException('Selected file exceeds 1 MiB');
        }
        final data = await File(
          selected,
        ).openRead(0, 1024 * 1024 + 1).expand((part) => part).toList();
        if (data.length > 1024 * 1024) {
          throw const FormatException('Selected file exceeds 1 MiB');
        }
        return {'name': file.name, 'base64': base64Encode(data)};
      case 'file.export':
        final name = _string(params, 'name', 128);
        if (name.contains(RegExp(r'[/\\:\x00-\x1f]')) ||
            name == '.' ||
            name == '..') {
          throw const FormatException('Invalid file name');
        }
        final data = base64Decode(_string(params, 'base64', 1398104));
        final destination = await getSaveLocation(suggestedName: name);
        if (destination == null || !mounted || !widget.active) return null;
        if ((await api.desktopPluginPermission(
              id,
              digest,
              payload,
            ))['allowed'] !=
            true) {
          return null;
        }
        if (!mounted || !widget.active) return null;
        await XFile.fromData(data, name: name).saveTo(destination.path);
        return true;
      case 'https':
        return api.desktopPluginHttps(id, digest, endpoint!, params['body']);
    }
    return null;
  }

  @override
  void dispose() {
    _generation++;
    _timeout?.cancel();
    unawaited(_close(_session));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final view = _view;
    if (_failed) {
      final retry = pluginText(context, 'Retry', '重试');
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(pluginText(context, 'Plugin failed to open', '插件打开失败')),
            const SizedBox(height: 10),
            GlassButton.custom(
              width: 96,
              height: 32,
              label: retry,
              shape: const LiquidRoundedRectangle(borderRadius: 8),
              onTap: _load,
              child: Text(retry),
            ),
          ],
        ),
      );
    }
    return Stack(
      fit: StackFit.expand,
      children: [
        if (view != null) web.WebViewWidget(controller: view),
        if (!_ready)
          ColoredBox(
            color: Theme.of(context).colorScheme.surface,
            child: const Center(child: CupertinoActivityIndicator()),
          ),
      ],
    );
  }
}

class _PluginPermissionDialog extends StatefulWidget {
  const _PluginPermissionDialog({
    required this.title,
    required this.label,
    required this.needsBearer,
  });

  final String title;
  final String label;
  final bool needsBearer;

  @override
  State<_PluginPermissionDialog> createState() =>
      _PluginPermissionDialogState();
}

class _PluginPermissionDialogState extends State<_PluginPermissionDialog> {
  final _token = TextEditingController();

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final allow = pluginText(context, 'Allow', '允许');
    return AlertDialog(
      title: Text(widget.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.label),
          if (widget.needsBearer) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _token,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(
                labelText: pluginText(context, 'API token', 'API 令牌'),
              ),
              onChanged: (_) => setState(() {}),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(pluginText(context, 'Cancel', '取消')),
        ),
        GlassButton.custom(
          width: 88,
          height: 34,
          label: allow,
          shape: const LiquidRoundedRectangle(borderRadius: 8),
          enabled: !widget.needsBearer || _token.text.trim().isNotEmpty,
          onTap: () => Navigator.pop(context, _token.text.trim()),
          child: Text(allow),
        ),
      ],
    );
  }
}
