# Mangosalad maintenance contract

Applies to every Agent working in this repository or its deployed copy.

## Normal use
- Creating or editing a checklist, canvas, task, or reminder is DATA work. Use mango.py / the existing API only. Canvas HTML belongs in database content, not static/.
- Do not edit source, Git metadata, services, skills, hooks, or permissions during normal use. Do not commit or deploy without an explicit user request to maintain this software.
- Keep drafts in /tmp or the Agent's own workspace; runtime data lives outside this checkout.
- lychee is the Hermes profile; olive is the OpenClaw main Agent. Use only your own installed skill identity and task inbox. Do not modify mango.

## Explicitly authorized maintenance
- Read this file, VERSION and git status first. Check the deployed VERSION separately; a source commit does not mean it was deployed.
- Work from the current main branch. Never reset, overwrite or force-push another Agent's work. Do not share a writable checkout concurrently.
- Run `sh scripts/setup-git.sh` in each clone. Each commit increments VERSION; commit messages include [vX.Y.Z]. Hooks enforce this locally and CI checks the history. Do not bypass hooks.
- Never stage runtime data, credentials, conversations, owner identifiers, or copied production configuration. Inspect the staged diff before commit.
- Validate affected behavior, then deploy only when the user authorized deployment. Deployment uses the existing runtime directory and keeps data intact.
- Root-owned deployed code blocks accidental writes. Never use sudo/chmod/chown to bypass that boundary for ordinary user tasks. Elevation is for explicitly authorized maintenance only.
