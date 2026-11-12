import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:sage_tool_labels/tool_labels.dart';

import 'brand.dart';
import 'voice_engine.dart';

enum SetupStage {
  recognition('语音识别'),
  agent('智能体'),
  synthesis('语音合成');

  const SetupStage(this.label);
  final String label;
}

class VoiceSettings extends StatefulWidget {
  const VoiceSettings({
    super.key,
    required this.engine,
    required this.backLabel,
    required this.onBack,
  });

  final VoiceEngine engine;
  final String backLabel;
  final VoidCallback onBack;

  @override
  State<VoiceSettings> createState() => _VoiceSettingsState();
}

class _VoiceSettingsState extends State<VoiceSettings> {
  late final Map<String, TextEditingController> fields;
  late final Map<String, Object?> initial;
  late String provider;
  late bool localTools;
  late final Map<String, Map<String, Object?>> toolSpeech;
  String selectedTool = 'get_local_time';
  int speechFieldsRevision = 0;
  SetupStage stage = SetupStage.recognition;
  bool saving = false;
  String? error;

  Map<String, Object?> get draft => {
    for (final entry in fields.entries) entry.key: entry.value.text.trim(),
    'speech_provider': provider,
    'local_tools': localTools,
    'tool_speech': Map.of(toolSpeech),
  };

  bool get dirty {
    final savedSpeech =
        initial['tool_speech'] as Map<String, Map<String, Object?>>;
    return draft.entries.any(
          (entry) =>
              entry.key != 'tool_speech' && entry.value != initial[entry.key],
        ) ||
        savedSpeech.length != toolSpeech.length ||
        toolSpeech.entries.any(
          (entry) => !mapEquals(entry.value, savedSpeech[entry.key]),
        );
  }

  @override
  void initState() {
    super.initState();
    final saved = widget.engine.settings ?? {};
    fields = {
      for (final entry in const {
        'model_base_url': 'https://api.openai.com/v1',
        'model': '',
        'model_api_key': '',
        'speech_api_key': '',
        'workspace_id': '',
        'voice': '',
      }.entries)
        entry.key: TextEditingController(
          text: saved[entry.key]?.toString() ?? entry.value,
        ),
    };
    provider = saved['speech_provider']?.toString() ?? 'qwen_audio';
    localTools = saved['local_tools'] == true;
    toolSpeech = {
      for (final entry in ((saved['tool_speech'] as Map?) ?? {}).entries)
        entry.key as String: Map<String, Object?>.from(entry.value as Map),
    };
    initial = draft;
  }

  void editToolSpeech(String key, Object value) {
    setState(() {
      final rule = {...?toolSpeech[selectedTool], key: value};
      if (rule['enabled'] != false &&
          (rule['zh'] as String? ?? '').trim().isEmpty &&
          (rule['en'] as String? ?? '').trim().isEmpty) {
        toolSpeech.remove(selectedTool);
      } else {
        toolSpeech[selectedTool] = rule;
      }
      error = null;
    });
  }

