#!/usr/bin/env python3
"""Project-local durable Jev dispatcher. Native memory is never opened."""
import argparse
import concurrent.futures as futures
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import jev_review as review

CONCURRENCY = 500
MAX_BATCH = 1000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def payload_bytes(payload):
    # Match the shared native client wire JSON encoding.
    return len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())


def connect(path):
    path = Path(path)
    if not path.exists():
        path.touch(mode=0o600, exist_ok=False)
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, status TEXT NOT NULL, response TEXT, error TEXT, started REAL, ended REAL)')
    db.commit()
    return db


def job_key(payload, client_hash, epoch, metadata=None):
    return hashlib.sha256(canonical(['memory-pipeline-v2.1', review.VERSION, payload, metadata, client_hash, epoch])).hexdigest()


def load_batch(path, client_path):
    batch = review.read(path)
    source = Path(client_path).read_bytes()
    if review.digest(source) != batch['client_sha256']:
        raise ValueError('Client changed; replan before sending')
    client = review.client_module(client_path)
    jobs = batch['jobs']
    if not 1 <= len(jobs) <= MAX_BATCH or not batch['cache_epoch'].strip():
        raise ValueError('Batch needs 1..1000 jobs and a model/cache epoch')
    if batch.get('version') != 'memory-pipeline-v2.1' or not 2000 <= batch['request_byte_limit'] <= 32000:
        raise ValueError('Unsupported policy or request byte budget')
    keys = set()
    for job in jobs:
        client.validate_request(job['payload'])
        if payload_bytes(job['payload']) > batch['request_byte_limit']:
            raise ValueError('Request exceeds frozen budget')
        key = job_key(job['payload'], batch['client_sha256'], batch['cache_epoch'], job['metadata'])
        if job['key'] != key or key in keys:
            raise ValueError('Invalid or duplicate job key')
        keys.add(key)
    return batch, client


def reuse_state(db, source, batch, client):
    """Import only exact matching attempts, including unknown ones to prevent retries."""
    path = Path(source).resolve(strict=True)
    previous = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    previous.row_factory = sqlite3.Row
    imported = 0
    try:
        for job in batch['jobs']:
            row = previous.execute('SELECT * FROM jobs WHERE key=?', (job['key'],)).fetchone()
            if row is None:
                continue
            status = row['status']
            if status == 'completed':
                response = json.loads(row['response'])
                client.validate_response(response, job['payload'])
                review.strict_answer_check(response['answers'], job['payload']['questions'])
            else:
                status = 'unknown'
            imported += db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?)',
                (row['key'], status, row['response'], row['error'], row['started'], row['ended'])).rowcount
        db.commit()
    finally:
        previous.close()
    return imported


def post(client, credentials, job):
    key, opener = credentials
    request = client.build_request(job['payload'], key)
    with opener.open(request, timeout=60) as response:
        raw = response.read()
    return raw.decode('utf-8')


def dispatch(batch, db, client, concurrency=CONCURRENCY, sender=None):
    """Caller holds process lock. Commit running before submit; never retry it."""
    if type(concurrency) is not int or not 1 <= concurrency <= CONCURRENCY:
        raise ValueError('Concurrency must be 1..500')
    db.execute("UPDATE jobs SET status='unknown', error='InterruptedAttempt' WHERE status='running'")
    db.commit()
    pending_jobs = []
    for job in batch['jobs']:
        old = db.execute('SELECT * FROM jobs WHERE key=?', (job['key'],)).fetchone()
        if old is None:
            pending_jobs.append(job)
        elif old['status'] != 'completed':
            raise ValueError('Batch contains an unresolved attempt; reconcile it before continuing')
        else:
            response = json.loads(old['response'])
            client.validate_response(response, job['payload'])
            review.strict_answer_check(response['answers'], job['payload']['questions'])
    credentials = client.runtime() if sender is None and pending_jobs else None
    send = sender or (lambda job: post(client, credentials, job))
    peak, attempted, stopped = 0, 0, False
    iterator = iter(pending_jobs)
    with futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        active = {}
        def submit():
            nonlocal attempted, peak
            job = next(iterator, None)
            if job is None:
                return False
            db.execute('INSERT INTO jobs(key,status,started) VALUES(?,?,?)', (job['key'], 'running', time.time()))
            db.commit()
            active[pool.submit(send, job)] = job
            attempted += 1
            peak = max(peak, len(active))
            return True
        while len(active) < concurrency and submit():
            pass
        while active:
            done, _ = futures.wait(active, return_when=futures.FIRST_COMPLETED)
            for future in done:
                job = active.pop(future)
                raw = None
                try:
                    raw = future.result()
                    response = json.loads(raw)
                    client.validate_response(response, job['payload'])
                    review.strict_answer_check(response['answers'], job['payload']['questions'])
                    status, error = 'completed', None
                except Exception as exc:
                    # Transport or validation failure may still have incurred a charge.
                    status, error, stopped = 'unknown', type(exc).__name__, True
                db.execute('UPDATE jobs SET status=?,response=?,error=?,ended=? WHERE key=?',
                           (status, raw, error, time.time(), job['key']))
                db.commit()
            if not stopped:
                while len(active) < concurrency and submit():
                    pass
    counts = {}
    for job in batch['jobs']:
        row = db.execute('SELECT status FROM jobs WHERE key=?', (job['key'],)).fetchone()
        status = row['status'] if row else 'pending'
        counts[status] = counts.get(status, 0) + 1
    return {'concurrency': concurrency, 'peak_inflight': peak, 'attempted': attempted,
            'reused': len(batch['jobs']) - len(pending_jobs), 'status_counts': counts,
            'stopped_on_error': stopped, 'actual_cost': 'unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--client', required=True)
    parser.add_argument('--state', required=True, help='Sidecar queue SQLite, outside native memory')
    parser.add_argument('--concurrency', type=int, default=500)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-calls', type=int)
    parser.add_argument('--reuse-state', help='Prior sidecar queue; import matching completed and uncertain attempts')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 500:
        parser.error('concurrency must be 1..500')
    batch, client = load_batch(args.batch, args.client)
    if not args.execute:
        print(json.dumps({'mode': 'dry-run', 'requests': len(batch['jobs']), 'concurrency': args.concurrency,
                          'payload_bytes': sum(payload_bytes(j['payload']) for j in batch['jobs']),
                          'credentials_loaded': False, 'cost': 'unknown'}))
        return
    if args.max_calls != len(batch['jobs']):
        parser.error('--max-calls must equal the reviewed batch request count')
    # State is always local to the reviewed plan; never accept a native DB path.
    state = Path(args.state).resolve()
    if state.parent != Path(args.batch).resolve().parent or state.name != 'queue.sqlite':
        parser.error('state must be queue.sqlite alongside the batch')
    # One dispatcher across all plans in this project, not one per batch directory.
    lock_root = Path(__file__).resolve().parents[2] / '.local'
    lock_root.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(str(lock_root / 'memory-jev-dispatch.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect(state)
        try:
            if args.reuse_state:
                reuse_state(db, args.reuse_state, batch, client)
            result = dispatch(batch, db, client, args.concurrency)
            print(json.dumps(result))
            if result['stopped_on_error']:
                raise SystemExit(2)
        finally:
            db.close()


if __name__ == '__main__':
    main()
