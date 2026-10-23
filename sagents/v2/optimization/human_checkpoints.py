"""Private human-test phase receipts. Never supplied to tuning or selection."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


class MeasurementCheckpoint:
    def __init__(self, directory, identity):
        self.identity = json.loads(json.dumps(identity))
        self.path = Path(directory) / '.phase-checkpoints' / (_digest(self.identity) + '.json')

    def save(self, conversation, grade):
        payload = {'identity': self.identity, 'conversation': conversation,
            'grade': grade.model_dump(mode='json') if grade is not None else None}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                               prefix='.receipt-', delete=False) as stream:
            temporary = stream.name
            try:
                json.dump({'payload': payload, 'digest': _digest(payload)}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def load(self):
        if not self.path.exists():
            return None
        record = json.loads(self.path.read_text(encoding='utf-8'))
        payload = record['payload']
        if record.get('digest') != _digest(payload) or payload.get('identity') != self.identity:
            raise ValueError('human measurement checkpoint differs')
        from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationObservation
        history = payload['conversation']
        if not isinstance(history, list) or not history:
            raise ValueError('human measurement checkpoint has no execution')
        for turn in history:
            if not isinstance(turn['user'], str):
                raise ValueError('human measurement checkpoint input differs')
            OptimizationObservation.model_validate(turn['target'])
        if payload['grade'] is not None:
            OptimizationGrade.model_validate(payload['grade'])
        return payload
