"""Install identity-specific copies of the shared website skill."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
text=(root/'skill/SKILL.md').read_text()
for agent,dest in {
 'lychee':Path.home()/'.hermes/profiles/lychee/skills/mangosalad-pages/SKILL.md',
 'olive':Path.home()/'.openclaw/workspace/skills/mangosalad-pages/SKILL.md'
}.items():
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(text.replace('{{AGENT}}',agent).replace('{{VERSION}}',(root/'VERSION').read_text().strip()))
    print('Installed mangosalad-pages for '+agent)
