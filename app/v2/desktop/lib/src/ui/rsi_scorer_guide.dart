import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

const rsiScorerExample = r'''def score(request):
    case = request["case"]
    observation = request["observation"]
    expected = case.get("reference_answer")
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError("This scorer requires a reference_answer")

    completed = observation["state"] == "completed"
    matched = observation["output"].strip() == expected.strip()
    passed = completed and matched
    return {
        "grade": {
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "rationale": (
                "Completed and matched the reference answer."
                if passed else
                "Execution did not complete or answer did not match."
            ),
        },
        "details": {"completed": completed, "matched": matched},
    }


def test_request(output, state="completed"):
    return {
        "goal": "Return the correct arithmetic result.",
        "case": {
            "id": "arithmetic-1",
            "input": "What is 6 * 7?",
            "rubric": "The answer must equal 42.",
            "reference_answer": "42",
            "split": "training",
        },
        "observation": {"state": state, "output": output},
    }


SCORER_TEST_CASES = [
    {"request": test_request("42"),
     "expected_score": 1.0, "expected_passed": True},
    {"request": test_request("41"),
     "expected_score": 0.0, "expected_passed": False},
    {"request": test_request("42", "failed"),
     "expected_score": 0.0, "expected_passed": False},
]
''';

Future<void> showRsiScorerGuide(BuildContext context, {required bool chinese}) {
  String t(String zh, String en) => chinese ? zh : en;
  return showDialog<void>(
    context: context,
    builder: (context) {
      final colors = Theme.of(context).colorScheme;
      final glass = LiquidGlassSettings(
        glassColor: colors.surface,
        visibility: 1,
        standardOpacityMultiplier: 1,
        blur: 0,
        lightIntensity: 0,
        glowIntensity: 0,
      );
      Widget section(String title, String content) => Padding(
        padding: const EdgeInsets.only(bottom: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            SelectableText(
              content,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(height: 1.5),
            ),
          ],
        ),
      );
      return Dialog(
        backgroundColor: Colors.transparent,
        child: SizedBox(
          width: 820,
          height: MediaQuery.sizeOf(context).height * .84,
          child: GlassCard(
            settings: glass,
            useOwnLayer: true,
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        t('如何编写评分器', 'Writing a scorer'),
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: t('关闭', 'Close'),
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(CupertinoIcons.xmark, size: 18),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        section(
                          t('1. 编写 Python 文件', '1. Write a Python file'),
                          t(
                            '保存为 .py 文件，导出 score(request) 函数，可使用同步或 async 函数。request 是字典，返回评分结果字典；不需要自行读取标准输入或打印 JSON。',
                            'Save a .py file exporting score(request), either synchronous or async. It receives a dictionary and returns a result dictionary. You do not need to read stdin or print JSON.',
                          ),
                        ),
                        section(
                          t('2. 根据执行证据评分', '2. Grade execution evidence'),
                          t(
                            '输入包含 goal（目标）、case（题目、rubric 评测标准、可选 reference_answer 标准答案）、observation（state 执行状态、output 输出、evidence 执行证据）以及 conversation（对话记录）。按任务要求核对答案、实际操作或最终状态，不要仅凭回答中出现“完成”等词就判定成功。',
                            'Inputs include goal, case (input, rubric, optional reference_answer), observation (state, output, evidence), and conversation. Check the answer, actual actions, or final state against the task. A claim such as “done” is not proof of success.',
                          ),
                        ),
                        section(
                          t('3. 返回明确的分数与依据', '3. Return a score and rationale'),
                          t(
                            '返回 grade，包含 score（0 到 1 的数字）、passed（布尔值）、rationale（非空评分依据）。可用 details 返回额外核验结果。评分规则和通过阈值应固定；执行失败、缺失证据和答案错误应分别处理。',
                            'Return grade with score (a number from 0 to 1), passed (a boolean), and rationale (a nonempty explanation). Optional details can contain verification results. Keep scoring rules and thresholds fixed, and handle execution failure, missing evidence, and incorrect answers explicitly.',
                          ),
                        ),
                        section(
                          t('4. 自测后导入', '4. Self-test and import'),
                          t(
                            '文件必须包含 1 到 10 个 SCORER_TEST_CASES，每项提供 request、expected_score 和 expected_passed。建议覆盖正确、错误和执行失败。点击“导入评分器”选择文件，系统运行自测，通过后保存固定版本，再从评分器列表选择使用。',
                            'Include 1 to 10 SCORER_TEST_CASES, each with request, expected_score, and expected_passed. Cover correct answers, incorrect answers, and failed executions. Import the file; the system runs these tests and saves a frozen version on success. Select it from the scorer list.',
                          ),
                        ),
                        section(
                          t('示例适用范围', 'Example scope'),
                          t(
                            '下面示例适用于有确定文本答案的题目，仅忽略首尾空白。业务操作、工具调用和多轮任务应改为核对对应的执行证据。若规则要求标准答案，题目未提供时应报错，避免误判通过。',
                            'This example checks a deterministic text answer, ignoring only surrounding whitespace. For business operations, tool use, and multi-turn tasks, verify the corresponding execution evidence. If your rules require a reference answer, raise an error when it is missing.',
                          ),
                        ),
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                'scorer.py',
                                style: Theme.of(context).textTheme.titleSmall,
                              ),
                            ),
                            GlassButton.custom(
                              width: 116,
                              height: 34,
                              settings: glass,
                              shape: const LiquidRoundedRectangle(
                                borderRadius: 10,
                              ),
                              onTap: () async {
                                await Clipboard.setData(
                                  const ClipboardData(text: rsiScorerExample),
                                );
                                if (context.mounted) {
                                  ScaffoldMessenger.maybeOf(
                                    context,
                                  )?.showSnackBar(
                                    SnackBar(
                                      content: Text(
                                        t('示例已复制', 'Example copied'),
                                      ),
                                    ),
                                  );
                                }
                              },
                              child: Text(t('复制示例', 'Copy example')),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        DecoratedBox(
                          decoration: BoxDecoration(
                            color: colors.surfaceContainerHighest,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            padding: const EdgeInsets.all(16),
                            child: SelectableText(
                              rsiScorerExample,
                              style: TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 13,
                                height: 1.5,
                                color: colors.onSurface,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}
