# Worklog — Riot Client under Darling: OpenGL / EGL crash

Date: 2026-10-17 (last updated 2026-10-18)
Status: **resolved** — the launcher, installer, picker, splash and the NVIDIA
game window are all verified; symptom 5 (black game window) was fixed in
`CGLContextMakeCurrentAndAttachToWindow` on 2026-10-18. Fold the durable
conclusions into the curated docs and retire this file.

This file is a working log for the session that got the Riot Client (League of
Legends launcher) to run under Darling past login. It is not part of the curated
project documentation (`STATUS.md`, `SETUP.md`, `TESTING.md`,
`TROUBLESHOOTING.md`); fold the durable conclusions into those when finished.
The follow-on FPS work on the same machine is in
[WORKLOG-FPS-2026-10-18.md](WORKLOG-FPS-2026-10-18.md).

> **Artifacts.** This session's scratch lived in `/tmp/opencode` (tmpfs, wiped on
> reboot). A full snapshot is kept at **`build/fps-diag/`** in the repo (gitignored);
> references below to `/tmp/opencode/...` mean the same file there. The few
> session-only files named here (`bi.py`, `QuartzCore.installed-backup`, `run4.log`,
> `monitor2.py`) were already gone before the snapshot.

## Status (2026-10-18, end of session)

All five symptoms are resolved. The launcher itself is verified working by the
user (`RiotClientServices` + Electron Riot Client, `LeagueClientUx` and
`LeagueClient` up), and the **game window now renders**.

1. Splash abort — fixed by defaulting `__GL_THREADED_OPTIMIZATIONS=0`.
2. Install-path abort — fixed in the AppKit overlay (sheet method + panel
   setters); see "Symptom 2 resolution".
3. Black install-path picker — fixed by a panel-only software present in the
   X11 backend; see "Symptom 3 resolution".
4. Black game window / hung client — the *hang* part is fixed by flushing the
   AppKit subwindow before EGL first looks at it; see "Symptom 4 resolution".
5. Black game window after the attach fix — **fixed** in
   `CGLContextMakeCurrentAndAttachToWindow` by selecting a draw buffer when
   NVIDIA reports `GL_NONE`; see "Symptom 5 resolution".

Remaining: fold the durable conclusions into `README.md` (architecture),
`STATUS.md` and `TROUBLESHOOTING.md`, and retire this file.

### Landed changes

- `tools/run-riot-client.sh`: `__GL_THREADED_OPTIMIZATIONS` default `1` → `0`
  (regenerated into `build/runtime/tools/run-riot-client.sh`).
- `patches/cocotron.patch`: `NSSavePanel` sheet method + no-op setters, and the
  X11 backend panel software present (`presentSoftwareSurface`, `_isPanel`).
- `patches/darling.patch`: OpenGL own-X-connection helper, robust
  `CGLGetWindow` config loop and context retry ladder — session debug logging
  removed and `display_rebuild_mutex` renamed; the regenerated patch
  reverse-applies cleanly and passes `python3 scripts/prepare.py --check-only`.
- `tools/install-riot-{appkit,gpu}-runtime.sh`: refuse to replace overlays while
  a Riot Client or League of Legends runs, unless `RIOT_ALLOW_RUNNING_CLIENT=1`.

### Activating an overlay needs a namespace restart

Replacing a framework in `RuntimeFrameworks/` while a namespace is running does
**not** reach the guest: every process in that namespace, including freshly
launched ones, kept loading the old binary (the guest still reported its
pre-update size and mtime) until `darling shutdown`. Restarting to activate the
overlay is what closed a client mid-download (78% → Riot patcher
`NeedsRepair`); install overlays before starting the game. Documented in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

**Hard constraints.** Keep patches minimal; edit source via
`patches/darling.patch` and never reset a checkout to make a patch apply; keep
each patch applicable to its pinned revision (`@@` hunk headers); no full
rebuilds (rebuild only the changed component); short answers; never print
`remotingAuthToken`, `machineId` or account data.

