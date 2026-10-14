# mangosalad

A self-hosted desk for persistent checklists, interactive canvas pages and whole-page Agent assignments. lychee is a Hermes profile; olive uses the existing OpenClaw gateway. No default daily notifications.

The separately authorized olive paper-investing experiment lives at `/invest`; its two trading-day reports are opt-in at deployment. See [INVESTING.md](INVESTING.md) for approved rules, evidence exports, validation and maintenance. It reuses SQLite and the serial worker; lychee's assignments are unchanged.

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

## Investment data failure handling

During an active investment run, market requests are admitted at most eight times,
with at most two failures for the same normalized query, and stop after three failed requests.
Successful refreshes do not count as failures. Concurrent duplicates are told to
wait for the current request; this is not recorded as a failed data fetch.
After six minutes (or two minutes before the existing report deadline), further
market fetches are refused so the Agent has time to submit and confirm its report.
`ok`, `quotes`, `candidates`, `errors`, and `stop_market` are always present in the
market business response. Partial quotes remain distinct from per-symbol errors.
The Agent must use existing verified evidence, or explicitly report insufficient
data with no orders; the server does not invent research or retry the whole run.

Request accounting uses a separate `invest_market_requests` table with atomic
admission. Diagnostics contain fixed source labels, error categories and HTTP
status codes, never upstream response bodies, credential values or URL queries.
They are also available in the existing authenticated olive runs audit projection.
This table is additive; rollback to an earlier release can leave it unused.
Settlement uses its original collector and unchanged trading/valuation rules.
The six-minute gate applies to new market calls, not to arbitrary Agent tools;
prompt/skill instructions also require stopping searches and other collection.
An Agent that ignores those instructions can still fail to submit, which remains
an explicit failed run rather than a fabricated successful report.
