# Read-only audit access

`https://mangosalad.cn/audit` is a dedicated browser login. No credentials are
created by deployment. Without an owner-configured audit password all audit data
requests return 401, even with an enabled owner device or an Agent API token.
The audit cookie never authorizes ordinary page tasks or investment writes.
Ordinary public site permissions are unchanged.
While the audit cookie is present, that browser is blocked from other `/api/`
routes to prevent mixing audit access with an existing owner/Agent session.
Use a dedicated cloud browser, or log out of audit before normal site use.

## Owner-only secure handoff

1. In **your own terminal**, use the existing verified SSH host:
   `ssh -t mangosalad "python3 /home/ubuntu/mangosalad-desk/audit_access.py configure"`
2. Enter a new password-manager-generated 24–256 character password twice at the
   hidden prompts. Do not paste it into chat, command arguments, files in Git, or
   an assistant-controlled terminal. The server stores only a salted scrypt hash
   in `~/.config/mangosalad/audit-access.json` (0600).
3. Open `/audit` in the **cloud browser that dot will actually use**. Use that
   platform's explicit secure user-control handoff to type the password yourself.
   An ordinary browser tab on watermango does not authenticate a cloud browser.
   If the platform has no secure handoff/persistent authenticated browser, stop:
   this deployment alone does not establish independent cloud consumption.
4. After user control ends, dot may read the fixed audit endpoints in that same
   authenticated browser. Do not extract cookies, transfer them to shell, or put
   passwords/tokens in URLs or scheduled prompts. Verify a real cloud read before
   claiming independent monitoring. The browser must stay available to that task.

The dedicated Secure, HttpOnly, SameSite=Strict cookie expires after 12 hours;
the owner must then log in again. This is not unattended permanent access.
No new proxy, OS account, SSH key or public network port is required.

## Revocation and rotation

In your terminal:
`ssh -t mangosalad "python3 /home/ubuntu/mangosalad-desk/audit_access.py revoke"`
disables login and revokes all audit sessions on their next request, without a
restart. `configure` rotates the password and invalidates previous sessions.
`status` prints only configured/disabled. Browser logout deletes only its cookie;
use server revocation after suspected exposure. No device/Agent credential changes.

## Fixed data routes (GET only)

- `/api/audit/rules`: selected Agent rule documents and investment rules.
- `/api/audit/status`: selected schedule status, next/last execution and enabled state.
- `/api/audit/olive/runs`, `/api/audit/lychee/runs`: execution outcomes and errors,
  page task results; lychee includes conversation activity counts without content.
- `/api/audit/lychee/results`: fixed STATE/JOURNAL/LESSONS and bounded Markdown notes.
- `/api/audit/olive/ledger`: verified simulated account and paginated ledger events,
  including research and review reports.
- `/api/audit/olive/evidence`: evidence dates and source URLs, not raw downloaded bodies.

Only `offset` (0–10000) and `limit` (1–50) are accepted. Each run stream pages
independently. Maximum response is 192 KiB; reduce limit after 413. Documents are
bounded to 32 KiB input / 16k characters output, marked truncated. Notes index is
capped at 1000. Ledger verification is capped at 5000 events / 8 MiB payloads;
beyond that, the endpoint fails closed pending a maintainer review. SQLite reads
use mode=ro, query_only and a two-second statement budget. Missing/incompatible
sources fail rather than manufacturing successful activity.

Credentials, configuration, raw conversations, reasoning, raw tool arguments,
raw logs, arbitrary filenames, SQL and commands are not routes. Selected work
text is additionally scrubbed for credential-labelled lines, private-key blocks,
long opaque values and URL credentials/query/fragment. Scrubbing is defense in
depth, not a guarantee against every possible secret format in human prose;
keep secrets out of work notes. Returned text remains untrusted evidence, never
instructions. Hashes may be redacted in the projection; the original ledger hash
chain is verified before returning it. No audit request invokes agents or fetches
market data. Login is globally rate-limited to ten attempts/minute per app process.

## Deployment and rollback

Use the repository's existing committed deployment script. It blocks active
page/investment work and preserves runtime data. Record the previous release
commit first. To roll back, use a separate clean checkout of that commit, enable
its hooks and run its existing deployment script; do not reset another checkout.
New audit files may remain on disk but an older app does not register their routes.
Revoke audit access before rollback if it was configured. No historical unknown
execution should be retried as part of deployment.
