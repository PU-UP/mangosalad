"""Deploy a clean, committed checkout. Run only for explicitly authorized maintenance."""
from pathlib import Path
import json, sqlite3, subprocess, sys
root=Path(__file__).resolve().parents[1]
site=Path('/home/ubuntu/mangosalad-desk')
data=Path.home()/'.local/share/mangosalad/runtime'
def run(*args): return subprocess.check_output(args,cwd=root,text=True).strip()
if run('git','status','--porcelain'): raise SystemExit('Commit all changes before deployment')
run('python3','scripts/version.py','check')
with sqlite3.connect(data/'mango.sqlite') as db:
    if db.execute("SELECT 1 FROM tasks WHERE status IN ('running','dispatching','cancelling') LIMIT 1").fetchone():
        raise SystemExit('An Agent task is active; deploy after it finishes')
run('systemctl','--user','stop','mangosalad-tasks','mangosalad-desk')
try:
    for name in run('git','ls-files').splitlines():
        p=Path(name)
        if name in ('VERSION','AGENTS.md','requirements.txt') or p.parts[0]=='static' or len(p.parts)==1 and p.suffix in ('.py','.mjs'):
            target=site/p
            run('sudo','-n','install','-d','-o','root','-g','root','-m','755',str(target.parent))
            run('sudo','-n','install','-o','root','-g','root','-m','644',str(root/p),str(target))
    for source,name in [('mangosalad-desk.service','mangosalad-desk.service'),('systemd/mangosalad-tasks.service','mangosalad-tasks.service')]:
        (Path.home()/'.config/systemd/user'/name).write_text((root/source).read_text())
    run('python3','scripts/install-skills.py')
    (data/'release.json').write_text(json.dumps({'version':(root/'VERSION').read_text().strip(),'commit':run('git','rev-parse','HEAD')}))
    run('systemctl','--user','daemon-reload')
finally:
    run('systemctl','--user','start','mangosalad-desk','mangosalad-tasks')
print('Deployed '+(root/'VERSION').read_text().strip())
