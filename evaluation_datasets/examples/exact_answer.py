"""Importable RSI scorer example; compare output against the dataset reference."""

def score(request):
    reference = request['case'].get('reference_answer')
    if reference is None:
        raise ValueError('reference_answer is required')
    correct = (request['observation']['state'] == 'completed'
               and request['observation']['output'].strip() == reference.strip())
    return {'score': 1.0 if correct else 0.0, 'passed': correct,
            'rationale': 'Output matches reference' if correct else 'Output differs from reference'}


SCORER_TEST_CASES = [
    {'request': {'goal': 'Accuracy', 'case': {'id': 'fixture', 'input': '6*7?',
        'rubric': '42', 'reference_answer': '42'}, 'observation': {'state': 'completed', 'output': output}},
     'expected_score': expected, 'expected_passed': expected == 1}
    for output, expected in [('42', 1), ('41', 0)]
]
