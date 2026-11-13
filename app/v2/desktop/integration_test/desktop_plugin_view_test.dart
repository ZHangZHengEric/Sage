import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:sage_desktop_v2/src/state/desktop_plugins.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/workspace_panels/desktop_plugin_panel.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('A native plugin view loads local assets and handshakes', (
    tester,
  ) async {
    final watchdog = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (binding.schedulerPhase == SchedulerPhase.idle) {
        binding.scheduleWarmUpFrame();
      }
    });
    addTearDown(watchdog.cancel);
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    var externalRequests = 0;
    server.listen((request) {
      externalRequests++;
      request.response.headers.set('Access-Control-Allow-Origin', '*');
      unawaited(request.response.close());
    });
    const manifest = <String, Object?>{
      'id': 'test.desktop-plugin',
      'name': 'Native plugin test',
      'entry': 'index.html',
      'icon': 'puzzle',
    };
    Map<String, String> asset(String type, String text) => {
      'type': type,
      'data': base64Encode(utf8.encode(text)),
    };
    final document = <String, Object?>{
      'manifest': manifest,
      'assets': {
        'index.html': asset(
          'text/html',
          '<!doctype html><html><head><title>Test</title></head><body><script src="probe.js" defer></script></body></html>',
        ),
        '__sage/theme.css': asset('text/css', 'body { color: CanvasText }'),
        '__sage/sdk.js': asset('text/javascript', '''
          window.pluginTestToken = document.currentScript.dataset.token;
          window.__sagePluginReceive = () => {};
        '''),
        'probe.js': asset('text/javascript', '''
          if (typeof globalThis.RTCPeerConnection !== 'undefined') throw new Error('WebRTC is available');
          fetch('http://127.0.0.1:${server.port}/probe').then(
            () => { throw new Error('Plugin fetched an external URL'); },
            () => window.SagePluginBridge.postMessage(JSON.stringify({
              version: 1, token: window.pluginTestToken, id: '1', method: 'ready', params: {}
            }))
          );
        '''),
      },
    };
    final controller = WorkspaceController();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DesktopPluginView(
            controller: controller,
            plugin: const DesktopPlugin(manifest),
            preview: document,
          ),
        ),
      ),
    );
    for (var i = 0; i < 100; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      if (find.byType(CupertinoActivityIndicator).evaluate().isEmpty) break;
    }
    expect(find.text('Plugin failed to open'), findsNothing);
    expect(find.byType(CupertinoActivityIndicator), findsNothing);
    expect(externalRequests, 0);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
