import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/services/scorer_import.dart';

void main() {
  late Directory directory;
  late File source;
  setUp(() async {
    directory = await Directory.systemTemp.createTemp('scorer runtime ');
    source = File('${directory.path}/scorer.py');
    await source.writeAsString('def score(request): pass');
  });
  tearDown(() async => directory.delete(recursive: true));

  test('ordinary Python imports preserve the default host runtime', () async {
    expect(await scorerPythonExecutable(source.path), isNull);
  });

  test(
    'adjacent metadata selects the local venv without resolving its executable symlink',
    () async {
      final relative = Platform.isWindows
          ? '.venv/Scripts/python.exe'
          : '.venv/bin/python';
      final executable = File('${directory.path}/$relative');
      await executable.parent.create(recursive: true);
      if (Platform.isWindows) {
        await executable.writeAsString('fixture');
      } else {
        await Link(executable.path).create(Platform.resolvedExecutable);
      }
      await File('${directory.path}/scorer.runtime.json').writeAsString(
        jsonEncode({
          'format_version': 'sage.rsi.scorer-runtime/v1',
          'python': '.venv/bin/python',
          'python_windows': '.venv/Scripts/python.exe',
        }),
      );
      expect(
        await scorerPythonExecutable(source.path),
        executable.absolute.path,
      );
    },
  );

  test(
    'a declared missing runtime never falls back to the backend Python',
    () async {
      await File('${directory.path}/scorer.runtime.json').writeAsString(
        jsonEncode({
          'format_version': 'sage.rsi.scorer-runtime/v1',
          'python': 'missing-python',
        }),
      );
      await expectLater(
        scorerPythonExecutable(source.path),
        throwsA(isA<FileSystemException>()),
      );
    },
  );

  test('unknown metadata formats are rejected', () async {
    await File('${directory.path}/scorer.runtime.json').writeAsString('{}');
    await expectLater(
      scorerPythonExecutable(source.path),
      throwsA(isA<FormatException>()),
    );
  });
}
