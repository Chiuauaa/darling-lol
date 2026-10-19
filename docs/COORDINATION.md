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

### Update 12:52 (-03) — coordinator

- Bisect result (author session): the *pre-fifth-session* overlay **loads**, so the
  black screen / `sig=6` is a regression from the 5th/6th indium hunks, not a
  pre-existing crash. Next test needs a `darling shutdown` + `run.sh` with
  `session5-clean` installed.
- The GPU session had already begun editing `patches/metal--deps--indium.patch`
  (first hunk: `presentationSemaphores` → `static thread_local`) when this was
  written. That file is frozen until the bisect closes; the change is on the
  *already-suspect* 6th-session code path.
- Crash forensics from the author session: game process SIGSEGV in
  `libobjc.A.dylib:objc_msgSend_stret` (offset `0x4089d`, zero isa) during the
  loading screen; the same signature recurs on 10-17/10-18 across older builds,
  so it is not automatically attributable to today's hunks.

### Roles (set 12:57)

- **`ses_eb4404820ffeyQ0JXT2BUNIMq0` ("Debug 6") is the implementer of record.**
  Every change to `patches/` and to a runtime overlay goes through it, or is
  handed to it by the coordinator. Analysis sessions propose; Debug 6 writes.
- **Coordinator** (the session that owns this section): reads all sessions,
  arbitrates contested files, owns the game-start/freeze calendar, and relays a
  code request to Debug 6 only when there is a decided, scoped change to make.
- **Analysis sessions** (`ses_eab36ec62…` GPU frame path, `ses_eab329d85…`
  telemetry, `ses_ead69602a…` reviewer/static RE) do not land runtime code
  themselves; they hand a spec, a diff or a validated hunk to Debug 6.
- Exception that stands until revoked: the telemetry session keeps authorship of
  its own `patches/xnu.patch` + `patches/iokitd.patch` hunks, because they are
  self-contained, already validated (`--check-only` 30/30) and Debug 6 has
  reviewed them. Any further change to those two files still goes to Debug 6.

### Update 13:02 (-03) — coordinator

Cross-reference of the GPU pull analysis with the rest of the tree. The archived
numbers (FPS 27.8, `commits/frame` 23.9, `submitMs/frame` 25.4 ms on the worker,
36 ms frame, `drain@commit` 58 % of the main thread's wall, worker 0.52–0.71 core
with ~0.55 in `sys`, ~1 `vkQueueSubmit2`/frame, GPU 1–30 % at P5) give a measured
ceiling of **≈664 commits/s = FPS × commits/frame**.

Arithmetic that drives the priority: 60 FPS at 23.9 commits/frame needs ~1434
commits/s, i.e. **2.16× the ceiling**. Trimming the fixed per-commit cost — which
is what the 5th/6th/7th indium hunks do, and which the bisect currently blames for
the black screen — cannot get there alone. Only two families can: **parallel
replay** (capped at 2 workers: the host is an i3-8100, 4 threads, no SMT) and
**fewer commits/frame** (coalescing in the batch/replay layer). Per-commit work is
therefore a data point, not the plan.

Consequences recorded in the queue handed to the implementer: close the bisect
first, keep the 7th-session hunks as a separate later commit, attribute the worker's
`sys` time with one `/tmp/metal-debug-timing` capture before choosing between the
two families, only then evaluate the framebuffer cache (~26 create/destroy per
frame) from measured cost, and design — not code — the two-worker replay.

Sequencing of game starts stands: (1) bisect with `session5-clean`, (2) telemetry
`/tmp/darling-hw-trace` capture, (3) FPS/timing capture.

### Update 13:08 (-03) — coordinator, correcting the 13:02 note

The GPU session measured the two things the 13:02 note had left as candidates.
Results, which supersede that note:

- **Framebuffer cache is not a lever.** `vkCreateFramebuffer` + `vkDestroyFramebuffer`
  costs 0.10 µs wall / 0.06 µs CPU per pair on driver 580 (microbench
  `build/fps-diag/vk-kernel-bench`, host GPU): ~2.6 µs/frame at ~26 passes. Removed
  from the queue; it was the one item the 13:02 note had kept "until measured".
- **There is no core to give a second replay worker.** In the same match the game
  used 0.94 core (worker 0.65 + main 0.265 + poll/batch 0.03), and the box sat at
  ~3.7 of 4 threads: the Riot client's Chromium helpers ~1.7 core, `darlingserver`
  ~0.3, desktop ~0.3. Free headroom: **~0.25 core**. Parallel replay is therefore
  not a viable next step on this host; the main thread blocked in `drain@commit`
  frees nothing (it is blocked, not idle-CPU).