## Objective

Run the Riot Client (League of Legends) under Darling on this machine.

Two distinct symptoms were hit in sequence:

1. **Splash abort (resolved):**
   `M58DG CGLCreateContext FAILED ... eglGetError=0x3008` (`EGL_BAD_DISPLAY`)
   while the splash renders.
2. **Install-path abort (resolved):** after logging in, selecting the game
   install path aborted the client. The UI process (`CrBrowserMain`) died with
   `SIGABRT` (Riot product session reported `exitCode:6`).

## Environment / how it is run

- GPU: **NVIDIA (proprietary driver)**. EGL vendor library:
  `/usr/share/glvnd/egl_vendor.d/10_nvidia.json`
  (Mesa alternative: `50_mesa.json` — works but software-slow).
- Installed OpenGL component currently:
  `~/.darling/Users/chiuaua/RuntimeFrameworks/OpenGL.framework/Versions/A/OpenGL`
  sha256 `9d82e8b787e1d6e562686c6f1a89ba19aada8a0dd4afb092a603a98efc055809`
  (includes exploratory instrumentation — see "Current repo state").
- Restart the namespace between runs (`darling shutdown`); runs are bimodal
  (sometimes the client exits early before the Electron windows appear).
- Compile/install only the `OpenGL` component with the helper
  `/tmp/opencode/bi.py` (compiles `OpenGL.c`, links from `link.txt`, installs
  atomically). No full build.

### Test command

```sh
darling shutdown
env RCLOL_REGION=BR DISABLE_LSFGVK=1 \
    __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json \
    sh scripts/run.sh 2>&1 | grep M58DG
```

## Symptom 1 root cause (CONFIRMED)

**NVIDIA `__GL_THREADED_OPTIMIZATIONS=1`.** NVIDIA's threaded-optimizations
worker thread invalidates the shared EGL display once Chromium/ANGLE also uses
EGL in-process (after roughly six contexts), right when the splash renders.

**Fix: set `__GL_THREADED_OPTIMIZATIONS=0`.**

Evidence:

- With `1`: reproduces the `EGL_BAD_DISPLAY` abort.
- With `0`: 12 OK contexts, 0 failures, splash renders; 3 consecutive runs
  stable.
- With the Mesa vendor: 11 OK, splash renders, never hits the bug.

The earlier "transient per-thread AppKit `X11Display` connection" theory was
**WRONG** and is superseded. GPU-direct present is **not** involved (still fails
with `RCLOL_GPU_DIRECT_PRESENT=0`).

### Extra diagnostics from that work

- `CGLGetWindow` always returned `EGL_BAD_CONFIG` (`0x3005`); the display then
  died externally (no `CGL` call in between; `XSync`/`XOpenDisplay` still
  succeed; `eglGetPlatformDisplay` starts returning `EGL_NO_DISPLAY`).
- Confirmed NVIDIA-specific by A/B vendor test.

## Symptom 2 — crash on install-path selection (RESOLVED)

### Symptom 2 resolution

`-[NSOpenPanel setShowsTagField:]` was the abort: an unimplemented selector
raises `NSInvalidArgumentException` inside Chromium's file-dialog setup, which
self-`abort()`s the browser process. Fixed in `NSSavePanel.m`
(`patches/cocotron.patch`) by implementing
`beginSheetModalForWindow:completionHandler:` (runs `[self runModal]`, then the
handler) and adding no-op setters `setShowsTagField:`,
`setCanSelectHiddenExtension:`, `setExtensionHidden:` and `setNameFieldLabel:`.
The probe `responds_to_sheet` went `0 → 1` and the
`unrecognized selector` abort stopped; the install flow then ran to completion.

Reproduction so far is manual: log in, click **Install**, choose the install
location → process aborts.

Evidence gathered:

