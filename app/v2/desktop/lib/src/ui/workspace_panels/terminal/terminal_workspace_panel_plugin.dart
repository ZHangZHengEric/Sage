import 'dart:async';
import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:xterm/xterm.dart';

import '../../../localization/app_localizations.dart';
import '../../../services/terminal_service.dart';
import '../workspace_panel_plugin.dart';

class TerminalWorkspacePanelPlugin extends WorkspacePanelPluginBase {
  const TerminalWorkspacePanelPlugin();

  static const pluginId = 'sage.workspace.terminal';

  @override
  String get id => pluginId;

  @override
  IconData get icon => CupertinoIcons.chevron_left_slash_chevron_right;

  @override
  bool get initiallyOpen => true;

  @override
  bool get singleton => false;

  @override
  WorkspacePanelSizing get sizing => const WorkspacePanelSizing(
    minWidthFraction: 0.34,
    preferredWidthFraction: 0.48,
    maxWidthFraction: 0.68,
    compactHeightFraction: 0.48,
  );

  @override
  bool supports(WorkspacePanelServices services) =>
      services.maybeRead<TerminalService>() != null &&
      (services.maybeRead<WorkspacePanelSelection>()?.agentId.isNotEmpty ??
          false);

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) {
    final base = context.l10n.text('workspace.terminal');
    return instance == null ? base : '$base ${instance.displayIndex}';
  }

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      _TerminalWorkspacePanel(panelContext: panelContext);
}

enum _TerminalStatus { starting, running, completed, failed }

class _TerminalWorkspacePanel extends StatefulWidget {
  const _TerminalWorkspacePanel({required this.panelContext});

  final WorkspacePanelContext panelContext;

  @override
  State<_TerminalWorkspacePanel> createState() =>
      _TerminalWorkspacePanelState();
}

class _TerminalWorkspacePanelState extends State<_TerminalWorkspacePanel> {
  late Terminal _terminal;
  final FocusNode _focusNode = FocusNode();
  StreamSubscription<TerminalEvent>? _events;
  Timer? _resizeTimer;
  TerminalSessionInfo? _session;
  _TerminalStatus _status = _TerminalStatus.starting;
  String? _error;
  int _columns = 100;
  int _rows = 30;
  int _lastSequence = 0;
  int _generation = 0;
  int _reconnectAttempts = 0;
  Future<void> _inputTail = Future<void>.value();

  TerminalService get _service =>
      widget.panelContext.services.read<TerminalService>();

  WorkspacePanelSelection get _selection =>
      widget.panelContext.services.read<WorkspacePanelSelection>();

  @override
  void initState() {
    super.initState();
    _terminal = _createTerminal();
    unawaited(_start());
  }