- **Replay units are ~22/frame.** `encCreate ≈ 0.92 × commits`, one render pass per
  command buffer, so batching (which merges submits, not replay units) is worth
  only ~1.09× (28 → ~30 FPS). 60 FPS at the measured ~664 commits/s ceiling needs
  `commits/frame ≤ 11`, which only command-buffer merging — a synchronization-model
  change — can produce.
- **Per-commit attribution is still open.** The only per-commit suspect with a
  counter is the binary semaphore (0.054 core); ~0.45 core of the worker's `sys`
  is unattributed because that capture had no `phases@` lines. The gating
  measurement is one `/tmp/metal-debug-timing` capture with those sections armed.

Revised queue for the implementer: (1) close the bisect, (2) land or drop the
7th-session hunks as their own commit, (3) the `phases@` timing capture — this is
what decides the next move, (4) only then choose between reclaiming non-game CPU
and merging command buffers, (5) framebuffer cache dropped.

### Who holds which shared resource

- **`RuntimeLibraries/libindium.dylib` + the indium overlay**: held by the author
  session, mid-bisection. Installed at 12:42 is the *pre-fifth-session* build
  (`3df22735…`, md5); backups `session5-clean` (`2909b341…`),
  `session6-24f7f7b` (`8acea7f3…`) and stock `darling-lol-backup` (`89e73389…`)
  are alongside it. Build ids are **md5 sums**, not sha256 — an earlier revision
  of this table quoted sha256 prefixes and was wrong. Do **not** rebuild, install
  or swap this file until the bisect reports.
- **`patches/xnu.patch`, `patches/iokitd.patch`**: owned by the telemetry
  session (additive, flag-gated hunks).
- **`patches/darling.patch`, `patches/cocotron.patch`**: owned by the author
  session (EGL/CGL, window attach, `NSSavePanel` selectors — all committed).
- **`patches/indium.patch`**: contested, frozen until the bisect closes. The author
  session wrote `67b3cd6` and `24f7f7b`; the GPU session applied three hunks in the
  working tree (`presentationSemaphores` and `extraWaitSemaphores` →
  `static thread_local`, one `dynamic_pointer_cast` → `else if`) and stopped there
  — unbuilt, untested, uncommitted. The implementer of record decides whether they
  survive, as their own commit after the bisect.
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

### Graphics-API research consolidated (2026-10-19, research session)

A standalone reference now lives in [`docs/GRAPHICS-STACK.md`](GRAPHICS-STACK.md): the
API model of OpenGL / Vulkan / Metal side by side, the five translation layers in play
and **which direction each one runs**, Darling's Mach-O -> ELF bridge (`mldr`,
`wrapgen`) as the reason host EGL/X11 is reachable at all, the two present paths in this
tree, and the Vulkan/GL external-object handoff used to present a Metal frame. It is
read-only knowledge: no patch, no overlay and no game-start policy changed.

What it changes for the sessions already in flight (each item is *context*, not a new
task, and none of them arms a flag or starts a game):

- **Implementer of record / indium bisect.** The measured cost of the frame path
  (`indium-submit` ~0.53 core of *kernel* time, `drain@commit` on the presenter) is the
  expected cost of replaying Metal's serialized encoder order into Vulkan, i.e. driver
  entries and submissions, not allocation or compute. The two mechanisms that attack it
  are the open items already on the list — framebuffer cache first, parallel replay
  last — and, on the presentation boundary, timeline semaphores (`MTLSharedEvent`-style
  counter waits) instead of a binary semaphore created and destroyed per commit. That
  last one is a *design* note; it is not a request to add a hunk while the bisect is open.
- **GPU frame-path session.** Indium requires Vulkan 1.3 or
  `VK_EXT_extended_dynamic_state`/`2` plus timeline semaphores, and it is the mirror of
  MoltenVK: shaders travel Metal/AIR -> SPIR-V through Iridium, so a shader bug surfaces
  as an Iridium translation issue, not a SPIR-V-to-MSL one. The MoltenVK guide's
  three-swapchain-images limit is the external confirmation of why a drawable that is
  not recycled in time produces `Metal Device timed out`.
- **Telemetry session.** Nothing to add at run time from this research; the H4/H1
  surface is unrelated to the graphics API model.
- **Reviewer session.** `winevulkan` is the closest solved analogue to Indium and
  documents the two traps worth mirroring in review: dispatchable handles must be
  wrapped, and struct layouts must be converted, not memcpy'd.

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

