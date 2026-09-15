import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/workspace_panels/workspace_panel_plugin.dart';

class StudioApi extends V2ApiClient {
  StudioApi({this.dark = false});
  final bool dark;
  bool rejectSync = false;
  final bodies = <Map<String, Object?>>[];
  final studioBodies = <Map<String, Object?>>[];
  @override
  Future<void> syncStudio(String studioId, Map<String, Object?> body) async {
    if (rejectSync) throw StateError('sync rejected');
    studioBodies.add(body);
  }

  @override
  Future<Map<String, Object?>> studioMessages(
    String studioId, {
    int afterSequence = 0,
  }) async => {
    'messages': bodies.isEmpty || afterSequence > 0
        ? []
        : [
            {
              'id': 'tool:note',
              'sequence': 1,
              'kind': 'note',
              'created_at': DateTime.now().toUtc().toIso8601String(),
              'turn_id': bodies.last['studio_message_id'],
              'sender': bodies.last['studio_member_id'],
              'text': '已读取群历史，沿用之前的约束。',
            },
          ],
    'has_more': false,
  };
  @override
  Future<List<AgentSummary>> listAgents() async => const [
    AgentSummary(id: 'sage', name: 'Sage'),
    AgentSummary(id: 'designer', name: 'Designer'),
  ];
  @override
  Future<DesktopSettings> getSettings() async =>
      DesktopSettings(language: 'zh', themeMode: dark ? 'dark' : 'light');
  @override
  Future<List<SkillSummary>> listSkills(String agentId) async => [];
  @override
  Future<List<WorkspaceFileNode>> workspaceTree({
    required String agentId,
    String workspaceId = '',
  }) async => [];
  @override
  Future<List<Map<String, Object?>>> getSessionTree(String sessionId) async =>
      [];
  @override
  Stream<Map<String, Object?>> subscribeSessionTree(String sessionId) =>
      const Stream.empty();
  @override
  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) {
    bodies.add(body);
    final n = bodies.length;
    return Stream.fromIterable([
      {
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_$n',
          'session_id': body['session_id'],
          'event_cursor': {'run_sequence': 0},
        },
      },
      {
        'type': 'message.delta',
        'run_id': 'run_$n',
        'session_id': body['session_id'],
        'run_sequence': 1,
        'item_id': 'reply_$n',
        'data': {
          'kind': 'item',
          'operation': 'delta',
          'delta': '可以。我们先确定成员和任务，再完成界面设计。',
        },
      },
      {
        'type': 'run.completed',
        'run_id': 'run_$n',
        'session_id': body['session_id'],
        'run_sequence': 2,
        'data': {'kind': 'run', 'state': 'completed'},
      },
    ]);
  }
}

class HoldingStudioApi extends StudioApi {
  final cancelled = <String>[];
  bool rejectCancel = false;
  @override
  Future<void> cancel(String runId) async {
    if (rejectCancel) throw StateError('cancel rejected');
    cancelled.add(runId);
  }

  @override
  Future<Map<String, Object?>> getRun(String runId) async {
    final index = int.parse(runId.split('_').last) - 1;
    return {
      'run': {
        'state': cancelled.contains(runId) ? 'cancelled' : 'running',
        'session_id': bodies[index]['session_id'],
      },
    };
  }

