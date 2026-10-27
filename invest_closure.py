"""Read-only report reconciliation; this module never submits investing data."""
import hashlib
import json
import os
from pathlib import Path


def reconcile(db, run_id, day, stage):
    with db() as connection:
        row = connection.execute('SELECT id,payload FROM invest_events WHERE event_key=?',
                                 (stage+':'+day,)).fetchone()
    if row is None:
        return {'report': 'missing'}
    payload = json.loads(row['payload'])
    if payload.get('run_id') != run_id:
        return {'report': 'run_mismatch', 'event_id': row['id']}
    return {'report': 'saved', 'event_id': row['id'],
            'payload_sha256': hashlib.sha256(row['payload'].encode()).hexdigest()}


def persist(directory, run_id, receipt):
    if not run_id or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('Invalid run identifier')
    directory=Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path=directory/(run_id+'.json')
    encoded=json.dumps(dict(receipt,run_id=run_id),sort_keys=True,ensure_ascii=False)
    try:
        with path.open('x',encoding='utf-8') as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_text(encoding='utf-8') != encoded:
            raise RuntimeError('Conflicting run receipt; do not retry execution')
    if path.read_text(encoding='utf-8') != encoded:
        raise RuntimeError('Run receipt readback failed')