- 2026-10-19 (research session): added `docs/GRAPHICS-STACK.md`, a consolidated
  reference for how OpenGL, Vulkan and Metal work and where each translation layer sits
  (MoltenVK backwards, Indium forwards, DXVK/vkd3d-proton, wined3d, ANGLE), together
  with the Darling ELF-bridge and overlay-restart constraints and the two present paths
  in this tree. Sources are primary (Khronos/MoltenVK docs, `darlinghq/indium`,
  darling-docs internals, Wine `winevulkan`/`winex11.drv`/`wined3d` sources, Proton,
  DXVK, vkd3d-proton, ANGLE). **No code, patch, overlay or runtime change**; the
  indium freeze, the one-knob-per-game-start rule and the game-start queue are
  untouched. Cross-referenced from the *Cross-session synthesis* section.

- 2026-10-19 (coordinator, 12:55): delivered one cross-session message to each of
  the four sessions via `opencode run -s` (queued as a user turn; no build, no
  install, no game start requested). Replies: author session registered its
  bisect state and corrected the build-id table (md5, not sha256); telemetry
  session reported H4/H1 hunks written and validated (`prepare.py --check-only`
  30/30, `validate.py` PASS) and will capture after the bisect frees the game
  start; reviewer session confirmed it stays strictly static; GPU session had
  already applied three hunks to `patches/metal--deps--indium.patch`
  (`presentationSemaphores` and `extraWaitSemaphores` → `static thread_local`,
  one `dynamic_pointer_cast` → `else if`) before the freeze arrived and has not
  built, installed or tested them. The message-delivery conventions are now in
  `AGENTS.md` (*Coordinating parallel sessions*).

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
- 2026-10-19 (author session, bisect open): **pre-5ª-sessão clean build is the
  build under test.** I installed it at 12:42 from the committed pre-5ª source
  (`libindium.dylib` md5 `3df22735e93c22675b792bfe5589c6e2`, kept as
  `libindium.dylib.prefifth-clean`); `check-darwin-tlv-calls.py` passes. My saved
  backups: `session5-clean` = `2909b341ccdafb8db51a476c3551820c` (5ª),
  `session6-24f7f7b` = `8acea7f312a5e04b6a5230954c0702d9` (6ª), stock
  `.darling-lol-backup` = `89e7338998e4d4de64192fa1fe3edf63`. Re-hashed at 12:42;
  the digests are self-consistent and the 12:45 synthesis table's `99f2192c…` /
  `65c27806…` / `cea9f6d1…` / `2c20e484…` do not correspond to these files. Per the
  conflict rule I have frozen `patches/metal--deps--indium.patch`.
  - **RESULT (pre-5ª test, done):** it **loads** — black screen gone, image up.
    ⇒ **the regression lives in the 5ª/6ª hunks, it is not a pre-existing crash.**
    The forensics below explain *how* those hunks corrupt the process.
  - **Running (12:53):** `session5-clean` (`2909b341…`, the 5ª build) is now
    installed and the namespace restarted; awaiting one game start. Loads ⇒ culprit
    is the 6ª hunk; dies ⇒ culprit is the 5ª hunk.
  - **Suspected hunks:** (a) 5ª session event-loop wake coalescing in
    `indium/device.cpp` (`_pollWaiting` guard, thread_local snapshot scratch in
    `pollEvents`, `wakeupEventLoop`, `waitForSemaphore`); (b) 6ª session
    batch-timer rewrite in `indium/command-buffer.cpp` (`flushSubmitBatchLocked`,
    no-precommit). Neither reviewed change showed a memory-safety bug on
    inspection.
  - **Crash forensics (not yet tied to indium):** the black screen is the game
    process taking SIGSEGV in `libobjc.A.dylib:objc_msgSend_stret` (offset
    `0x4089d`, zero isa) during the loading screen; `launchd` also SIGSEGV'd in
    `libsystem_platform:__platform_strlen` and took the session down. The game
    signature (`bsd=11 addr=0x18`) recurs on 10-17 23:35, 10-18 02:08, 10-18
    20:23 and 10-18 22:29 across older builds, so it may pre-date this work.
  - **Worktree state (dirty, not committed):** the indium checkout currently holds
    the pre-5ª files — `device.cpp` `f939e544…`, `command-buffer.cpp`
    `8dece49e…`, `render-command-encoder.cpp` `76458c6f…`. The 6ª versions are
    saved in `/tmp/six/src/indium/`.
