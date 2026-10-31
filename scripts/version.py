"""One monotonically increasing semantic version for every commit."""
import re, subprocess, sys
from pathlib import Path

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

def version(s):
    if not re.fullmatch(r'\d+\.\d+\.\d+',s): raise ValueError('VERSION must be X.Y.Z')
    return tuple(map(int,s.split('.')))

mode=sys.argv[1]
if mode=='bump':
    head=subprocess.run(['git','rev-parse','--verify','HEAD'],capture_output=True,text=True)
    current=Path('VERSION').read_text().strip()
    if head.returncode==0:
        previous=git('show','HEAD:VERSION'); old=version(previous)
        if version(current)<=old: current=f'{old[0]}.{old[1]}.{old[2]+1}'
    version(current)
    Path('VERSION').write_text(current+'\n')
    subprocess.run(['git','add','--','VERSION'],check=True)
elif mode=='message':
    p=Path(sys.argv[2]); message=p.read_text()
    message=re.sub(r'^\[v\d+\.\d+\.\d+\]\s*','',message)
    p.write_text('[v'+git('show',':VERSION')+'] '+message)
elif mode=='check':
    for commit in git('rev-list','--reverse','HEAD').splitlines():
        value=version(git('show',commit+':VERSION'))
        parents=git('show','-s','--format=%P',commit).split()
        parent_versions=[version(git('show',parent+':VERSION')) for parent in parents]
        subject=git('show','-s','--format=%s',commit)
        if len(parents)>1:
            # GitHub merge commits keep the branch tip VERSION; require not below any parent.
            assert parent_versions and value>=max(parent_versions), 'Merge version below a parent: '+commit
            assert subject.startswith('[v'+'.'.join(map(str,value))+'] ') or subject.startswith('Merge '), 'Missing version in merge message'
        else:
            for parent_version in parent_versions:
                assert value>parent_version, 'Version did not increase: '+commit
            assert subject.startswith('[v'+'.'.join(map(str,value))+'] '), 'Missing version in message'
    print('Version history verified')
else: raise SystemExit('Use bump, message or check')
