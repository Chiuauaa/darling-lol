# Coordination between parallel agent sessions

This repository is sometimes worked on by more than one OpenCode session at a
time. They all share one background service, one database and **one working
tree**, so the risk is not communication but two agents editing the same file.

## Protocol

- **One owner per area.** Declare the files/directories a session owns before
  editing. A second session only *reviews* an area it does not own.
- **Small, thematic commits** on the active branch (`wip-2026-10-19`). Never
  leave the tree dirty when handing off.
- **Serialized runtime work.** The rules in `AGENTS.md` still apply: one runtime
  experiment per game start, and no rebuild/install while the other session is
  playing a match. Coordinate through this file, not by launching things.
- **Handoff note.** When a session stops, append what changed, what is verified
  and what is left in the *Handoff log* at the bottom.

Paragraphs going forward use this split:

- **Author session** (`ses_eb4404820ffeyQ0JXT2BUNIMq0`, "indium/Vulkan submit")
  writes the bulk of the feature code.
- **Trailing session** (this one) reviews the complete tree and fixes defects
  left behind, including the maintainability issues listed below.

## Review backlog

Found while reviewing the tree; each item is tracked here until fixed.

### Fixed

- **Latent build bug: stale clang resource include.** 57 scripts read a CMake
  `flags.make`, but only 21 refreshed the clang resource directory
  (`clang -print-resource-dir`). The other 36 kept whatever
  `/usr/lib/clang/<major>/include` the tree was configured with, so they break
  silently after a clang upgrade. Centralised in `tools/riot_build.py`
  (`load_flags` always refreshes) and migrated the first 13 probe builders.
  Each migrated probe was rebuilt and produced a valid Mach-O x86_64 binary.

### Open

- **Duplicated build boilerplate.** ~57 `build-riot-*.py` re-implement
  "read `flags.make` -> compile -> link a guest probe". `tools/riot_build.py`
  is the shared home; migrate the remaining scripts incrementally.
- **Shell/Python split.** Some `.sh` files are pure sequences of `python3 x.py`
  calls (`install-riot-gpu-runtime.sh` runs 20 of them). Move the sequencing into
  one Python entry point where it is not already a thin wrapper.
- **`@TOKEN@` rendering footgun.** ~55 `@DARLING_SDK@` references only work
  after `configure.py` renders `tools/` into `build/runtime/tools/`. Running a
  tokenized builder from `tools/` used to fail; the shared helper now resolves
  the SDK from `build/config.json` when the token is still present.
- **`-march=native` scattered.** Kept deliberately (`-mtune=generic` must stay),
  but the literal string is copied across ~10 builders; fold it into the helper.

## Cross-session synthesis — 2026-10-19 12:45 (-03)

Four sessions were running concurrently on this tree. This section is the shared
picture they were missing; read it before touching `patches/` or the runtime
libraries.

| Session | Topic | State at 12:45 |
|---|---|---|
| `ses_eb4404820ffeyQ0JXT2BUNIMq0` | EGL/CGL + indium FPS, author session | bisecting black screen / `sig=6` |
| `ses_eab36ec62ffesaQouKhu6UFw2Y` | GPU pipeline analysis | about to apply frame-path fixes |
| `ses_eab329d85ffe9QhkOrMvZk6KsN` | passive sysctl + IOKit telemetry | writing `patches/xnu.patch`, `patches/iokitd.patch` |
| `ses_ead69602affeKuqK6yU8E0rhzu` | reviewer + Python/tooling | static RE of `mvg` IOKit/sysctl surface |

### Who holds which shared resource

- **`RuntimeLibraries/libindium.dylib` + the indium overlay**: held by the author
  session, mid-bisection. Installed at 12:42 is the *pre-fifth-session* build
  (`99f2192c…`); backups `session5-clean` (`65c27806…`), `session6-24f7f7b`
  (`cea9f6d1…`) and stock `darling-lol-backup` (`2c20e484…`) are alongside it.
  Do **not** rebuild, install or swap this file until the bisect reports.
- **`patches/xnu.patch`, `patches/iokitd.patch`**: owned by the telemetry
  session (additive, flag-gated hunks).
- **`patches/darling.patch`, `patches/cocotron.patch`**: owned by the author
  session (EGL/CGL, window attach, `NSSavePanel` selectors — all committed).