- 2026-10-19 (reviewer session, static RE of `mvg` surface): closed the static
  list for the runtime `H1IOKIT`/`H4SYSCTL` cross-check. **IOKit** — exactly one
  `IOServiceMatching`, and the obfuscated class name decrypts to
  `IOPlatformExpertDevice` (`plain[i] = cipher[i] XOR key[i % 17]`, key
  `a1 6d cb 03 11 59 c9 54 1d 5a 4c a9 14 4a 27 55 65`, blob at `0x11EF4A0`;
  the same buffer also holds the fallback `unknown`); one
  `IOServiceGetMatchingService`; **two** `IORegistryEntryCreateCFProperty` sites
  whose key names use a *second* decryptor not reversed yet (not the 17-byte
  keystream); one each of `IORegistryGetRootEntry`,
  `IORegistryEntryCreateIterator`, `IORegistryEntryGetPath`; one
  `KextManagerCopyLoadedKextInfo` (Darling returns NULL — no `kextd` /
  `com.apple.KernelExtensionServer`); one `IOCreatePlugInInterfaceForService`
  (synthetic services have no `kIOCFPlugInTypesKey` factory →
  `kIOReturnUnsupported`). `kIOMainPortDefault` is `weak_import`; the rest bind
  strong and resolve. **sysctl** (proven by `sysctlbyname("…")` format strings):
  `hw.physicalcpu_max`, `hw.logicalcpu_max`, `hw.packages`, `hw.cacheconfig`
  (`vfs.usermount` is also present but likely from a bundled library, not Vanguard
  code). The runtime `H1IOKIT`/`H4SYSCTL` lines should be diffed against this:
  the two property keys and any extra sysctl names are the deliverable. Strictly
  static: no runtime armed, no game start, no `patches/` touched, Vanguard
  untouched.
- 2026-10-19 (telemetry session): `H4SYSCTL` lines now also carry `pid=` (cached
  `__NR_getpid`), so both halves can be attributed per process; `H1IOKIT` already
  carried `caller=`. Added `build/hw-trace-crosscheck.py` (untracked, under
  `build/`) — it parses the raw log and prints the static-vs-captured key diff
  (`[seen]`/`[MISSING]`/`[extra]`), per-pid sysctl counts, captured IOKit ops and
  the matched criteria. Hunks re-validated: `prepare.py --check-only` 30/30,
  `validate.py` PASS, clean-revision apply reproduces the working tree. Capture
  stays queued at position 2 (after the indium bisect), never with `/tmp/metal-*`.
  Note: `KextManagerCopyLoadedKextInfo` and `IOCreatePlugInInterfaceForService`
  are client-side (`patches/IOKitUser.patch`), so they never reach `iokitd`; the
  "kextd returns NULL" proof needs a scoped hunk there — flagged, not written,
  since that component is not part of the telemetry patches owned so far.
- 2026-10-19 (telemetry session, after the coordinator's queue note): took
  `patches/IOKitUser.patch` for the client-side kext trace, as authorized. New
  `kext.subproj/HWTrace.h` (same `/tmp/darling-hw-trace` gate) plus two lines:
  `KextManagerCopyLoadedKextInfo` logs `op=kext_copy_loaded rv=NULL|dict`, and
  `OSKextCopyLoadedKextInfo` logs `op=kext_request op_result=<n> present=0|1`
  (the kextd RPC refuses because there is no `kextd`). Added the CPU keys to the
  cross-check expected set (`hw.ncpu`, `hw.logicalcpu`, `hw.physicalcpu`,
  `machdep.cpu.brand_string`; all four exist in the sysctl tables) — the H4 trace
  records them automatically since it logs every key. Revalidated: `prepare.py
  --check-only` 30/30, clean-revision apply reproduces the tree for all three
  patches, `validate.py` PASS. Owner of record: this session for `xnu.patch`,
  `iokitd.patch`, `IOKitUser.patch`. Confirmed: capture stays at **#2**, right
  after the black-screen bisect closes, one game start, only `/tmp/darling-hw-trace`.
- 2026-10-19 (reviewer/tooling session, coordinator's items 2–3; item 1 above
  unchanged): **item 2** — `docs/TROUBLESHOOTING.md` gained the `prepare.py`
  shared-checkout bullet: a refusal/failure at one component (usually `iokitd`)
  while another session holds edits there is a dirty shared checkout, not a
  regression in the patch under test; the normal run stops with the "checkout has
  other edits" message, while `--check-only` validates the committed patch text
  against the pinned revision through a temporary index and leaves the shared
  worktree untouched, so it tells the two apart. **item 3** — the FPS analysis is
  now one tracked entry point, `tools/fps_diag.py` (`perframe`, `optime`,
  `thread-prof`, `report` self-contained and read-only; `arm-counters`/`restore`/
  `collect-match`/`watch`/`probe-summary` *delegate* to the recipes in
  `build/fps-diag`, overridable with `FPS_DIAG_DIR`). The historical
  `python3 build/fps-diag/{perframe,optime,thread-prof}.py` invocations still work
  as thin shims over it (originals kept in `build/fps-diag/legacy-analysis/`);
  output verified byte-identical against the legacy scripts on
  `build/fps-diag/match2-metal-trace.log`. README architecture paragraph and
  `docs/TESTING.md` updated. No `patches/`, no RuntimeLibraries and no runtime
  knob touched; strictly static/tooling.
