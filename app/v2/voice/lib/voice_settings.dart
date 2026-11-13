import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_tool_labels/tool_labels.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_glass.dart';
import 'voice_locale.dart';

enum SetupStage {
  recognition('语音识别', 'Speech recognition'),
  agent('智能体', 'Agent'),
  synthesis('语音合成', 'Speech synthesis');

  const SetupStage(this.zh, this.en);
  final String zh;
  final String en;

  String label(BuildContext context) => context.tr(zh, en);
}

enum AgentSection {
  connection(Icons.link_rounded, '模型连接', 'Model connection'),
  generation(Icons.tune_rounded, '生成参数', 'Generation'),
  prompt(Icons.notes_rounded, '系统提示词', 'System prompt'),
  tools(Icons.build_outlined, '工具', 'Tools');

  const AgentSection(this.icon, this.zh, this.en);
  final IconData icon;
  final String zh;
  final String en;

  String label(BuildContext context) => context.tr(zh, en);
}

class VoiceSettings extends StatefulWidget {
  const VoiceSettings({
    super.key,
    required this.engine,
    required this.backLabel,
    required this.onBack,
    this.onLanguageChanged,
  });

  final VoiceEngine engine;
  final String backLabel;
  final VoidCallback onBack;
  final ValueChanged<Locale?>? onLanguageChanged;

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
  AgentSection agentSection = AgentSection.connection;
  String? reasoningEffort;

  static const numericFields = {'temperature', 'max_output_tokens'};
  bool saving = false;
  String? error;

