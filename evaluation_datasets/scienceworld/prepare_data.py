"""Stream the pinned official archive; never materialize its 463 MB JSON at once."""
import json
from pathlib import Path
import zipfile
import ijson

ROOT = Path(__file__).resolve().parent


def build_tasks():
    out = []
    with zipfile.ZipFile(ROOT / 'vendor/goldpaths/goldpaths-all.zip') as archive:
        with archive.open(archive.namelist()[0]) as stream:
            for key, task in ijson.kvitems(stream, ''):
                for fold, count in [('train', 3), ('dev', 1), ('test', 1)]:
                    rows = [r for r in task['goldActionSequences'] if r['fold'] == fold]
                    rows.sort(key=lambda r: (len(r['path']), r['variationIdx']))
                    for row in rows[:count]:
                        out.append({'id': f"scienceworld-{key}-{row['variationIdx']}", 'task': task['taskName'],
                            'variation': row['variationIdx'], 'fold': fold, 'input': row['taskDescription'],
                            'gold_actions': [s['action'] for s in row['path']]})
    report = json.loads((ROOT / 'data/validation.json').read_text())
    for row in out:
        row['archive_input'] = row['input']
        row['input'] = report['prompt_overrides'].get(row['id'], row['input'])
    return out


if __name__ == '__main__':
    (ROOT / 'data/tasks.json').write_text(json.dumps(build_tasks(), ensure_ascii=False, indent=2) + '\n')