- `coredumpctl`: `SIGABRT`, `si_code SI_TKILL` (self-`abort()`), executable
  `/usr/local/libexec/darling/usr/libexec/darling/mldr`, process name
  `CrBrowserMain` (the Riot Client Electron/Chromium browser main).
- Riot Client log sequence: `productDetailsPlayButton: click` with
  `buttonState:"Install"` → `productSessionEnd ... exitCode:6` about 3 s later.
- Crashes are not stored as coredumps (`Storage: none`); no crashpad minidump.
- `.../Application Support/riot-client-ux/Crashpad/` is empty (no `.dmp`).
- `.../Application Support/Riot Games/Riot Client/Crashes/Riot Client/<uuid>.run/`
  contains a Sentry event (`__sentry-event`, `level=fatal`, `platform=native`)
  but **no stacktrace** and no minidump.

### Working hypothesis (unconfirmed)

The folder picker is a native Cocoa panel; Chromium's Cocoa file dialog drives
`NSOpenPanel`. In this Cocotron fork:

- `NSSavePanel.m` implements `beginWithCompletionHandler:` as
  `NSUnimplementedMethod()` (logs only — `_NSUnimplementedMethod` just calls
  `NSLog`, it does **not** abort).
- `beginSheetModalForWindow:completionHandler:` is **not** implemented
  (unrecognized selector → `NSInvalidArgumentException`, which could abort).
- `-runModal` works via `[NSApp runModalForWindow:self]`; the legacy
  `beginSheetForDirectory:file:modalForWindow:modalDelegate:didEndSelector:contextInfo:`
  runs `runModal` on a **background thread** (suspicious).

Relevant files:
`src/external/cocotron/AppKit/NSSavePanel.subproj/{NSSavePanel.m,NSOpenPanel.m}`,
`src/external/cocotron/AppKit/NSDisplay.m` (`implementsCustomPanelForClass:`
returns `NO`, so a nib is used),
`src/external/cocotron/AppKit/X11.backend/X11Display.m` (`savePanel:`,
`openPanel:`, `runModalPrintPanelWithPrintInfoDictionary:`).

**To confirm** we need the guest's stderr at the moment of the abort (Chromium
`CHECK`/`LOG(FATAL)` text or an uncaught-exception trace). The captured abort
output was not available; reproducing requires GUI interaction (login + click),
so it likely needs either the user's terminal output or a dedicated guest probe.
This is now superseded by the resolution above.

## Symptom 3 — black install-path picker (RESOLVED)

The picker opened but rendered black. Root cause: AppKit presents windows
through GL (`openGLFlushBuffer` → `CGLFlushDrawable`), and **every**
`CGLGetWindow` on this NVIDIA system fails
(`surface=0x0 eglGetError=0x3005`, `EGL_BAD_CONFIG`), so `_cglWindow == NULL`
and the flush is a no-op. Chromium's own windows still render because they use
the remote CA frame path (`presentRemoteCAFrame`, published as
`/dev/shm/darling-ca-frame-*` by `QuartzCore/CALayer.m`), which the panel does
not.

Fix (`patches/cocotron.patch`, `X11.backend/X11Window.m`): a
`presentSoftwareSurface` fallback that `XPutImage`s the Onyx O2 surface, taken
only when `_isPanel && _cglWindow == NULL` so a panel without a same-sized
Chromium frame still shows its own content. Verified with
`build/riot-openpanel-show-check`: the file list, **Cancel** and **Open**
buttons render, with no X errors and no `M58DG` noise.

## Symptom 4 — black game window and hung client (RESOLVED)

The practice game stayed black and the League UX hung on its loading screen
while both processes were alive, with `Metal Device timed out` repeating in the
game's `*_r3dlog.txt`.

Root cause: `X11SubWindow` created and mapped the layer subwindow with
`XCreateSimpleWindow`/`XMapWindow` but never flushed that X connection. The
requests sat in the connection's output buffer, so the window did not exist
server-side when `CALayerContext` attached its GL context: `CGLGetWindow` calls
`eglCreateWindowSurface` on `OpenGL.framework`'s **own** X connection, which
could not find the window and returned `EGL_BAD_CONFIG` (`0x3005`) for the
window and for all 40 window-capable configs. `_cglWindow == NULL` then made
`CALayerContext.render` a no-op, so queued Metal drawables were never recycled
and every presentation timed out.