  Map<String, Object?> get draft => {
    for (final entry in fields.entries)
      if (!numericFields.contains(entry.key))
        entry.key: entry.value.text.trim(),
    for (final key in numericFields)
      key: fields[key]!.text.trim().isEmpty ? null : fields[key]!.text.trim(),
    'reasoning_effort': reasoningEffort,
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
        'system_prompt': '',
        'temperature': '',
        'max_output_tokens': '',
        'speech_api_key': '',
        'workspace_id': '',
        'voice': '',
      }.entries)
        entry.key: TextEditingController(
          text: saved[entry.key]?.toString() ?? entry.value,
        ),
    };
    reasoningEffort = saved['reasoning_effort'] as String?;
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
    final tools =
        {
          'get_local_time',
          ...defaults.keys,
          ...toolSpeech.keys,
          ...sageToolNames.keys,
        }..removeWhere((name) {
          final canonical = (defaults[name] as Map?)?['canonical_tool'];
          return canonical != null && canonical != name;
        });
    final rule = toolSpeech[selectedTool] ?? {};
    final preset = defaults[selectedTool] as Map? ?? {};
    final enabled = rule['enabled'] != false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        heading(context.tr('工具进度播报', 'Tool announcements')),
        const SizedBox(height: 14),
        DropdownButtonFormField<String>(
          key: ValueKey(selectedTool),
          initialValue: selectedTool,
          isExpanded: true,
          decoration: InputDecoration(labelText: context.tr('工具', 'Tool')),
          items: [
            for (final name in tools)
              DropdownMenuItem(
                value: name,
                child: Text(
                  sageToolNames[name]?[context.voiceChinese ? 'zh' : 'en'] ??
                      name,
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
          title: Text(context.tr('播报进度', 'Announce progress')),
          value: enabled,
          onChanged: saving
              ? null
              : (value) => editToolSpeech('enabled', value),
        ),
        for (final language in {'zh': '中文', 'en': 'English'}.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: TextFormField(
              key: ValueKey((selectedTool, language.key, speechFieldsRevision)),
              initialValue: rule[language.key] as String? ?? '',
              enabled: enabled && !saving,
              maxLength: 100,
              decoration: InputDecoration(
                labelText: language.value,
                floatingLabelBehavior: FloatingLabelBehavior.always,
                hintText: preset[language.key] as String?,
                counterText: '',
              ),
              onChanged: (value) => editToolSpeech(language.key, value),
            ),
          ),
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
              child: Text(context.tr('恢复默认播报', 'Restore defaults')),
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
                title: Text(
                  context.tr('放弃未保存的更改？', 'Discard unsaved changes?'),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: Text(context.tr('继续编辑', 'Keep editing')),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: Text(context.tr('放弃更改', 'Discard changes')),
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
          if (step == SetupStage.agent) agentSection = AgentSection.connection;
          error = context.tr('请填写必填项。', 'Complete the required fields.');
        });
        return;
      }
    }
    final temperatureText = fields['temperature']!.text.trim();
    final maxTokensText = fields['max_output_tokens']!.text.trim();
    final temperature = double.tryParse(temperatureText);
    final maxTokens = int.tryParse(maxTokensText);
    if (temperatureText.isNotEmpty &&
        (temperature == null ||
            !temperature.isFinite ||
            temperature < 0 ||
            temperature > 2)) {
      setState(() {
        stage = SetupStage.agent;
        agentSection = AgentSection.generation;
        error = context.tr(
          '温度须在 0 到 2 之间。',
          'Temperature must be between 0 and 2.',
        );
      });
      return;
    }
    if (maxTokensText.isNotEmpty && (maxTokens == null || maxTokens < 1)) {
      setState(() {
        stage = SetupStage.agent;
        agentSection = AgentSection.generation;
        error = context.tr(
          '最大输出 Token 数须为正整数。',
          'Max output tokens must be a positive integer.',
        );
      });
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.engine.configure({
        ...draft,
        'temperature': temperature,
        'max_output_tokens': maxTokens,
      });
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
    int lines = 1,
    int? maxLength,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: TextField(
      controller: fields[name],
      enabled: !saving,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      minLines: lines,
      maxLines: lines == 1 ? 1 : 12,
      maxLength: maxLength,
      decoration: InputDecoration(
        labelText: label,
        floatingLabelBehavior: FloatingLabelBehavior.always,
        counterText: '',
      ),
      onChanged: (_) {
        if (error != null) setState(() => error = null);
      },
    ),
  );

  Widget heading(String title) => Text(
    title,
    style: Theme.of(
      context,
    ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
  );

  Widget section(String title, List<Widget> children) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [heading(title), const SizedBox(height: 16), ...children],
  );

  Widget speechFields() {
    final colors = Theme.of(context).colorScheme;
    final synthesis = stage == SetupStage.synthesis;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 188,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              heading(context.tr('语音服务', 'Speech service')),
              const SizedBox(height: 8),
              for (final service in {
                'qwen_audio': context.tr('阿里云语音', 'Alibaba Cloud'),
                'volcengine': context.tr('火山引擎语音', 'Volcengine'),
              }.entries)
                ListTile(
                  dense: true,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  leading: const Icon(Icons.cloud_outlined, size: 17),
                  title: Text(service.value),
                  selected: provider == service.key,
                  selectedTileColor: colors.secondaryContainer,
                  onTap: saving || provider == service.key
                      ? null
                      : () => setState(() {
                          provider = service.key;
                          fields['speech_api_key']!.clear();
                          fields['workspace_id']!.clear();
                          fields['voice']!.clear();
                          error = null;
                        }),
                ),
            ],
          ),
        ),
        const SizedBox(width: 24),
        Expanded(
          child: section(stage.label(context), [
            field('speech_api_key', 'API Key', secret: true),
            if (provider == 'qwen_audio')
              field(
                'workspace_id',
                context.tr('Workspace ID（可选）', 'Workspace ID (optional)'),
              ),
            if (synthesis)
              field('voice', context.tr('音色 ID（可选）', 'Voice ID (optional)')),
          ]),
        ),
      ],
    );
  }

  List<Widget> connectionFields() => [
    field('model_base_url', 'Base URL'),
    field('model_api_key', 'API Key', secret: true),
    field('model', context.tr('模型 ID', 'Model ID')),
  ];

  List<Widget> generationFields() => [
    DropdownButtonFormField<String>(
      initialValue: reasoningEffort ?? '',
      decoration: InputDecoration(
        labelText: context.tr('思考强度', 'Reasoning effort'),
        floatingLabelBehavior: FloatingLabelBehavior.always,
      ),
      items: [
        for (final option in {
          '': context.tr('模型默认', 'Model default'),
          'none': context.tr('关闭', 'Off'),
          'minimal': context.tr('极低', 'Minimal'),
          'low': context.tr('低', 'Low'),
          'medium': context.tr('中', 'Medium'),
          'high': context.tr('高', 'High'),
          'xhigh': context.tr('极高', 'Extra high'),
        }.entries)
          DropdownMenuItem(value: option.key, child: Text(option.value)),
      ],
      onChanged: saving
          ? null
          : (value) {
              setState(() => reasoningEffort = value == '' ? null : value);
            },
    ),
    const SizedBox(height: 16),
    field('temperature', context.tr('温度（可选）', 'Temperature (optional)')),
    field(
      'max_output_tokens',
      context.tr('最大输出 Token 数（可选）', 'Max output tokens (optional)'),
    ),
  ];

  List<Widget> toolFields() => [
    SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(context.tr('允许查询本机时间', 'Allow local time lookup')),
      value: localTools,
      onChanged: saving ? null : (value) => setState(() => localTools = value),
    ),
    const SizedBox(height: 16),
    toolSpeechSettings(),
  ];

  Widget agentFields() {
    final colors = Theme.of(context).colorScheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 188,
          child: Column(
            children: [
              for (final item in AgentSection.values)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: ListTile(
                    dense: true,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    leading: Icon(item.icon, size: 17),
                    title: Text(item.label(context)),
                    selected: agentSection == item,
                    selectedTileColor: colors.secondaryContainer,
                    onTap: saving
                        ? null
                        : () => setState(() {
                            agentSection = item;
                          }),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(width: 24),
        Expanded(
          child: KeyedSubtree(
            key: ValueKey(agentSection),
            child: section(agentSection.label(context), switch (agentSection) {
              AgentSection.connection => connectionFields(),
              AgentSection.generation => generationFields(),
              AgentSection.prompt => [
                field(
                  'system_prompt',
                  context.tr('系统提示词（可选）', 'System prompt (optional)'),
                  lines: 5,
                  maxLength: 12000,
                ),
              ],
              AgentSection.tools => toolFields(),
            }),
          ),
        ),
      ],
    );
  }

  Widget languageMenu() => PopupMenuButton<String>(
    tooltip: context.tr('界面语言', 'Interface language'),
    icon: const Icon(Icons.language_rounded, size: 18),
    onSelected: (value) =>
        widget.onLanguageChanged!(value.isEmpty ? null : Locale(value)),
    itemBuilder: (context) => [
      PopupMenuItem(
        value: '',
        child: Text(context.tr('跟随系统', 'System default')),
      ),
      const PopupMenuItem(value: 'zh', child: Text('简体中文')),
      const PopupMenuItem(value: 'en', child: Text('English')),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        SizedBox(
          height: 44,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(92, 0, 18, 0),
            child: Row(
              children: [
                VoiceGlassButton(
                  icon: Icons.arrow_back_rounded,
                  label: widget.backLabel,
                  onPressed: saving ? null : back,
                ),
                const Spacer(),
                if (widget.onLanguageChanged != null) ...[
                  languageMenu(),
                  const SizedBox(width: 12),
                ],
                const SageBrand(size: 16),
              ],
            ),
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(28, 12, 28, 28),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1060),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 480),
                        child: GlassSegmentedControl(
                          segments: [
                            for (final step in SetupStage.values)
                              GlassTab(label: step.label(context)),
                          ],
                          selectedIndex: stage.index,
                          onSegmentSelected: (index) {
                            if (saving || index == stage.index) return;
                            setState(() {
                              stage = SetupStage.values[index];
                              error = null;
                            });
                          },
                          height: 36,
                          borderRadius: 10,
                          padding: const EdgeInsets.all(3),
                          backgroundColor: colors.surfaceContainerHighest,
                          indicatorColor: colors.secondaryContainer,
                          selectedTextStyle: TextStyle(
                            color: colors.onSecondaryContainer,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                          unselectedTextStyle: TextStyle(
                            color: colors.onSurfaceVariant,
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                          ),
                          indicatorExpansion: EdgeInsets.zero,
                          interactionBehavior: GlassInteractionBehavior.none,
                          quality: GlassQuality.minimal,
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    GlassContainer(
                      key: ValueKey(stage),
                      shape: const LiquidRoundedRectangle(borderRadius: 16),
                      quality: GlassQuality.minimal,
                      settings: LiquidGlassSettings(
                        glassColor: colors.surfaceContainerLow,
                        thickness: 2,
                      ),
                      padding: const EdgeInsets.all(22),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (stage == SetupStage.agent)
                            agentFields()
                          else
                            speechFields(),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  error == null
                                      ? ''
                                      : voiceMessage(context, error!),
                                  style: TextStyle(color: colors.error),
                                ),
                              ),
                              const SizedBox(width: 12),
                              VoiceGlassButton(
                                primary: true,
                                label: saving
                                    ? context.tr('保存中', 'Saving')
                                    : context.tr('保存配置', 'Save settings'),
                                onPressed: saving || !widget.engine.connected
                                    ? null
                                    : save,
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