  @override
  void didUpdateWidget(covariant _TerminalWorkspacePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!oldWidget.panelContext.active && widget.panelContext.active) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focusNode.requestFocus();
      });
    }
  }

  @override
  void dispose() {
    _generation += 1;
    _resizeTimer?.cancel();
    unawaited(_events?.cancel());
    final sessionId = _session?.sessionId;
    if (sessionId != null) unawaited(_service.close(sessionId));
    _focusNode.dispose();
    super.dispose();
  }

  Terminal _createTerminal() => Terminal(
    maxLines: 10000,
    platform: switch (defaultTargetPlatform) {
      TargetPlatform.macOS => TerminalTargetPlatform.macos,
      TargetPlatform.linux => TerminalTargetPlatform.linux,
      TargetPlatform.windows => TerminalTargetPlatform.windows,
      TargetPlatform.iOS => TerminalTargetPlatform.ios,
      TargetPlatform.android => TerminalTargetPlatform.android,
      TargetPlatform.fuchsia => TerminalTargetPlatform.fuchsia,
    },
    onOutput: _handleInput,
    onResize: _handleResize,
  );

  Future<void> _start() async {
    final generation = ++_generation;
    _resizeTimer?.cancel();
    await _events?.cancel();
    final previousSession = _session?.sessionId;
    _session = null;
    if (previousSession != null) {
      try {
        await _service.close(previousSession);
      } on Object {
        // The sidecar may already have reaped an exited session.
      }
    }
    if (!mounted || generation != _generation) return;
    setState(() {
      _terminal = _createTerminal();
      _status = _TerminalStatus.starting;
      _error = null;
      _lastSequence = 0;
      _reconnectAttempts = 0;
    });
    try {
      final selection = _selection;
      final session = await _service.create(
        agentId: selection.agentId,
        workspaceId: selection.workspaceId,
        columns: _columns,
        rows: _rows,
      );
      if (!mounted || generation != _generation) {
        await _service.close(session.sessionId);
        return;
      }
      setState(() {
        _session = session;
        _status = _TerminalStatus.running;
      });
      _subscribe(generation);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && widget.panelContext.active) _focusNode.requestFocus();
      });
    } on Object catch (exception) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _status = _TerminalStatus.failed;
        _error = exception.toString();
      });
      _terminal.write('\r\n[${exception.toString()}]\r\n');
    }
  }

  void _subscribe(int generation) {
    final session = _session;
    if (session == null) return;
    _events = _service
        .events(session.sessionId, afterSequence: _lastSequence)
        .listen(
          (event) => _handleEvent(event, generation),
          onError: (Object error, StackTrace stackTrace) =>
              _handleStreamError(error, generation),
        );
  }

  void _handleEvent(TerminalEvent event, int generation) {
    if (!mounted || generation != _generation) return;
    if (event is TerminalOverflowEvent) {
      // Do not advance the cursor: the overflow sequence is the producer's
      // current position, not the last event this subscriber consumed.
      _handleStreamError(
        StateError('Terminal output subscriber fell behind; reconnecting.'),
        generation,
      );
      return;
    }
    _lastSequence = event.sequence;
    _reconnectAttempts = 0;
    switch (event) {
      case TerminalOutputEvent(:final bytes):
        _terminal.write(utf8.decode(bytes, allowMalformed: true));
      case TerminalExitedEvent(:final exitCode):
        _terminal.write('\r\n[process exited with code $exitCode]\r\n');
        setState(() {
          _status = exitCode == 0
              ? _TerminalStatus.completed
              : _TerminalStatus.failed;
        });
      case TerminalFailedEvent(:final message):
        _terminal.write('\r\n[$message]\r\n');
        setState(() {
          _status = _TerminalStatus.failed;
          _error = message;
        });
      case TerminalOverflowEvent():
        // Handled before advancing the replay cursor above.
        return;
    }
  }

  void _handleStreamError(Object error, int generation) {
    if (!mounted || generation != _generation || _session == null) return;
    if (_reconnectAttempts < 3 && _status == _TerminalStatus.running) {
      final delay = Duration(milliseconds: 200 * (1 << _reconnectAttempts));
      _reconnectAttempts += 1;
      Future<void>.delayed(delay, () {
        if (mounted && generation == _generation) _subscribe(generation);
      });
      return;
    }
    setState(() {
      _status = _TerminalStatus.failed;
      _error = error.toString();
    });
  }

  void _handleInput(String data) {
    final sessionId = _session?.sessionId;
    if (sessionId == null || _status != _TerminalStatus.running) return;
    _inputTail = _inputTail
        .then((_) => _service.write(sessionId, data))
        .onError((Object error, StackTrace stackTrace) {
          if (mounted) setState(() => _error = error.toString());
        });
  }

  void _handleResize(int columns, int rows, int pixelWidth, int pixelHeight) {
    if (columns < 10 || rows < 2) return;
    _columns = columns.clamp(10, 500);
    _rows = rows.clamp(2, 500);
    _resizeTimer?.cancel();
    _resizeTimer = Timer(const Duration(milliseconds: 120), () {
      final sessionId = _session?.sessionId;
      if (sessionId == null || _status != _TerminalStatus.running) return;
      unawaited(
        _service.resize(sessionId, columns: _columns, rows: _rows).onError((
          Object error,
          StackTrace stackTrace,
        ) {
          if (mounted) setState(() => _error = error.toString());
        }),
      );
    });
  }

  String _statusLabel(BuildContext context) => switch (_status) {
    _TerminalStatus.starting => context.l10n.text('status.starting'),
    _TerminalStatus.running => context.l10n.text('status.running'),
    _TerminalStatus.completed => context.l10n.text('status.completed'),
    _TerminalStatus.failed => context.l10n.text('status.failed'),
  };

  Color _statusColor(ColorScheme colors) => switch (_status) {
    _TerminalStatus.starting => colors.tertiary,
    _TerminalStatus.running => const Color(0xFF34C759),
    _TerminalStatus.completed => colors.onSurfaceVariant,
    _TerminalStatus.failed => colors.error,
  };

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return ColoredBox(
      color: colors.surface,
      child: Column(
        children: [
          SizedBox(
            height: 38,
            child: Row(
              children: [
                const SizedBox(width: 13),
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: _statusColor(colors),
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  _statusLabel(context),
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    _session?.cwd ?? _selection.workspaceName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontFamily: 'monospace',
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ),
                if (_error != null)
                  Tooltip(
                    message: _error!,
                    child: Icon(
                      CupertinoIcons.exclamationmark_triangle,
                      size: 15,
                      color: colors.error,
                    ),
                  ),
                IconButton(
                  key: ValueKey(
                    'terminal-restart:${widget.panelContext.instanceId}',
                  ),
                  tooltip: context.l10n.text('common.retry'),
                  onPressed: () => unawaited(_start()),
                  icon: const Icon(CupertinoIcons.arrow_clockwise, size: 16),
                ),
                const SizedBox(width: 5),
              ],
            ),
          ),
          Divider(height: 1, color: colors.outlineVariant),
          Expanded(
            child: ClipRect(
              child: TerminalView(
                _terminal,
                key: ValueKey(
                  'terminal-view:${widget.panelContext.instanceId}:$_generation',
                ),
                focusNode: _focusNode,
                autofocus: widget.panelContext.active,
                readOnly: _status != _TerminalStatus.running,
                theme: TerminalThemes.defaultTheme,
                textStyle: const TerminalStyle(
                  fontSize: 13,
                  height: 1.22,
                  fontFamily: 'Menlo',
                ),
                padding: const EdgeInsets.all(10),
                backgroundOpacity: 1,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
