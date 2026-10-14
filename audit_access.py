"""Owner-operated audit password setup. Never prints a password or hash."""
import argparse
import getpass
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent/'vendor'))
from werkzeug.security import generate_password_hash, check_password_hash

ACCESS = Path.home()/'.config/mangosalad/audit-access.json'


def configure(path, password):
    if not isinstance(password, str) or not re.fullmatch(r'[0-9]{6}',password):
        raise ValueError('Use exactly six ASCII digits (0–9); leading zeroes are preserved.')
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


def authenticate(access_path, state_path, password):
    """Serialize password checks with a durable account-wide lockout record."""
    config = load_access(access_path)
    if not config:
        return 'disabled', None, 0
    if state_path.resolve()!=state_path.absolute():
        raise OSError('Invalid authentication state path')
    try:
        fd=os.open(state_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
    except FileExistsError:
        pass
    c=sqlite3.connect(state_path,timeout=10)
    try:
        c.execute('PRAGMA synchronous=FULL')
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS audit_login (account INTEGER PRIMARY KEY CHECK(account=1), generation TEXT NOT NULL, failures INTEGER NOT NULL, locked_until REAL NOT NULL)')
        generation=hashlib.sha256(config['generation'].encode()).hexdigest()
        row=c.execute('SELECT generation,failures,locked_until FROM audit_login WHERE account=1').fetchone()
        now=time.time()
        if not row or row[0]!=generation:
            failures,locked_until=0,0
        else:
            failures,locked_until=row[1:]
        if locked_until>now:
            c.commit()
            return 'locked',None,math.ceil(locked_until-now)
        if locked_until:
            failures,locked_until=0,0
        valid=isinstance(password,str) and re.fullmatch(r'[0-9]{6}',password)
        if valid and check_password_hash(config['password_hash'],password):
            failures,locked_until=0,0
            result='ok'
        else:
            failures+=1
            locked_until=now+3600 if failures>=5 else 0
            result='locked' if locked_until else 'denied'
        c.execute('INSERT OR REPLACE INTO audit_login VALUES(1,?,?,?)',(generation,failures,locked_until))
        c.commit()
        return result,config['generation'] if result=='ok' else None,3600 if locked_until else 0
    finally:
        c.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure', 'revoke', 'status'])
    action = parser.parse_args().action
    if action == 'configure':
        if not os.isatty(0):
            raise SystemExit('Run interactively in your own terminal; do not pipe a password.')
        try:
            password = getpass.getpass('New six-digit audit PIN (hidden; leading zeroes allowed): ')
            if password != getpass.getpass('Repeat PIN (hidden): '):
                raise ValueError('PINs differ; nothing changed.')
            configure(ACCESS, password)
        except ValueError as error:
            raise SystemExit(str(error))
        except (EOFError,KeyboardInterrupt):
            raise SystemExit('Cancelled; configuration was not completed.')
        except OSError:
            raise SystemExit('Could not save audit configuration; check the account and directory permissions.')
        print('Audit login enabled. Previous audit sessions are revoked. No restart needed.')
    elif action == 'revoke':
        ACCESS.unlink(missing_ok=True)
        print('Audit login disabled and all audit sessions revoked. No restart needed.')
    else:
        print('Audit login configured.' if load_access(ACCESS) else 'Audit login disabled.')