Evidence (guest flag `/tmp/metal-debug-trace` + `/tmp/metal-trace.log`):

- `CGLGetWindow` succeeded for the toplevel (`X11Window`, which flushes) and
  failed for the child (`X11SubWindow`) although both were `visual=0x23 depth=24`
  and the host's EGL accepted both.
- `XGetGeometry` on the child, issued from CGL's own connection, failed — the
  window was not there yet. `XGetGeometry` on the previously accepted toplevel
  returned its real size, and on CGL's own freshly created window it succeeded.
- After the fix: `X11SubWindow` `XSync`s, the child gets its surface, and
  `build/riot-metal-presentation-check` prints all three `PASS` lines (it
  previously failed at frame 3 with `FAIL: drawable after late window/context
  attachment`).

Landed: `patches/cocotron.patch` (`AppKit/X11.backend/X11SubWindow.m`), plus
`tools/build-riot-x11-runtime.py` now recompiles `X11SubWindow.m` as well.
`patches/darling.patch` and `patches/cocotron.patch` were regenerated and pass
`python3 scripts/prepare.py --check-only`; all session diagnostics
(`cglWindowTrace`, `probe-*`, `darlingQCTracePresent`, `ND-ENTER`) were removed.

## Symptom 5 — game window black after the attach fix (RESOLVED)

> **Resolution (2026-10-18).** The draw-buffer defect is fixed in
> `CGLContextMakeCurrentAndAttachToWindow` (see "Where the fix would live"
> below): after a successful attach it queries `GL_DRAW_BUFFER` and, only when
> the driver reports `GL_NONE`, selects `GL_BACK` (or `GL_FRONT` on a
> single-buffered surface) for the draw and read buffers. The "composite quad
> does not rasterise" finding turned out to be an artefact of a diagnostic that
> sampled the root layer's empty texture instead of the Metal layer's — geometry,
> rasterisation and presentation were never broken. Validated on the GTX 1070: a
> practice match on Summoner's Rift showed the full HUD at 59 FPS / 9 ms,
> `GAMESTATE_GAMELOOP`, and zero `Metal Device timed out` entries. The temporary
> `CALayerContext.m` / `CARenderer.m` diagnostics were removed and the QuartzCore
> overlay restored to the clean build. The narrative below is kept for the
> reasoning trail.

With the `XSync` correction the game no longer starves and no longer hangs:
host `LeagueofLegends` reached `GAMESTATE_SPAWN → GAMESTATE_GAMELOOP`, the
`Metal Device timed out` count in `*_r3dlog.txt` fell from 43 to 2, and
`metal-device.log` reports the healthy path on the GTX 1070
(`presenting GL renderer="NVIDIA GeForce GTX 1070/PCIe/SSE2"`,
`drawable GL import ... vkTiling=optimal glTiling=optimal ok`,
`drawable GL semaphore ... import_error=0x0 wait_error=0x0 ok`). The window
`0x6c00002` (`League of Legends (TM) Client`, 1360x768, visual 0x23) and its GL
child `0x6c00003` exist and accept a window surface
(`eglCreateWindowSurface -> OK (err 0x3000)`). The window is nevertheless pure
black: a `spectacle` full-screen capture with the window raised is entirely
black and static while the terminal on the same screen renders normally.
Per-window captures (`import`, `XGetImage`) are unreliable for GL windows; the
compositor's own capture is the ground truth.

**Decisive reproduction.** A standalone AppKit window that owns a
`CAMetalLayer` (no game, no client) shows the same black content, so the defect
can be exercised and fixed in seconds instead of requiring a game start.

**Finding 1 — the window's default framebuffer has no draw buffer.** Inside
`CALayerContext.renderLayer`, after the attach succeeds:

