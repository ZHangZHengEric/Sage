import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/v2_api.dart';

class DesktopPlugin {
  const DesktopPlugin(this.data);

  final Map<String, Object?> data;
  String get id => data['id'] as String;
  String get title => data['name'] as String;
  String get digest => data['digest'] as String? ?? '';
  String get icon => data['icon'] as String;
  bool get enabled => data['enabled'] != false;
  int? get pin => data['pin'] as int?;
}

class DesktopPlugins extends ChangeNotifier {
  DesktopPlugins(this.api, this.clientId, this.ensureReady);

  final V2ApiClient api;
  final String clientId;
  final Future<void> Function()? ensureReady;
  List<DesktopPlugin> installed = const [];
  List<Map<String, Object?>> opens = const [];
  final Set<String> _opened = {};
  StreamSubscription<Map<String, Object?>>? _subscription;
  Timer? _retry;
  bool _closed = false;

  List<DesktopPlugin> get pinned =>
      installed.where((p) => p.pin != null).toList()
        ..sort((a, b) => a.pin!.compareTo(b.pin!));

  void start() {
    if (_closed || _subscription != null) return;
    _subscription = api
        .desktopPluginEvents(clientId)
        .listen(
          _update,
          onError: (Object _) => _reconnect(),
          onDone: _reconnect,
          cancelOnError: true,
        );
  }

  void _update(Map<String, Object?> event) {
    if (_closed) return;
    if (!event.containsKey('revision')) {
      for (final request in _opened.toList()) {
        unawaited(_acknowledge(request));
      }
      return;
    }
    installed = [
      for (final item in event['plugins'] as List)
        DesktopPlugin((item as Map).cast<String, Object?>()),
    ];
    opens = [
      for (final item in event['opens'] as List)
        (item as Map).cast<String, Object?>(),
    ];
    final pending = {for (final item in opens) item['request']};
    _opened.retainWhere(pending.contains);
    notifyListeners();
    for (final request in _opened.toList()) {
      unawaited(_acknowledge(request));
    }
  }

  void _reconnect() {
    _subscription = null;
    if (_closed || _retry?.isActive == true) return;
    _retry = Timer(const Duration(seconds: 1), () async {
      if (_closed) return;
      try {
        await ensureReady?.call();
      } on Object {
        _reconnect();
        return;
      }
      start();
    });
  }

  bool wasOpened(String request) => _opened.contains(request);

  void mounted(String request) {
    if (_closed || !_opened.add(request)) return;
    debugPrint('Desktop plugin panel mounted ($request)');
    unawaited(_acknowledge(request));
  }

  Future<void> _acknowledge(String request) async {
    try {
      await api.acknowledgeDesktopPlugin(clientId, request);
    } on Object {
      // The next stream snapshot retries the acknowledgement.
    }
  }

  Future<void> manage(DesktopPlugin plugin, String action) =>
      api.manageDesktopPlugin(plugin.id, action);

  @override
  void dispose() {
    _closed = true;
    _retry?.cancel();
    unawaited(_subscription?.cancel());
    super.dispose();
  }
}
