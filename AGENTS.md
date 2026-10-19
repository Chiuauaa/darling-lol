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
- Diagnostic-only `libindium` overlays (thread naming plus worker/polling/`binarySem` counters) are built **outside** the tree and never committed to `patches/`; a capture ends by restoring the stock `libindium` (`89e7338998e4d4de64192fa1fe3edf63`). The capture/rollback recipe and the overlay's flags are in the FPS worklog and `docs/TESTING.md`.

## Coordinating parallel sessions
- Several sessions can work on this tree at once, sharing one background service, one database and one working tree. The canonical channel is `docs/COORDINATION.md`: declare the area a session owns, log what changed, and read the *Cross-session synthesis* section before touching `patches/` or the runtime libraries.
- A message can be delivered into another session with `opencode run -s <sessionID> "<text>"`. It enqueues a normal user turn, delivered at the next turn boundary — it never cuts a running step, and it does not change the session's agent, model or variant. Observed side effects: it becomes a user turn that competes with the human's next prompt, it can trigger a context compaction on a large session, and it costs tokens.
- Delivery discipline: send only when that session is idle, prefix the text with `[coordenação]`, state explicitly that it does not change that session's task, ask exactly one question, and never ask for a build, an install or a game start from a session you do not own. One message per session per issue.
- Only one session owns a contested file at a time. When a bisect or a runtime capture is open, the file and the runtime library under test are frozen for everyone else.
- One session is the **implementer of record** (declared in `docs/COORDINATION.md`, *Roles*): every change to `patches/` and to a runtime overlay is written by it, or handed to it with a scoped spec by the coordinator. Analysis sessions propose; the implementer writes.
- Sessions working on telemetry must not arm each other's flags, and the one-knob-per-game-start rule below applies across sessions, not just within one.

## Anti-cheat (Vanguard)
- Treat Vanguard as read-only. Never spoof it, fake its service, patch `libRiotClientFoundation`/`rcp-be-lol-vanguard`, or touch the game process (no memory read/write, no injection, no input automation, no `SIGSTOP`/`SIGCONT`).
- The client reporting the platform unsupported (`VAN -101`, `Failed getting installed version of Vanguard: Unsupported operating system`) is expected here, not a bug to fix. See `docs/VANGUARD.md`.

## Secrets
- Never print `remotingAuthToken`, `--remoting-auth-token`, `--riotclient-auth-token`, `machineId` or account data. LCU logs repeat the token as a session id in many lines — redact by value, not by field name.
- Tokens can be shorter than a generic length filter expects (a 22-character `--riotclient-auth-token` slipped past a 32+ filter once). Never dump whole log lines or `grep` without a fixed `cut -c1-N`, and never echo a process command line that carries auth arguments.