  Widget toolSpeechSettings() {
    final defaults = widget.engine.toolSpeechDefaults;
    final tools = {...defaults.keys, ...toolSpeech.keys, ...sageToolNames.keys}
      ..removeWhere((name) {
        final canonical = (defaults[name] as Map?)?['canonical_tool'];
        return canonical != null && canonical != name;
      });
    final rule = toolSpeech[selectedTool] ?? {};
    final preset = defaults[selectedTool] as Map? ?? {};
    final enabled = rule['enabled'] != false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 12),
        heading('工具进度播报'),
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          key: ValueKey(selectedTool),
          initialValue: selectedTool,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '工具'),
          items: [
            for (final name in tools)
              DropdownMenuItem(
                value: name,
                child: Text(
                  sageToolNames.containsKey(name)
                      ? '${sageToolNames[name]!['zh']} · $name'
                      : name,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: saving
              ? null
              : (name) {
                  if (name != null) setState(() => selectedTool = name);
                },
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('播报此工具的进度'),
          value: enabled,
          onChanged: saving
              ? null
              : (value) => editToolSpeech('enabled', value),
        ),
        for (final language in {'zh': '中文', 'en': '英文'}.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: TextFormField(
              key: ValueKey((selectedTool, language.key, speechFieldsRevision)),
              initialValue: rule[language.key] as String? ?? '',
              enabled: enabled && !saving,
              maxLength: 100,
              decoration: InputDecoration(
                labelText: '${language.value}播报',
                hintText: preset[language.key] as String? ?? '填写后启用此语言的工具提示',
                counterText: '',
              ),
              onChanged: (value) => editToolSpeech(language.key, value),
            ),
          ),
        if (preset['supports_target'] == true)
          const Text('可用 {target} 代入文件名或网站域名。'),
        if (toolSpeech.containsKey(selectedTool))
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: saving
                  ? null
                  : () => setState(() {
                      toolSpeech.remove(selectedTool);
                      speechFieldsRevision++;
                      error = null;
                    }),
              child: const Text('恢复默认播报'),
            ),
          ),
      ],
    );
  }

  @override
  void dispose() {
    for (final field in fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  bool ready(SetupStage step) => switch (step) {
    SetupStage.agent => [
      'model_base_url',
      'model',
      'model_api_key',
    ].every((key) => fields[key]!.text.trim().isNotEmpty),
    SetupStage.recognition ||
    SetupStage.synthesis => fields['speech_api_key']!.text.trim().isNotEmpty,
  };

  Future<void> back() async {
    final leave =
        !dirty ||
        await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: const Text('放弃未保存的更改？'),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('继续编辑'),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('放弃更改'),
                  ),
                ],
              ),
            ) ==
            true;
    if (mounted && leave) widget.onBack();
  }

  Future<void> save() async {
    for (final step in [SetupStage.recognition, SetupStage.agent]) {
      if (!ready(step)) {
        setState(() {
          stage = step;
          error = '请填写${step.label}所需的配置。';
        });
        return;
      }
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.engine.configure(draft);
      if (mounted) widget.onBack();
    } on Object catch (exception) {
      if (!mounted) return;
      setState(() {
        saving = false;
        error = exception.toString();
      });
    }
  }

  Widget field(
    String name,
    String label, {
    bool secret = false,
    String? hint,
  }) => Padding(
    padding: const EdgeInsets.only(top: 14),
    child: TextField(
      controller: fields[name],
      enabled: !saving,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      decoration: InputDecoration(labelText: label, hintText: hint),
      onChanged: (_) => setState(() => error = null),
    ),
  );

  Widget heading(String title, [String? description]) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(title, style: Theme.of(context).textTheme.titleMedium),
      if (description != null) ...[
        const SizedBox(height: 5),
        Text(
          description,
          style: TextStyle(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    ],
  );

  Widget stages(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Stack(
      children: [
        Positioned(
          top: 21,
          left: 90,
          right: 90,
          child: Divider(height: 1, color: colors.outlineVariant),
        ),
        Row(
          children: [
            for (final step in SetupStage.values)
              Expanded(
                child: TextButton(
                  onPressed: saving
                      ? null
                      : () => setState(() {
                          stage = step;
                          error = null;
                        }),
                  child: Column(
                    children: [
                      CircleAvatar(
                        radius: 17,
                        backgroundColor: stage == step
                            ? colors.primaryContainer
                            : colors.surfaceContainerHighest,
                        foregroundColor: stage == step
                            ? colors.onPrimaryContainer
                            : colors.onSurfaceVariant,
                        child: ready(step)
                            ? const Icon(Icons.check, size: 16)
                            : Text('${step.index + 1}'),
                      ),
                      const SizedBox(height: 7),
                      Text(step.label),
                      Text(
                        ready(step) ? '已填写' : '待配置',
                        style: TextStyle(
                          fontSize: 11,
                          color: colors.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget speechFields(BuildContext context) {
    final synthesis = stage == SetupStage.synthesis;
    final colors = Theme.of(context).colorScheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 188,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              heading('语音服务'),
              const SizedBox(height: 8),
              for (final entry in const {
                'qwen_audio': '阿里云语音',
                'volcengine': '火山引擎语音',
              }.entries)
                ListTile(
                  dense: true,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  selected: provider == entry.key,
                  selectedTileColor: colors.primaryContainer,
                  leading: const Icon(Icons.cloud_outlined, size: 18),
                  title: Text(entry.value),
                  trailing: provider == entry.key
                      ? const Icon(Icons.check, size: 16)
                      : null,
                  onTap: saving || provider == entry.key
                      ? null
                      : () => setState(() {
                          provider = entry.key;
                          fields['speech_api_key']!.clear();
                          fields['workspace_id']!.clear();
                          fields['voice']!.clear();
                        }),
                ),
            ],
          ),
        ),
        const SizedBox(width: 24),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              heading(synthesis ? '连接与音色' : '语音识别', '语音识别与合成共用服务商和 API Key。'),
              field('speech_api_key', 'API Key', secret: true),
              if (provider == 'qwen_audio')
                field('workspace_id', '百炼 Workspace ID（可选）'),
              if (synthesis)
                field(
                  'voice',
                  '音色 ID（可选）',
                  hint: provider == 'qwen_audio'
                      ? 'longanhuan_v3.6'
                      : 'zh_female_vv_uranus_bigtts',
                ),
            ],
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(28, 18, 28, 32),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1060),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  TextButton.icon(
                    onPressed: saving ? null : back,
                    icon: const Icon(Icons.arrow_back, size: 16),
                    label: Text(widget.backLabel),
                  ),
                  const Spacer(),
                  const SageBrand(size: 21),
                ],
              ),
              const SizedBox(height: 20),
              stages(context),
              const SizedBox(height: 18),
              Container(
                padding: const EdgeInsets.all(22),
                decoration: BoxDecoration(
                  border: Border.all(color: colors.outlineVariant),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (stage == SetupStage.agent) ...[
                      heading('模型配置', '连接兼容 OpenAI Chat Completions 的模型服务。'),
                      field('model_base_url', 'Base URL'),
                      field('model_api_key', 'API Key', secret: true),
                      field('model', '模型 ID'),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('启用本机时间查询'),
                        subtitle: const Text('需要模型支持工具调用'),
                        value: localTools,
                        onChanged: saving
                            ? null
                            : (value) {
                                setState(() => localTools = value);
                              },
                      ),
                      toolSpeechSettings(),
                    ] else
                      speechFields(context),
                    if (error case final String message)
                      Padding(
                        padding: const EdgeInsets.only(top: 14),
                        child: Text(
                          message,
                          style: TextStyle(color: colors.error),
                        ),
                      ),
                    const SizedBox(height: 20),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton(
                        onPressed: saving || !widget.engine.connected
                            ? null
                            : save,
                        child: Text(saving ? '保存中' : '保存配置'),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
