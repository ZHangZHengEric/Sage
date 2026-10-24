"""Validate selected archive trajectories against the pinned JAR, without a model."""
import argparse
import hashlib
import json
from evaluation_datasets.scienceworld import runtime


def verify():
    env = runtime.activate()(envStepLimit=runtime.LIMIT + 1)
    report = {'jar_sha256': hashlib.sha256((runtime.ROOT / 'vendor/scienceworld/scienceworld.jar').read_bytes()).hexdigest(),
        'simplifications': '', 'target_action_limit': runtime.LIMIT, 'verified_task_ids': [],
        'failed_reference_paths': [], 'fold_mismatches': [], 'prompt_overrides': {}}
    try:
        for i, t in enumerate(runtime.tasks().values()):
            env.load(t['task'], t['variation'], simplificationStr='', generateGoldPath=False)
            _, info = env.reset()
            folds = {'train': env.get_variations_train, 'dev': env.get_variations_dev, 'test': env.get_variations_test}
            if t['variation'] not in folds[t['fold']]():
                report['fold_mismatches'].append(t['id'])
            current = env.get_task_description().strip()
            if t.get('archive_input', t['input']).strip() != current:
                report['prompt_overrides'][t['id']] = current
            for action in t['gold_actions'][:runtime.LIMIT]:
                _, _, done, info = env.step(action)
                if done:
                    break
            if info['score'] == 100:
                report['verified_task_ids'].append(t['id'])
            else:
                report['failed_reference_paths'].append({'id': t['id'], 'score': info['score']})
            print(f"{i + 1}/{len(runtime.tasks())}: {t['id']} = {info['score']}", flush=True)
    finally:
        env.close()
        env._gateway.java_process.wait(timeout=5)
    if report['fold_mismatches']:
        raise ValueError('Official split drift; refusing to publish this selection')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=runtime.ROOT / 'data/validation.json', type=__import__('pathlib').Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(verify(), ensure_ascii=False, indent=2) + '\n')