  final streams = <StreamController<Map<String, Object?>>>[];
  @override
  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) {
    bodies.add(body);
    final stream = StreamController<Map<String, Object?>>();
    streams.add(stream);
    stream.add({
      'kind': 'stream.opened',
      'handle': {
        'run_id': 'held_${streams.length}',
        'session_id': body['session_id'],
        'event_cursor': {'run_sequence': 0},
      },
    });
    return stream.stream;
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test(
    'Studio targets stable member identity, isolates sessions and restores public history',
    () async {
      final api = StudioApi();
      final controller = WorkspaceController(api: api);
      await controller.initialize();
      final first = await controller.createStudio('产品讨论', [
        'sage',
        'designer',
      ], coordinatorAgentId: 'sage');
      final designer = first.members.last;
      controller.selectStudioMember(designer.id, mention: true);
      final ordinaryApproval = controller.selectedConversation!.approvalMode;
      controller.setStudioApprovalMode(first, designer, ApprovalMode.alwaysAsk);
      expect(
        await controller.sendStudioMessage('请看看设计，正文引用 @Sage 不改变接收人'),
        isTrue,
      );
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(api.bodies.single['agent_id'], 'designer');
      expect(
        api.bodies.single['approval_mode'],
        ApprovalMode.alwaysAsk.wireValue,
      );
      expect(controller.selectedConversation!.approvalMode, ordinaryApproval);
      expect(controller.studioReplies(first, first.turns.single), hasLength(1));
      expect(controller.agentWorkspaceConversations, hasLength(1));
      await controller.toggleStudioContextTurn(first, first.turns.single.id);
      final second = await controller.createStudio('另一个群', [
        'designer',
      ], coordinatorAgentId: 'designer');
      expect(second.members.single.id, isNot(designer.id));
      await controller.sendStudioMessage('独立上下文');
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(
        api.bodies.last['session_id'],
        isNot(api.bodies.first['session_id']),
      );
      controller.selectStudio(first.id);
      expect(controller.selectedStudioMemberId, isEmpty);
      expect(controller.studioRecipientId, isEmpty);
      await controller.sendStudioMessage('请汇总');
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(api.bodies.last['agent_id'], 'sage');
      expect(api.studioBodies.last.toString(), contains('可以。我们先确定'));
      expect(api.bodies.last['studio_id'], first.id);
      expect(api.bodies.last['studio_member_id'], first.coordinatorId);
      expect(api.bodies.last['messages'], [
        {'role': 'user', 'text': '请汇总'},
      ]);
      await controller.setStudioCoordinator(first, designer.id);
      expect(api.studioBodies.last['coordinator_id'], designer.id);
      expect(controller.studioRecipientId, isEmpty);
      await controller.sendStudioMessage('交给新群主');
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(api.bodies.last['agent_id'], 'designer');
      expect(first.turns.last.explicitMention, isFalse);
      expect(first.turns.first.explicitMention, isTrue);
      api.rejectSync = true;
      await controller.setStudioCoordinator(first, first.members.first.id);
      expect(first.coordinatorId, designer.id);
      expect(first.updatingCoordinator, isFalse);
      expect(controller.error, contains('sync rejected'));
      api.rejectSync = false;
      final restored = WorkspaceController(api: StudioApi());
      await restored.initialize();
      expect(restored.studios, hasLength(2));
      expect(restored.studios.first.turns, hasLength(3));
      expect(restored.studios.first.coordinatorId, designer.id);
      expect(restored.studios.first.pinnedTurnIds, {first.turns.first.id});
      expect(
        restored.studioReplies(
          restored.studios.first,
          restored.studios.first.turns.first,
        ),
        hasLength(1),
      );
      controller.dispose();
      restored.dispose();
    },
  );

  test(
    'messages interrupt only recipients and retain one Session per member',
    () async {
      final api = HoldingStudioApi();
      final controller = WorkspaceController(api: api);
      await controller.initialize();
      final studio = await controller.createStudio('Team', [
        'sage',
        'designer',
      ], coordinatorAgentId: 'sage');
      final sage = studio.members.first;
      final designer = studio.members.last;
      for (final member in studio.members) {
        controller.selectStudioMember(member.id, mention: true);
      }
      expect(await controller.sendStudioMessage('Work in parallel'), isTrue);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      final sessions = {
        for (final m in studio.members)
          m.id: controller.studioExecution(studio, m)!.sessionId,
      };
      final designerRun = controller.studioExecution(studio, designer)!.runId;
      expect(await controller.sendStudioMessage('Update the plan'), isTrue);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(api.cancelled, ['held_1']);
      expect(api.bodies.last['agent_id'], 'sage');
      expect(controller.studioExecution(studio, designer)!.runId, designerRun);
      controller.selectStudioMember(designer.id, mention: true);
      expect(
        await controller.sendStudioMessage('@Designer update layout'),
        isTrue,
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(api.cancelled, ['held_1', designerRun]);
      expect(api.bodies.last['agent_id'], 'designer');
      expect(controller.studioExecution(studio, sage)!.runId, 'held_3');
      for (final member in studio.members) {
        expect(
          controller.studioExecution(studio, member)!.sessionId,
          sessions[member.id],
        );
      }
      api.rejectCancel = true;
      expect(await controller.sendStudioMessage('Cannot cancel'), isFalse);
      expect(api.bodies, hasLength(4));
      expect(studio.turns, hasLength(3));
      expect(controller.studioSending, isFalse);
      expect(controller.error, contains('cancel rejected'));
      controller.dispose();
      for (final stream in api.streams) {
        await stream.close();
      }
    },
  );

  test(
    'multiple mentions start before either completes and share one referenced input',
    () async {
      final api = HoldingStudioApi();
      final controller = WorkspaceController(api: api);
      await controller.initialize();
      final studio = await controller.createStudio('Parallel', [
        'sage',
        'designer',
      ], coordinatorAgentId: 'sage');
      for (final member in studio.members) {
        controller.selectStudioMember(member.id, mention: true);
      }
      controller.setInvocationMode(InvocationMode.plan);
      controller.referenceMessage(
        ChatMessage(id: 'quoted', role: 'assistant', text: 'Full prior answer'),
        'prior answer',
        label: 'Sage',
      );
      expect(controller.composerReferences.single.text, 'prior answer');
      final content = [
        ChatMessageContent.text('@Sage check code; @Designer check UI'),
        ChatMessageContent.reference(
          fileName: 'Sage',
          path: 'conversation://quoted',
          quote: 'prior answer',
        ),
      ];
      expect(
        await controller.sendStudioMessage(
          '@Sage check code; @Designer check UI',
          content: content,
        ),
        isTrue,
      );
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(api.bodies, hasLength(2));
      expect(studio.turns, hasLength(1));
      expect(studio.turns.single.memberIds, hasLength(2));
      expect(api.bodies.map((b) => b['studio_message_id']).toSet(), {
        studio.turns.single.id,
      });
      expect(api.bodies.map((b) => b['session_id']).toSet(), hasLength(2));
      expect(api.bodies.every((b) => b['invocation_mode'] == 'plan'), isTrue);
      expect((api.bodies.last['messages'] as List).single['content'], [
        for (final p in content) p.toJson(),
      ]);
      expect(controller.studioBusy, isTrue);
      expect(controller.composerReferences, isEmpty);
      expect(controller.agentWorkspaceConversations, hasLength(1));
      controller.dispose();
      for (final stream in api.streams) {
        await stream.close();
      }
    },
  );

  for (final dark in [false, true]) {
    testWidgets(
      'Studio creation, keyboard mention, real Run projection and dock ${dark ? 'dark' : 'light'}',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        if (Platform.environment['STUDIO_SCREENSHOTS'] == '1') {
          await tester.runAsync(() async {
            final loader = FontLoader('.AppleSystemUIFont');
            final bytes = await File(
              '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ).readAsBytes();
            loader.addFont(Future.value(ByteData.sublistView(bytes)));
            await loader.load();
            for (final entry in {
              'packages/cupertino_icons/CupertinoIcons':
                  'packages/cupertino_icons/assets/CupertinoIcons.ttf',
              'MaterialIcons': 'fonts/MaterialIcons-Regular.otf',
            }.entries) {
              final icons = FontLoader(entry.key);
              icons.addFont(rootBundle.load(entry.value));
              await icons.load();
            }
          });
        }
        final api = StudioApi(dark: dark);
        final controller = WorkspaceController(api: api);
        final dock = WorkspacePanelDockController();
        await tester.pumpWidget(
          RepaintBoundary(
            key: const ValueKey('capture'),
            child: SageDesktopV2App(
              controller: controller,
              panelDockController: dock,
            ),
          ),
        );
        await tester.pumpAndSettle();
        final normalDockWidth = tester
            .getSize(find.byKey(const ValueKey('workspace-repaint-boundary')))
            .width;
        await tester.tap(find.byKey(const ValueKey('studio-create')));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const ValueKey('studio-name')),
          '产品讨论组',
        );
        await tester.tap(find.widgetWithText(CheckboxListTile, 'Sage'));
        await tester.pump();
        await tester.tap(find.widgetWithText(CheckboxListTile, 'Designer'));
        await tester.pump();
        await tester.tap(find.byKey(const ValueKey('studio-create-confirm')));
        await tester.pumpAndSettle();
        expect(controller.studios, hasLength(1));
        expect(
          tester
              .getSize(find.byKey(const ValueKey('workspace-repaint-boundary')))
              .width,
          closeTo(normalDockWidth, 1),
        );
        await tester.tap(find.byKey(const ValueKey('canvas-collapse-button')));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('workspace-repaint-boundary')),
          findsNothing,
        );
        await tester.tap(find.byKey(const ValueKey('canvas-expand-button')));
        await tester.pumpAndSettle();
        expect(
          tester
              .getSize(find.byKey(const ValueKey('workspace-repaint-boundary')))
              .width,
          closeTo(normalDockWidth, 1),
        );
        expect(dock.activePluginId, 'sage.workspace.studio');
        expect(
          find.byKey(const ValueKey('studio-explicit-mention')),
          findsNothing,
        );
        expect(find.text('群主'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('composer-upload-button')),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('agent-picker')), findsNothing);
        expect(
          find.byKey(const ValueKey('studio-mention-picker')),
          findsNothing,
        );
        final studio = controller.studios.single;
        await tester.tap(
          find.byKey(
            ValueKey('studio-owner:${studio.id}:${studio.coordinatorId}'),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(ValueKey('studio-owner-option:${studio.members.last.id}')),
        );
        await tester.pumpAndSettle();
        expect(studio.coordinatorId, studio.members.last.id);
        expect(studio.turns, isEmpty);
        expect(controller.selectedStudioId, studio.id);
        expect(
          find.byKey(
            ValueKey('studio-settings:${controller.selectedStudioId}'),
          ),
          findsOneWidget,
        );
        dock.open('sage.workspace.files');
        await tester.pumpAndSettle();
        expect(dock.activePluginId, 'sage.workspace.files');
        await tester.tap(
          find.byKey(
            ValueKey('studio-settings:${controller.selectedStudioId}'),
          ),
        );
        await tester.pumpAndSettle();
        expect(dock.activePluginId, 'sage.workspace.studio');
        controller.selectStudioMember(
          controller.studios.single.members.first.id,
          mention: true,
        );
        await tester.pump();
        expect(find.byType(InputChip), findsOneWidget);
        tester.widget<InputChip>(find.byType(InputChip)).onDeleted!();
        await tester.pump();
        expect(
          find.byKey(const ValueKey('studio-explicit-mention')),
          findsNothing,
        );
        await tester.enterText(
          find.byKey(const ValueKey('studio-composer')),
          '@',
        );
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await tester.sendKeyEvent(LogicalKeyboardKey.enter);
        await tester.pump();
        expect(
          controller.studioRecipientId,
          controller.studios.single.members.last.id,
        );
        await tester.enterText(
          find.byKey(const ValueKey('studio-composer')),
          '一起讨论一下 Studio 的群聊界面',
        );
        await tester.pump();
        await tester.tap(find.byKey(const ValueKey('studio-send')));
        await tester.pumpAndSettle();
        expect(api.bodies.single['agent_id'], 'designer');
        expect(find.textContaining('我们先确定'), findsWidgets);
        expect(
          find.byKey(const ValueKey('studio-public:tool:note')),
          findsOneWidget,
        );
        expect(find.text('已读取群历史，沿用之前的约束。'), findsOneWidget);
        expect(
          find.byKey(ValueKey('studio-details:${controller.selectedStudioId}')),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('process-panel')), findsNothing);
        final memberId = controller.studios.single.members.last.id;
        await tester.tap(find.byKey(ValueKey('studio-member-open:$memberId')));
        await tester.pumpAndSettle();
        expect(
          find.byKey(ValueKey('studio-member-session:$memberId')),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('studio-composer')), findsOneWidget);
        expect(find.textContaining('可以。我们先确定'), findsWidgets);
        final memberView = find.byKey(
          ValueKey('studio-member-session:$memberId'),
        );
        expect(
          find.descendant(of: memberView, matching: find.byType(TextField)),
          findsNothing,
        );
        final memberReply = controller
            .studioReplies(studio, studio.turns.single)
            .single;
        expect(
          find.byKey(ValueKey('message-copy:${memberReply.id}')),
          findsOneWidget,
        );
        expect(
          find.byKey(ValueKey('message-reference:${memberReply.id}')),
          findsOneWidget,
        );
        if (Platform.environment['STUDIO_SCREENSHOTS'] == '1') {
          await tester.runAsync(() async {
            final boundary = tester.renderObject<RenderRepaintBoundary>(
              find.byKey(const ValueKey('capture')),
            );
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '/tmp/sage-studio-member-${dark ? 'dark' : 'light'}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.tap(find.byKey(const ValueKey('studio-member-back')));
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('process-panel')), findsNothing);
        expect(tester.takeException(), isNull);
        // Optional local visual QA artifact, never a checked-in golden baseline.
        if (Platform.environment['STUDIO_SCREENSHOTS'] == '1') {
          await tester.runAsync(() async {
            final boundary = tester.renderObject<RenderRepaintBoundary>(
              find.byKey(const ValueKey('capture')),
            );
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '/tmp/sage-studio-${dark ? 'dark' : 'light'}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        final replyId = controller
            .studioReplies(studio, studio.turns.single)
            .single
            .id;
        await tester.tap(find.byKey(ValueKey('studio-reference:$replyId')));
        await tester.pumpAndSettle();
        expect(controller.composerReferences.single.text, contains('可以。我们先确定'));
        controller.clearComposerReferences(studio.id);
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(ValueKey('studio-message-mention:$replyId')),
        );
        await tester.pumpAndSettle();
        expect(controller.studioRecipientIds, [studio.members.last.id]);
        expect(
          tester
              .widget<TextField>(find.byKey(const ValueKey('studio-composer')))
              .controller!
              .text,
          contains('@Designer'),
        );
        controller.clearStudioMention();
        await tester.pumpAndSettle();
        expect(find.byTooltip('保留为群上下文'), findsNothing);
        final composerBounds = tester.getRect(
          find.byKey(const ValueKey('studio-composer-surface')),
        );
        final sendBounds = tester.getRect(
          find.byKey(const ValueKey('studio-send')),
        );
        expect(composerBounds.right - sendBounds.right, closeTo(10, 1));
        final turn = controller.studios.single.turns.single;
        expect(find.byKey(ValueKey('studio-time:${turn.id}')), findsOneWidget);
        String? copied;
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          (call) async {
            if (call.method == 'Clipboard.setData') {
              copied = (call.arguments as Map)['text'] as String;
            }
            return null;
          },
        );
        await tester.tap(find.byKey(ValueKey('studio-copy:${turn.id}')));
        await tester.pumpAndSettle();
        expect(copied, turn.text);
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        );
        expect(api.studioBodies.last['pinned_turn_ids'], isEmpty);
        final oldId = controller.selectedConversationId;
        await controller.selectAgentWorkspaceConversation(oldId);
        await tester.pumpAndSettle();
        expect(controller.selectedStudio, isNull);
        expect(dock.activePluginId, 'sage.workspace.files');
        expect(
          dock.openInstances.where(
            (p) => p.pluginId == 'sage.workspace.studio',
          ),
          isEmpty,
        );
        expect(dock.open('sage.workspace.studio'), isNull);
        controller.selectStudio(controller.studios.single.id);
        await tester.pumpAndSettle();
        dock.closeInstance(dock.activeInstanceId!);
        await tester.pumpAndSettle();
        expect(controller.selectedStudio, isNotNull);
        await tester.tap(find.byKey(const ValueKey('studio-details-open')));
        await tester.pumpAndSettle();
        expect(dock.activePluginId, 'sage.workspace.studio');
        for (final width in [900.0, 600.0]) {
          tester.view.physicalSize = Size(width, 1000);
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const ValueKey('studio-details-open')));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
        }
        await tester.pumpWidget(const SizedBox());
        controller.dispose();
        dock.dispose();
      },
    );
  }
}
