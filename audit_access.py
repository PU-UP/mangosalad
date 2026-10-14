"""Owner-operated audit password setup. Never prints a password or hash."""
import argparse
import getpass
import json
import os
import re
import secrets
import sys
from pathlib import Path
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent/'vendor'))
from werkzeug.security import generate_password_hash

ACCESS = Path.home()/'.config/mangosalad/audit-access.json'


def configure(path, password):
    if not isinstance(password, str) or not 24 <= len(password) <= 256:
        raise ValueError('Use a unique password-manager password, 24–256 characters.')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.resolve() != path.parent.absolute():
        raise ValueError('Refusing a symlinked configuration path.')
    record = {'password_hash': generate_password_hash(password, method='scrypt:16384:8:1'),
              'generation': secrets.token_hex(24)}
    temporary = path.with_name('.audit-access-'+secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_access(path):
    try:
        if path.resolve() != path.absolute() or path.stat().st_mode & 0o077:
            return None
        with path.open() as stream:
            record = json.loads(stream.read(2048))
        if (set(record) != {'password_hash', 'generation'} or
            not re.fullmatch(r'[a-f0-9]{48}', record['generation']) or
            not re.fullmatch(r'scrypt:16384:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}', record['password_hash'])):
            return None
        return record
    except (OSError, ValueError, TypeError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure', 'revoke', 'status'])
    action = parser.parse_args().action
    if action == 'configure':
        if not os.isatty(0):
            raise SystemExit('Run interactively in your own terminal; do not pipe a password.')
        password = getpass.getpass('New dedicated audit password (hidden): ')
        if password != getpass.getpass('Repeat password (hidden): '):
            raise SystemExit('Passwords differ; nothing changed.')
        configure(ACCESS, password)
        print('Audit login enabled. Previous audit sessions are revoked. No restart needed.')
    elif action == 'revoke':
        ACCESS.unlink(missing_ok=True)
        print('Audit login disabled and all audit sessions revoked. No restart needed.')
    else:
        print('Audit login configured.' if load_access(ACCESS) else 'Audit login disabled.')
