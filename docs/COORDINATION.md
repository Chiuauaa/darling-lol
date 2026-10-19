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

## Handoff log

- 2026-10-19 (trailing): created this file and `tools/riot_build.py`; migrated
  the first batch of probe builders (resource-dir refresh + shared compile/link).
- 2026-10-19 (fourth FPS session): per-thread profiling of a live match (read-only
  `/proc`) pinned the NVIDIA frame pacer to the `indium-submit` replay worker
  (~0.55 core, ~0.53 kernel time, no page faults, `State: R`). Extended the
  diagnostic libindium overlay with binary-semaphore counters and wrote the
  arm/restore capture recipe. **No `patches/` or runtime change** — the runtime was
  restored to the stock `libindium` (`89e7338998e4d4de64192fa1fe3edf63`). Updated
  README, STATUS, SETUP, TROUBLESHOOTING and the FPS worklog.
