import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/openui_extras.dart';

void main() {
  final cases =
      jsonDecode(
            File(
              'test/fixtures/openui_numeric_contract.json',
            ).readAsStringSync(),
          )
          as List;
  for (var i = 0; i < cases.length; i++) {
    final c = cases[i] as Map;
    test('shared backend/native numeric contract $i ${c['operation']}', () {
      final result = openUiCompute(
        c['operation'] as String,
        c['inputs'] as List,
        Map<String, Object?>.from(c['values'] as Map),
      );
      final expected = c['expected'] as num?;
      expect(result, expected == null ? isNull : closeTo(expected, 1e-8));
    });
  }
}
