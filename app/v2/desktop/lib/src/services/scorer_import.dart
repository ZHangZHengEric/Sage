import 'dart:convert';
import 'dart:io';

/// A scorer may opt into an adjacent, explicitly declared Python environment.
Future<String?> scorerPythonExecutable(String sourcePath) async {
  if (sourcePath.isEmpty) return null;
  final source = File(sourcePath).absolute;
  final metadata = File(
    source.path.replaceFirst(RegExp(r'\.py$'), '.runtime.json'),
  );
  if (metadata.path == source.path || !metadata.existsSync()) return null;
  if (metadata.lengthSync() > 65536) {
    throw const FormatException('Scorer runtime configuration exceeds 64 KiB');
  }
  final value = jsonDecode(metadata.readAsStringSync());
  if (value is! Map ||
      value['format_version'] != 'sage.rsi.scorer-runtime/v1') {
    throw const FormatException('Invalid scorer runtime configuration');
  }
  final executable =
      (Platform.isWindows ? value['python_windows'] : null) ?? value['python'];
  if (executable is! String || executable.trim().isEmpty) {
    throw const FormatException(
      'Scorer runtime configuration must specify Python',
    );
  }
  final interpreter = File(executable).isAbsolute
      ? File(executable)
      : File('${source.parent.path}${Platform.pathSeparator}$executable');
  if (!interpreter.existsSync()) {
    throw FileSystemException(
      'Create the scorer virtual environment before importing it',
      interpreter.path,
    );
  }
  // Keep the venv path: resolving its symlink would select the base Python.
  return interpreter.absolute.path;
}
