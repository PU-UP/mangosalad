"""Keep seven daily, consistent snapshots of this site's data only."""
from pathlib import Path
import sqlite3
from datetime import datetime
import os

os.umask(0o077)
root=Path.home()/'.local/share/mangosalad'
folder=root/'backups/data'
folder.mkdir(parents=True,exist_ok=True)
source=sqlite3.connect('file:'+str(root/'runtime/mango.sqlite')+'?mode=ro',uri=True)
target=folder/(datetime.now().strftime('%Y-%m-%d')+'.sqlite')
with sqlite3.connect(target) as dest:
    source.backup(dest)
source.close()
for old in sorted(folder.glob('????-??-??.sqlite'))[:-7]:
    old.unlink()
print('Website data snapshot saved.')