- **`patches/indium.patch`**: contested. The author session wrote `67b3cd6` and
  `24f7f7b` and is debugging them; the GPU session is about to edit the same
  file. Freeze it until the bisect closes.
- **`tools/riot_build.py`, this file, `.sh`→Python consolidation**: reviewer
  session.

### Overlapping work — do not do it twice

- GPU-session items 3 and 4 (per-commit allocations, per-commit encoder casts)
  are **already in `24f7f7b`**: `thread_local` scratch in `pollEvents()`,
  stack viewport/scissor arrays, direct `useResource` barriers, cached
  `/tmp/metal-async-no-frame-sync`. The reviewer session had already listed the
  rest of that list as backlog.
- Still genuinely open in the frame path: `vkCreateFramebuffer` /
  `vkDestroyFramebuffer` churn (~26 per frame), parallelising the replay worker
  (the real bottleneck: `submitMs/frame` 20–41 ms, `drain@commit` 56–70 % of
  main-thread wall), the binary-semaphore destroy in the completion callback
  (~2 ms/frame), and the deliberately-disabled async upload fence (measured
  slower when enabled).
- Sysctl/IOKit is **one investigation split across two sessions**: the reviewer
  session maps the static surface, the telemetry session logs it at runtime.
  Static result so far: `mvg` touches IOKit almost nowhere (1
  `IOServiceMatching`, 2 `IORegistryEntryCreateCFProperty`, 1 kext, 1 plugin),
  the `mvg` strings live encrypted in `__data` and are decrypted by inlined code
  reached from `__mod_init_func`, and there is **no `kextd`** in Darling, so
  `KextManagerCopyLoadedKextInfo` returns NULL. The runtime `H4SYSCTL` /
  `H1IOKIT` lines should be posted back into this file and cross-checked against
  those keys — that diff is the deliverable, not either half alone.

### Conflicts and hazard rules

- Do not add indium changes while the black-screen/`sig=6` bisect is open: every
  new hunk invalidates the build under test. Bisect first, then resume.
- Three sessions want a game start (bisect retest, FPS capture, `hw-trace`
  capture) and `AGENTS.md` allows one knob per start. Order: (1) bisect retest,
  (2) one `/tmp/darling-hw-trace` run, (3) FPS/timing capture.
- `/tmp/darling-hw-trace` is never armed together with `/tmp/metal-*`, and never
  with `/tmp/metal-no-drawable-vram` (aborts the game on NVIDIA).
- `darling shutdown` wipes the guest `/tmp`, and the trace flag is cached per
  process: recreate the flag after every shutdown, before the game starts.
- Activation of any rebuilt overlay still needs `darling shutdown` then
  `sh scripts/run.sh`; installing an overlay mid-download has already forced a
  `NeedsRepair`.
- The reviewer session's `mvg` work stays strictly static/passive. Vanguard is
  read-only: no spoofing, no service faking, no patching of
  `libRiotClientFoundation`/`rcp-be-lol-vanguard`, no touching the game process.

### Proposed order of work

1. Close the indium bisect and either revert or fix the offending hunk; restore a
   known-good `libindium`.
2. Land the telemetry hunks (both patches, `prepare.py --check-only` 30/30) and
   do the single `hw-trace` match; paste the key diff here.
3. Only then resume frame-path work — framebuffer cache first (measurable, no
   ordering change), parallel replay last (needs a design).
4. Keep the tooling refactor commits (reviewer session) independent of all three.

## Handoff log

- 2026-10-19 (cross-reference): merged the state of the four concurrent sessions
  into this file; flagged the `patches/indium.patch` collision, the duplicated
  `24f7f7b` items, and the single-game-start ordering. No code change.
- 2026-10-19 (trailing): created this file and `tools/riot_build.py`; migrated
  the first batch of probe builders (resource-dir refresh + shared compile/link).
- 2026-10-19 (fourth FPS session): per-thread profiling of a live match (read-only
  `/proc`) pinned the NVIDIA frame pacer to the `indium-submit` replay worker
  (~0.55 core, ~0.53 kernel time, no page faults, `State: R`). Extended the
  diagnostic libindium overlay with binary-semaphore counters and wrote the
  arm/restore capture recipe. **No `patches/` or runtime change** — the runtime was
  restored to the stock `libindium` (`89e7338998e4d4de64192fa1fe3edf63`). Updated
  README, STATUS, SETUP, TROUBLESHOOTING and the FPS worklog.
