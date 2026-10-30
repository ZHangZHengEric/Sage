import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

class RsiSaveAgentDialog extends StatefulWidget {
  const RsiSaveAgentDialog({
    required this.initialName,
    required this.chinese,
    required this.settings,
    required this.onSave,
    super.key,
  });

  final String initialName;
  final bool chinese;
  final LiquidGlassSettings settings;
  final Future<void> Function(String name, String requestId) onSave;

  @override
  State<RsiSaveAgentDialog> createState() => _RsiSaveAgentDialogState();
}

class _RsiSaveAgentDialogState extends State<RsiSaveAgentDialog> {
  late final _name = TextEditingController(text: widget.initialName);
  final _form = GlobalKey<FormState>();
  bool _saving = false;
  String? _error, _requestId, _submittedName;
  String t(String zh, String en) => widget.chinese ? zh : en;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving || !_form.currentState!.validate()) return;
    final name = _name.text.trim();
    if (_submittedName != name) {
      _requestId = 'save-agent-${DateTime.now().microsecondsSinceEpoch}';
      _submittedName = name;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave(name, _requestId!);
      if (mounted) Navigator.pop(context, name);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget button(String label, VoidCallback? onTap, Key key) => Semantics(
    button: true,
    enabled: onTap != null,
    label: label,
    child: IgnorePointer(
      ignoring: onTap == null,
      child: Opacity(
        opacity: onTap == null ? .45 : 1,
        child: GlassButton.custom(
          key: key,
          width: 112,
          height: 36,
          settings: widget.settings,
          onTap: onTap ?? () {},
          child: Text(label, style: Theme.of(context).textTheme.bodyMedium),
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_saving,
    child: Dialog(
      backgroundColor: Theme.of(context).colorScheme.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(20)),
      ),
      clipBehavior: Clip.antiAlias,
      elevation: 0,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: GlassCard(
          settings: widget.settings,
          shape: const LiquidRoundedRectangle(borderRadius: 20),
          padding: const EdgeInsets.all(24),
          child: SingleChildScrollView(
            child: Form(
              key: _form,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    t('另存为新 Agent', 'Save as new Agent'),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 24),
                  Text(t('名称', 'Name')),
                  const SizedBox(height: 8),
                  FormField<String>(
                    validator: (_) => _name.text.trim().isEmpty
                        ? t('请输入名称', 'Enter a name')
                        : null,
                    builder: (field) => Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        DecoratedBox(
                          decoration: BoxDecoration(
                            border: Border.all(
                              color: field.hasError
                                  ? Theme.of(context).colorScheme.error
                                  : Theme.of(
                                      context,
                                    ).colorScheme.outlineVariant,
                            ),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Semantics(
                            label: t('名称', 'Name'),
                            child: GlassTextField(
                              key: const ValueKey('rsi-new-agent-name'),
                              controller: _name,
                              enabled: !_saving,
                              autofocus: true,
                              maxLength: 255,
                              textStyle: Theme.of(context).textTheme.bodyMedium,
                              settings: widget.settings,
                              onSubmitted: (_) => _save(),
                            ),
                          ),
                        ),
                        if (field.hasError)
                          Text(
                            field.errorText!,
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                      ],
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    SelectableText(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      button(
                        t('取消', 'Cancel'),
                        _saving ? null : () => Navigator.pop(context),
                        const ValueKey('rsi-save-agent-cancel'),
                      ),
                      button(
                        t('保存', 'Save'),
                        _saving ? null : _save,
                        const ValueKey('rsi-save-agent-confirm'),
                      ),
                      if (_saving) const CupertinoActivityIndicator(),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
