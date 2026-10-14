"""Six-digit policy and account-wide persistent lockout using fixture credentials."""
import multiprocessing
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from audit_access import authenticate, configure


def attempt(access,state,password):
    return authenticate(Path(access),Path(state),password)[0]


def run():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);access=root/'access.json';state=root/'login.sqlite'
        pin='012345'  # Test fixture; not a production credential.
        for invalid in ['12345','1234567','１２３４５６','١٢٣٤٥٦','123 45',' 123456','123456\n','abc123',123456,None]:
            try:configure(access,invalid)
            except ValueError:pass
            else:raise AssertionError('Invalid PIN accepted')
        assert not access.exists()
        configure(access,pin)
        assert authenticate(access,state,pin)[0]=='ok'
        for wrong in ['12345','１２３４５６',123456,'000000']:
            with patch('audit_access.time.time',return_value=1000):
                assert authenticate(access,state,wrong)[0]=='denied'
        with patch('audit_access.time.time',return_value=1000):
            assert authenticate(access,state,'000000')==('locked',None,3600)
        with sqlite3.connect(state) as c:
            assert c.execute('SELECT failures,locked_until FROM audit_login').fetchone()==(5,4600)
        with patch('audit_access.time.time',return_value=1200):
            assert authenticate(access,state,pin)==('locked',None,3400)
            assert authenticate(access,state,'000000')==('locked',None,3400)
        with sqlite3.connect(state) as c:
            assert c.execute('SELECT failures,locked_until FROM audit_login').fetchone()==(5,4600)
        with patch('audit_access.time.time',return_value=4600):
            assert authenticate(access,state,'000000')[0]=='denied'
            assert authenticate(access,state,pin)[0]=='ok'
        with sqlite3.connect(state) as c:
            assert c.execute('SELECT failures,locked_until FROM audit_login').fetchone()==(0,0)
        for i in range(3):assert authenticate(access,state,'000000')[0]=='denied'
        assert authenticate(access,state,pin)[0]=='ok'
        assert authenticate(access,state,'000000')[0]=='denied'
        with sqlite3.connect(state) as c:
            assert c.execute('SELECT failures FROM audit_login').fetchone()==(1,)
        # Fresh processes cannot each obtain five guesses or lose prior state.
        configure(access,pin)
        context=multiprocessing.get_context('spawn')
        with context.Pool(8) as pool:
            outcomes=pool.starmap(attempt,[(str(access),str(state),'000000')]*8)
        assert outcomes.count('denied')==4 and outcomes.count('locked')==4,outcomes
        with context.Pool(1) as pool:
            assert pool.starmap(attempt,[(str(access),str(state),pin)])==['locked']
        with sqlite3.connect(state) as c:assert c.execute('SELECT failures FROM audit_login').fetchone()==(5,)
        access.unlink()
        assert authenticate(access,state,pin)[0]=='disabled'
        configure(access,pin)
        assert authenticate(access,state,pin)[0]=='ok'
    print('PASS audit PIN: ASCII/leading-zero policy, fifth-failure lock, expiry, reset, concurrency, cross-process persistence and revocation')


if __name__=='__main__':run()
