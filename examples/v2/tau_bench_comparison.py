"""Write a local, matched τ-bench comparison only after all trials finish."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.v2.tau_bench_report import assess


def compare(experiment: Path, reference: Path):
    left = json.loads((experiment / 'experiment.json').read_text())
    right = json.loads((reference / 'experiment.json').read_text())
    if left.get('reference_only') or not right.get('reference_only'):
        raise ValueError('expected one RSI experiment and one default reference')
    for key in ('commit', 'domain', 'seed', 'max_steps', 'target_turn_max_steps',
                'native_tools', 'domain_tools', 'user_and_nl_judge_model'):
        if left[key] != right[key]:
            raise ValueError(f'unmatched comparison condition: {key}')
    if left['partition']['test'] != right['partition']['test']:
        raise ValueError('unmatched test tasks')
    if left['provider_ids'][2] != right['provider_ids'][2]:
        raise ValueError('unmatched user/judge route')
    if left.get('test_trials') != 4 or right.get('test_trials') != 4:
        raise ValueError('comparison requires four trials')
    reports = [assess(experiment), assess(reference)]
    if not all(r['reliability']['complete'] and r.get('frozen_test_conditions_match') for r in reports):
        raise ValueError('comparison is incomplete or frozen conditions differ')
    if reports[0]['frozen']['baseline'] != reports[1]['frozen']['baseline']:
        raise ValueError('reference default package differs from RSI baseline')
    changed = reports[0]['candidate_differs_from_baseline']
    rows = [
        {'label': '默认 ' + left['target_model'], **reports[0]['reliability']['baseline']},
        {'label': ('RSI 后 ' if changed else '原版独立复测（无候选被保留） ') + left['target_model'], **reports[0]['reliability']['candidate']},
        {'label': '默认 ' + right['target_model'], **reports[1]['reliability']['reference']},
    ]
    delta = {k: rows[1][k] - rows[0][k] for k in ('pass^1', 'pass^4')}
    return {'conditions_matched': True, 'tasks': len(left['partition']['test']), 'trials': 4,
        'user_and_judge': left['user_and_nl_judge_model'], 'rows': rows,
        'candidate_changed': changed,
        'adapter_adjustments_disclosed': any(r.get('implementation_adjustments') for r in reports),
        'measurement_delta': delta,
        'rsi_delta': delta if changed else None,
        'audit': reports,
        'warning': 'Local exploratory retail test subset, custom scaffold and model routes; not a leaderboard ranking.'}


def markdown(result):
    lines = ['# τ-bench 本地同条件测评', '',
        f"官方 retail test：{result['tasks']} 题，每题 {result['trials']} 次；用户模拟与自然语言裁判：{result['user_and_judge']}。", '',
        '| Agent | pass¹ | pass⁴ |', '| --- | ---: | ---: |']
    lines.extend(f"| {r['label']} | {r['pass^1']:.2%} | {r['pass^4']:.2%} |" for r in result['rows'])
    comparison = ('RSI 相对同模型默认版：' if result['candidate_changed'] else '原版两组独立测量差值：')
    comparison += '；'.join(f"{k} {v * 100:+.2f} 个百分点" for k, v in result['measurement_delta'].items()) + '。'
    if not result['candidate_changed']:
        comparison += ' 未保留不同于原版的候选；两组包哈希相同，差值只能反映重复测量波动，不能归因于 RSI 改进。'
    lines += ['', comparison, '',
        'pass¹ 是四次运行的平均成功率；pass⁴ 是四次全部成功的任务比例。冻结后的候选由 train/dev 决定，test 仅供人观察。', '',
        '三组使用相同测试任务、种子、原生与业务工具、任务步数与输出预算、用户模拟和判分路由。目标模型采用各自已配置的默认采样/推理参数；因此这里是同任务与显式执行预算下的系统对照，不是严格等算力对照。', '',
        'RSI 使用较强的调优模型，其开发成本也属于方法成本。一次固定划分上的结果不能证明跨领域普遍有效。', '',
        '本实验使用官方 test 子集及自定义 Sage scaffold，与公开完整 base 榜单范围不同，不能直接按百分比排榜。所有结果仅保存在本地，未提交。', '']
    if result.get('adapter_adjustments_disclosed'):
        lines += ['评测包含修复传输适配器后的续跑批次，具体变更保存在审计记录的 implementation_adjustments。已有评分保留，未完成项续跑；这不是全程使用单一适配器实现的实验，解释差异时需保留此限制。', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.experiment, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown(result), encoding='utf-8')
    args.output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(args.output)