```
attach cgl=… err=0 glerr=0x0 frame=400x300
drawFbo=0 readFbo=0 rgbBits=8/8/8 alphaBits=0 depthBits=0 double=1 samples=0
drawBuffer=0x0 drawBuffer0=0x0 readBuffer=0x0        <- all GL_NONE
glClear(magenta) + glReadPixels -> 0,0,0   err=0x0   <- discarded, no error
```

Every draw *and every `glClear`* on the default framebuffer is discarded
without a GL error, which is why the drawable import looked fine (the `_tex`
texture holds the frame: `lit=120000/120000 mean=281 rgba=255,13,13,255`,
cycling red/green/blue) while the window stayed black — the window never
receives it. Forcing `glDrawBuffer(GL_BACK)` right after the attach fixes the
buffer: the clear lands (`px=255,0,255`), and after `CGLFlushDrawable` the
front buffer holds it (`front lit=120000 mean=510`). `eglSwapBuffers` and the
present path are therefore healthy; only the draw-buffer state is wrong.
`CGLPresentIOSurface` in `OpenGL.c` already sets `glDrawBuffer(GL_BACK)`
explicitly for the same reason.

**Finding 2 — the composite quad still does not rasterise.** With the draw
buffer forced, a manual textured quad of the layer's `_tex` — alpha test,
blending, depth test and scissor all disabled, `err=0x0` — still reads back
`0,0,0,255` at the viewport centre. The state around it is sane
(`tex2d=1`, `binding=1`, `viewport=0,0 400x300`, `matrixMode=GL_MODELVIEW`,
identity modelview, projection scales non-zero for x/y) and the layer reads back
correct geometry and opacity through the same KVC the renderer uses
(`opacity=1`, `bounds=0,0 400x300`, `hidden=0`, `textureId=1`, `isTexture=1`).
Because a discarded fragment and a fragment sampled from a black texture are
indistinguishable in that readback, the next test is a flat-colour client-array
draw: it separates the client-side vertex-array path from the texture sampling.

**Ruled out along the way.** The EGL context is not a core profile
(`GL_VERSION=4.6.0 NVIDIA 580.178.04`, `profileMask=0x2` compatibility, a
legacy fixed-function draw returns `glError=0`); the subwindow attach is not
failing; layer opacity/anchor/position are not degenerate (position and
anchorPoint both read as 0, which still covers the viewport because the
translate is `position - bounds*anchorPoint`); the Chromium client is unaffected
because its frames go through the remote CA frame path and
`DARLING_CA_SKIP_LOCAL_IOSURFACE_RENDER`, never through `CARenderer`.

**Where the fix lives.** In
`CGLContextMakeCurrentAndAttachToWindow` (`patches/darling.patch`), so every GL
window gets a usable draw buffer when it is attached. A layer-only variant in
`CALayerContext.renderLayer` (`patches/cocotron.patch`) was not needed.

**Open items (status).** (a) Done — the flat-colour and immediate-mode draws both
landed, confirming the draw-buffer state, not rasterisation, was the defect.
(b) Done — a practice match renders on the GTX 1070. (c) Optional — decode the
XGE/Present events seen on the game subwindow (608 `GenericEvent` type-35 events
in 12 s) to confirm pixmap presents. (d) Optional — re-check the earlier LCU
HTTP/2 `jade-home` timeout now that the client works.

## Current repo state

`git status --short`:

```
 M README.md
 M docs/SETUP.md
 M docs/STATUS.md
 M docs/TROUBLESHOOTING.md
 M patches/cocotron.patch
 M patches/darling.patch
 M tools/build-riot-appkit-runtime.py
 M tools/build-riot-x11-runtime.py
 M tools/install-riot-appkit-runtime.sh
 M tools/install-riot-gpu-runtime.sh
 M tools/run-riot-client.sh
?? AGENTS.md
?? docs/WORKLOG-OpenGL-EGL.md
?? docs/WORKLOG-FPS-2026-10-18.md
?? tools/build-riot-openpanel-sheet-check.py
?? tools/build-riot-openpanel-show-check.py
?? tools/riot-openpanel-sheet-check.m
?? tools/riot-openpanel-show-check.m
```

