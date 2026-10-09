"""Validate and atomically accept a researched news or policy manuscript.

This command does not research, schedule, commit, push, or deploy anything.
It is the file interface for an authenticated publisher running this checkout.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.magazine import validate_entry


def accept(entry, channel, content_dir, *, replace=False):
    validate_entry(entry, channel)
    directory = content_dir / channel
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'{entry["date"]}-{entry["id"]}.json'
    lock_id = hashlib.sha256(str(content_dir.resolve()).encode()).hexdigest()[:16]
    with open(Path(tempfile.gettempdir()) / f'marketnote-intake-{lock_id}.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            previous = json.loads(target.read_text(encoding='utf-8'))
            if previous == entry:
                return target, False
            if not replace:
                raise ValueError('different manuscript exists; review corrections and use --replace')
            if datetime.fromisoformat(entry['checked_at']) <= datetime.fromisoformat(previous['checked_at']):
                raise ValueError('correction must have a newer checked_at')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, prefix='.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(entry, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    return target, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', choices=('news', 'policies'), required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--content', type=Path, default=Path('content'))
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    try:
        entry = json.loads(args.input.read_text(encoding='utf-8'))
        target, changed = accept(entry, args.channel, args.content, replace=args.replace)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Manuscript rejected: {exc}\n')
    print(f'{"Accepted" if changed else "Already accepted"}: {target}')


if __name__ == '__main__':
    main()
