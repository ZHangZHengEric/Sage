import 'package:flutter_test/flutter_test.dart';

import 'package:sage_desktop_v2/src/ui/tool_activity_presentation.dart';

void main() {
  test(
    'delegation presents task content without internal agent identifiers',
    () {
      final presentation = toolArgumentPresentation('sys_delegate_task', const {
        'tasks': [
          {
            'agent_id': 'agent_c696d608967c46f1a32d8d7f90571599',
            'content': '实现一个快速排序（QuickSort）算法',
            'session_id': 'session_internal',
          },
        ],
        'session_id': 'session_parent',
      }, 'zh');

      expect(presentation.primary, '实现一个快速排序（QuickSort）算法');
      expect(presentation.metadata, ['1 个子任务']);
      expect(presentation.compact, isNot(contains('agent_')));
      expect(presentation.compact, isNot(contains('session_')));
      expect(presentation.compact, isNot(contains('{')));
    },
  );

  test('every Sage built-in tool has a semantic compact presentation', () {
    final cases = <String, Map<String, Object?>>{
      'file_read': {
        'file_path': 'lib/app.dart',
        'start_line': 10,
        'end_line': 20,
      },
      'file_write': {
        'file_path': 'lib/app.dart',
        'content': 'private body\nsecond line',
        'mode': 'overwrite',
      },
      'file_update': {
        'file_path': 'lib/app.dart',
        'operations': [
          {'update_mode': 'line_range', 'start_line': 1, 'end_line': 2},
        ],
      },
      'apply_patch': {
        'patch':
            '*** Begin Patch\n*** Update File: lib/app.dart\n*** End Patch',
      },
      'grep': {'pattern': 'WorkspacePanel', 'path': 'lib'},
      'glob': {'pattern': '**/*.dart', 'path': 'lib'},
      'list_dir': {'path': 'lib/src', 'depth': 2},
      'execute_shell_command': {'command': 'flutter test', 'workdir': 'app'},
      'await_shell': {'task_id': 'shell_task_123456789'},
      'kill_shell': {'task_id': 'shell_task_123456789'},
      'todo_write': {
        'tasks': [
          {'id': 'internal-id', 'content': '完成测试', 'status': 'in_progress'},
        ],
      },
      'todo_read': {'session_id': 'hidden'},
      'goal_submit': {'content': '# 实施目标\n\n完成所有测试'},
      'goal_complete': {'summary': '全部验收标准已经通过'},
      'turn_status': {'status': 'task_done', 'note': '结果已交付'},
      'tool_expand_tools': {
        'tool_names': ['grep', 'glob'],
      },
      'search_memory': {'query': '插件架构', 'limit': 5},
      'fetch_webpages': {
        'urls': ['https://example.com/docs', 'https://example.com/api'],
      },
      'analyze_image': {'image_path': 'assets/layout.png', 'prompt': '检查布局'},
      'read_lints': {
        'paths': ['lib/app.dart', 'lib/main.dart'],
      },
      'questionnaire_async': {
        'questions': [
          {'question': '请选择布局方式'},
        ],
      },
      'load_skill': {'name': 'frontend-design'},
      'sys_spawn_agent': {
        'name': 'reviewer',
        'description': '代码审查专家',
        'system_prompt': 'very long internal persona',
      },
      'sys_delegate_task': {
        'tasks': [
          {'agent_id': 'agent_internal', 'content': '审查实现'},
        ],
      },
      'sys_team_delegate_task': {
        'tasks': [
          {'agent_id': 'agent_internal', 'content': '运行测试'},
        ],
      },
    };

    for (final entry in cases.entries) {
      final label = localizedToolName(entry.key, 'zh');
      final preview = toolArgumentPreview(entry.key, entry.value, 'zh');
      expect(label, isNot(entry.key), reason: entry.key);
      expect(preview, isNot(contains('agent_internal')), reason: entry.key);
      expect(preview, isNot(contains('session_id')), reason: entry.key);
      expect(preview, isNot(contains('system_prompt')), reason: entry.key);
      expect(preview, isNot(contains('{')), reason: entry.key);
    }

    expect(
      toolArgumentPreview('file_write', cases['file_write']!, 'zh'),
      isNot(contains('private body')),
    );
    expect(
      toolArgumentPreview('todo_write', cases['todo_write']!, 'zh'),
      contains('完成测试'),
    );
  });

  test('all built-in browser tools hide payloads and show user intent', () {
    final cases = <String, Map<String, Object?>>{
      'browser_get_context': const {},
      'browser_navigate': {'url': 'https://example.com/docs?q=sage'},
      'browser_find_text': {'text': '安装'},
      'browser_scroll': {'direction': 'down', 'pages': 2},
      'browser_send_keys': {'keys': 'hello', 'selector': '#search'},
      'browser_wait': {'seconds': 1.5},
      'browser_list_tabs': const {},
      'browser_switch_tab': {'tab_id_suffix': '1234'},
      'browser_select_dropdown': {'text': 'Flutter', 'selector': '#language'},
      'browser_upload_file': {
        'file_name': 'report.pdf',
        'file_data_base64': 'VERY_LONG_PRIVATE_BASE64',
        'file_mime_type': 'application/pdf',
      },
      'browser_screenshot': {'format': 'png', 'quality': 90},
      'browser_dom_action': {
        'action': 'fill',
        'value': 'Sage',
        'dom_id': 'd12',
        'code': 'private script body',
      },
    };

    for (final entry in cases.entries) {
      final label = localizedToolName(entry.key, 'zh');
      final preview = toolArgumentPreview(entry.key, entry.value, 'zh');
      expect(label, isNot(entry.key), reason: entry.key);
      expect(preview, isNot(contains('VERY_LONG_PRIVATE_BASE64')));
      expect(preview, isNot(contains('private script body')));
      expect(preview, isNot(contains('{')));
    }
  });

  test('unknown tools use a safe fallback for nested arguments', () {
    final preview = toolArgumentPreview('future_tool', const {
      'agent_id': 'agent_hidden',
      'api_key': 'secret',
      'tasks': [
        {'agent_id': 'agent_hidden', 'content': '保留用户可读任务'},
      ],
    }, 'zh');

    expect(preview, contains('保留用户可读任务'));
    expect(preview, isNot(contains('agent_hidden')));
    expect(preview, isNot(contains('secret')));
    expect(preview, isNot(contains('{')));
  });
}