- The working tree it describes is the one with the `XSync` subwindow fix and
  the symptom-5 draw-buffer fix (`OpenGL.c`) landed, regenerated and validated
  (`python3 scripts/prepare.py --check-only` → "All 30 component patches
  validated"); the temporary symptom-5 diagnostics are **not** in the patches.
- `build/darling-src/src/external/cocotron/QuartzCore/CALayerContext.m` no longer
  carries the symptom-5 diagnostics; the instrumented `/tmp/win-present-*` paths
  were removed and the QuartzCore overlay restored to the clean build.
- The installed QuartzCore overlay was rebuilt from that instrumented source
  during the investigation and has been restored to the clean installed build
  (`/tmp/opencode/QuartzCore.installed-backup`). Activating a rebuilt overlay
  needs a namespace restart; see "Activating an overlay needs a namespace
  restart".
- The quick build loop for this work is
  `python3 build/runtime/tools/build-riot-metal-presentation.py` (compiles
  `CALayer`, `CALayerContext`, `CATransaction`, `CAMetalLayer`,
  `CAMetalDrawable` and links `build/riot-QuartzCore`, which is then copied
  over the installed overlay path; it does **not** compile `CARenderer.m`, so
  that file needs `build-m58f336-quartzcore.py`).

- `tools/run-riot-client.sh` and its generated copy default
  `__GL_THREADED_OPTIMIZATIONS` to `0`.
- `build/darling-src/src/frameworks/OpenGL/OpenGL.c` keeps the own-X-connection
  helper, the robust `CGLGetWindow` config loop and the context retry ladder;
  the session debug logging is gone and `m58dg_display_mutex` is now
  `display_rebuild_mutex`.
- `patches/darling.patch` and `build/applied-patches/darling.patch` are in sync
  with that source.

## Next steps

1. **Done — symptom 5 closed:** the draw-buffer fix is in
   `CGLContextMakeCurrentAndAttachToWindow` (`patches/darling.patch`), the
   `/tmp/win-present-*` diagnostics are removed, `python3 scripts/prepare.py
   --check-only` passes, and a practice match renders.
2. **Docs:** `README.md` (architecture), `STATUS.md` and `TROUBLESHOOTING.md`
   now describe the fix. Fold any remaining NVIDIA `__GL_THREADED_OPTIMIZATIONS`,
   sheet/setter, panel-present and overlay-restart findings, then retire this
   file.
3. **Optional:** the own-X-connection helper and the `CGLGetWindow` config loop
   were originally written for the belief that every window config was rejected.
   The real cause of the rejections was the unflushed subwindow; both are kept
   because they are inert on this driver and still cover a genuinely invalid
   display. Revisit if the patch should shrink further.

## Constraints / conventions

- Keep patches minimal; no unrelated changes.
- Source changes live in `patches/darling.patch`; never reset a checkout to make
  a patch apply. Keep each patch applicable to its pinned revision (correct `@@`
  hunk headers).
- Short answers; do not dump logs containing `remotingAuthToken`, `machineId`,
  or account data.

## References

- Error strings: `M58DG CGLCreateContext FAILED ... eglGetError=0x3008`
  (`EGL_BAD_DISPLAY`); `CGLGetWindow ... eglGetError=0x3005` (`EGL_BAD_CONFIG`).
- `tools/m58f299-xshm.c` and `src/external/iokitd/src/IOSurfaceRoot.mm` were
  checked for EGL teardown; only the `iokitd` daemon calls `eglTerminate`.
- `gdb` is present but `ptrace_scope=1` blocks attaching to the guest; a host
  `LD_PRELOAD` EGL shim was **not** honored (empty log).
