# mangosalad

A self-hosted desk for persistent checklists, interactive canvas pages and whole-page Agent assignments. lychee is a Hermes profile; olive uses the existing OpenClaw gateway. No default daily notifications.

## Version and maintenance

Read [AGENTS.md](AGENTS.md) before changing code. [VERSION](VERSION) is the source version; deployed VERSION and runtime release.json identify the installed release.

```sh
sh scripts/setup-git.sh
# edit and validate the authorized change
python3 test_app.py
python3 test_tasks.py
python3 test_reminders.py
git add <specific-code-files>
git commit -m "Describe the change"
git push origin main
```

Each commit automatically increases the patch version unless a greater version was explicitly supplied. Its message includes [vX.Y.Z]. CI verifies every commit's version. Each fresh clone must install hooks; Git does not automatically enable cloned hooks. Do not bypass hooks or use automated squash messages without the version prefix. Tags name stable releases.

## Separation of code and data

| Location on the current server | Purpose |
| --- | --- |
| ~/mangosalad-source | Git checkout; maintenance only |
| ~/mangosalad-desk | Deployed code, root-owned to prevent accidental Agent writes |
| ~/.local/share/mangosalad/runtime | Database, private delivery settings, task execution output, release record |
| ~/.local/share/mangosalad/backups | Database and historical deployment backups |
| ~/.config/mangosalad | Private per-Agent local API tokens |

Compatibility links data/ and backups/ in the deployed directory point outside it. Dependencies and Python caches are untracked. No production data, keys, personal conversations or generated pages belong in Git. Canvas HTML is database content. Existing daily SQLite backups are independent of source history; code rollback does not restore data.

Normal Agent use goes through mango.py / the local API and leaves git diff clean. The shared skill is rendered separately for lychee and olive by scripts/install-skills.py, embedding the release version and the correct identity. Identity instructions and local API inbox checks prevent accidental cross-Agent use; both Agents currently share the same OS account, so these are not adversarial isolation boundaries. Do not use elevated privileges to bypass deployed code protection without explicit maintenance authorization.

## Deployment

Existing runtime: Python Flask/Gunicorn on localhost:5010, Nginx TLS proxy, user services mangosalad-desk and mangosalad-tasks. This repository's paths target the existing server; it is not a general-purpose installer. deploy.sh is the historical first-time proxy setup, not the update command.

After reviewing and committing a change, authorized maintainers run:

```sh
python3 scripts/deploy.py
```

The script refuses dirty source or active tasks, installs root-owned code, renders both skills, records the deployed commit, and restarts the site and dispatcher. Keep prior tags/commits for code rollback; use a separate clean checkout of the chosen version and run the same deployment command. Do not run two deployments concurrently.

The dispatcher checks due work every five seconds and runs serially. A scheduled time starts processing, not second-accurate message delivery. Agent acknowledgement precedes the running state; results persist and are sent through that Agent to the configured owner chat. Interrupted work is not automatically retried. Cancellation cannot undo earlier side effects. The old per-item timer is disabled.

OpenClaw stop_olive.mjs uses the installed official gateway-runtime SDK to stop only mangosalad task sessions. Revalidate it after OpenClaw upgrades. Hermes/OpenClaw themselves, their full configuration and their memories are not vendored here.

The current website is public by owner choice (MANGO_PUBLIC=1). Dispatching Agent work requires owner-device activation. Keep credentials out of repository and browser content.
