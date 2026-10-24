import 'dart:convert';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:file_selector_platform_interface/file_selector_platform_interface.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';
import 'rsi_screen_test.dart' show RsiApi;

void main() {
  testWidgets(
    'user Python upload, selection, default reset and request are independent from scorer',
    (tester) async {
      final oldSelector = FileSelectorPlatform.instance;
      FileSelectorPlatform.instance = UserFileSelector();
      addTearDown(() => FileSelectorPlatform.instance = oldSelector);
      final api = UserModuleApi();
      final controller = WorkspaceController(api: api);
      tester.view.physicalSize = const Size(1800, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(() {
        controller.dispose();
        api.close();
      });
      await tester.pumpWidget(
        MaterialApp(
          home: RsiScreen(
            controller: controller,
            agentId: 'agent',
            agentName: 'Sage',
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
      await tester.pumpAndSettle();
      final uploadButton = find.byKey(
        const ValueKey('rsi-import-user-simulator'),
      );
      await tester.ensureVisible(uploadButton);
      await tester.tap(uploadButton);
      await tester.pumpAndSettle();
      expect(api.uploadedModule!['name'], 'tau_user.py');
      expect(api.uploadedModule!['source'], 'async def reply(request): pass');
      expect(find.text('tau_user.py'), findsOneWidget);
      final instructions = find.byKey(
        const ValueKey('rsi-user-simulator-instructions'),
      );
      expect(tester.widget<GlassTextField>(instructions).enabled, isFalse);
      final picker = find.byKey(const ValueKey('rsi-user-simulator-picker'));
      await tester.ensureVisible(picker);
      await tester.tap(picker);
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('rsi-user-simulator-default')),
      );
      await tester.pumpAndSettle();
      expect(tester.widget<GlassTextField>(instructions).enabled, isTrue);
      await tester.tap(picker);
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('rsi-user-simulator-user-module-1')),
      );
      await tester.pumpAndSettle();
      final goal = find.byKey(const ValueKey('rsi-goal'));
      await tester.ensureVisible(goal);
      await tester.enterText(goal, 'Improve dialogue');
      final start = find.byKey(const ValueKey('rsi-start'));
      await tester.ensureVisible(start);
      await tester.tap(start);
      await tester.pumpAndSettle();
      expect(api.startOptions!['user_simulator_id'], 'user-module-1');
      expect(
        api.startOptions!.containsKey('user_simulator_instructions'),
        isFalse,
      );
      expect(api.startOptions!.containsKey('scorer_id'), isFalse);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  for (final custom in [
    null,
    'Only use supplied customer facts. Ask one question at a time.',
  ]) {
    testWidgets(
      'simulated user ${custom == null ? "defaults" : "is independently configured"}',
      (tester) async {
        final api = RsiApi();
        final controller = WorkspaceController(api: api);
        tester.view.physicalSize = const Size(1600, 1600);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(() {
          controller.dispose();
          api.close();
        });
        await tester.pumpWidget(
          MaterialApp(
            home: RsiScreen(
              controller: controller,
              agentId: 'agent',
              agentName: 'Sage',
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
        await tester.pumpAndSettle();
        expect(find.text('模拟用户（留空使用默认）'), findsOneWidget);
        await tester.enterText(
          find.byKey(const ValueKey('rsi-goal')),
          'Improve factual dialogue',
        );
        if (custom != null) {
          final field = find.byKey(
            const ValueKey('rsi-user-simulator-instructions'),
          );
          await tester.ensureVisible(field);
          await tester.enterText(field, custom);
        }
        final start = find.byKey(const ValueKey('rsi-start'));
        await tester.ensureVisible(start);
        await tester.tap(start);
        await tester.pumpAndSettle();
        expect(api.startOptions, isNotNull);
        if (custom == null) {
          expect(
            api.startOptions!.containsKey('user_simulator_instructions'),
            isFalse,
          );
        } else {
          expect(api.startOptions!['user_simulator_instructions'], custom);
        }
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
}

class UserModuleApi extends RsiApi {
  final modules = <Map<String, Object?>>[];
  Map<String, Object?>? uploadedModule;

  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    ...await super.rsiHistory(agentId),
    'user_simulators': modules,
  };

  @override
  Future<Map<String, Object?>> importRsiUserSimulator(
    String agentId,
    Map<String, Object?> module,
  ) async {
    uploadedModule = module;
    final stored = <String, Object?>{
      'id': 'user-module-1',
      'name': module['name'],
      'descriptor': {'version': 'frozen-v1'},
      'validation': {'status': 'passed'},
    };
    modules.add(stored);
    return stored;
  }
}

class UserFileSelector extends FileSelectorPlatform {
  @override
  Future<XFile?> openFile({
    List<XTypeGroup>? acceptedTypeGroups,
    String? initialDirectory,
    String? confirmButtonText,
  }) async {
    expect(acceptedTypeGroups!.single.extensions, ['py']);
    return XFile.fromData(
      utf8.encode('async def reply(request): pass'),
      name: 'tau_user.py',
      path: '/tmp/tau_user.py',
    );
  }
}
