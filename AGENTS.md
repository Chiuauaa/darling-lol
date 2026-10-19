# AGENTS.md

Conventions for AI agents working in this repository.

## Memory and documentation
- Whenever a new feature/functionality is added, update the architecture section in `README.md`.
- Whenever project conventions or style rules change, update this `AGENTS.md` automatically.

## Source changes
- Source changes live in `patches/` (one patch per repository); apply them with `scripts/prepare.py`. Never reset a checkout to make a patch apply.
- Keep each patch applicable to its pinned revision (correct `@@` hunk headers).

## Runtime experiments
- Test runtime/knob toggles one at a time, one per game start. Arming several at once once made a whole session's play fail with an unrelated abort.
- `/tmp/metal-no-drawable-vram` aborts the game on NVIDIA (crash-loop at Metal resource creation); it is a RADV-only experiment. See `docs/SETUP.md` and `docs/TROUBLESHOOTING.md`.
- Activating a rebuilt framework overlay needs `darling shutdown` then `sh scripts/run.sh`.

## Anti-cheat (Vanguard)
- Treat Vanguard as read-only. Never spoof it, fake its service, patch `libRiotClientFoundation`/`rcp-be-lol-vanguard`, or touch the game process (no memory read/write, no injection, no input automation, no `SIGSTOP`/`SIGCONT`).
- The client reporting the platform unsupported (`VAN -101`, `Failed getting installed version of Vanguard: Unsupported operating system`) is expected here, not a bug to fix. See `docs/VANGUARD.md`.

## Secrets
- Never print `remotingAuthToken`, `--remoting-auth-token`, `--riotclient-auth-token`, `machineId` or account data. LCU logs repeat the token as a session id in many lines — redact by value, not by field name.
- Tokens can be shorter than a generic length filter expects (a 22-character `--riotclient-auth-token` slipped past a 32+ filter once). Never dump whole log lines or `grep` without a fixed `cut -c1-N`, and never echo a process command line that carries auth arguments.
