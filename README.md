# darling-lol

> [!IMPORTANT]
> ## Announcement
>
> This project has gained a lot of attention, so a few things need to be said clearly.
>
> **1. Maintenance.** I built this mainly as a technical challenge, because everyone kept telling me it was impossible. I don't have the time to maintain it fully. Apart from open issues that block you completely, I will only review and merge pull requests.
>
> **2. Bans.** This project can get you permanently banned, as I have said many times. I am not responsible for your actions. You alone are responsible for launching the game in a modified environment (Darling). If you use it:
> - don't cheat;
> - don't play ranked;
> - don't use your main account.
>
> Even with all of that, you will probably still get permabanned.
>
> **3. Takedown.** Riot may well shut this project down. If that happens, I will publish a fork of Darling containing only the changes made here (none of them breach anything), and release the small script as a gist or similar.
>
> **4. To Riot.** If you are reading this, it means a lot of people want to play your game on Linux and are disappointed that they currently can't. As with macOS for your other games (TFT, Valorant), it feels like Riot doesn't care about a part of its players who have been waiting the longest. If you want to fix this, make LoL Next compatible with Linux, either natively or through a layer like Proton. Yes, that includes your kernel anticheat: Epic Games did it with Easy Anti-Cheat. Follow the trend. This is the year of Linux, and people shouldn't be locked out of a platform or forced to dual boot for a single game.

https://github.com/user-attachments/assets/140df3e0-3790-46b6-bab5-578139b84a7c

Experimental source patches and tools for running the **macOS League of Legends client on x86-64 Linux through Darling**.

This is a development snapshot, not a finished launcher. Riot and League clients can launch and manually played ARAM games have run. Graphics, audio, input, startup crashes and memory reclamation have received compatibility fixes. On the Ryzen 5 5500 / RX 6600 PC, ARAM now averages about 118–135 FPS, with the slowest 10-second stretches around 106–119 (the higher figures with Hyprland's direct scanout off; fights were 70–80 FPS before the 2026-10-13/14 work, versus 170–190 on Windows). On the NVIDIA GTX 1070 machine the practice match window now renders too; there the game is CPU-bound on a 4-thread i3-8100, which the [FPS worklog](docs/WORKLOG-FPS-2026-10-18.md) covers. The effect of the memory changes on client RAM remains unmeasured. A fresh checkout has not been validated end to end on another machine.

## Included

- Pinned upstream revisions and patches for 30 Darling components, including Metal/Indium, AppKit, QuartzCore, CoreAudio, the kernel shim and darlingserver.
- Event-poll presentation and GPU synchronization fixes, floating-point-safe GL resolvers, multi-window presentation and nullable LaunchServices error handling.
- Reusable server receive buffers and Darwin allocator hints translated to Linux lazy reclamation.
- Build/install/launch wrappers, atomic incremental installers and standalone regression probes.

Game files, Riot installers, account databases, tokens, local prefixes, captures and compiled binaries are not included. Install the game manually through Riot. The normal launcher does not enable an Electron inspector or start UI automation helpers. The launcher clears `DYLD_INSERT_LIBRARIES` and retains Darling runtime library/framework overrides; this is not a claim of approval by Riot.

## Architecture

The runtime is the pinned Darling translation layer plus this repository's patches and per-user overlays.

- **Kernel/CPU.** The XNU syscall shim (`libsystem_kernel`) and `darlingserver` implement the Darwin side; the launcher installs optimized per-user libraries (real CPU topology, lazy-reclaim allocator hints and the libc/libm/libc++/string-primitive overlays).
- **Graphics.** `OpenGL.framework` bridges CGL to the host EGL through a private `dlopen(RTLD_LOCAL)`, so the native EGL stays out of ANGLE's dependency scope. `CGLCreateContext` derives the requested OpenGL profile from the pixel format and creates the EGL context; on failure it retries progressively: without the core-profile mask, then with driver defaults, then after re-choosing an `EGLConfig`, and finally by rebuilding the EGL display and config from a private Xlib connection that `OpenGL.framework` owns itself (opened through the `/usr/lib/native/libX11` shim and kept for the process lifetime) when the display is reported invalid (`EGL_BAD_DISPLAY`). Because `CGLRegisterNativeDisplay` is fed AppKit's transient `X11Display`, whose `XCloseDisplay` would otherwise invalidate the EGL display, the framework never depends on it staying alive. NVIDIA's threaded-optimizations worker invalidates that shared display once ANGLE also uses EGL in-process, so the launcher defaults `__GL_THREADED_OPTIMIZATIONS=0`. AppKit windows normally present through GL (`CGLFlushDrawable`); where the driver rejects every `CGLGetWindow` (`EGL_BAD_CONFIG`), panels fall back to a software `XPutImage` of the Onyx surface while Chromium windows keep using the size-matched remote CA frame path. AppKit subwindows (`X11SubWindow`) are `XSync`ed after creation and mapping: the requests are otherwise still buffered in that X connection's output queue, so EGL — which looks the window up on its own connection — cannot find it and returns `EGL_BAD_CONFIG`, leaving the layer context with no drawable and the compositor permanently starving (`Metal Device timed out`). Metal/Indium and the AppKit/QuartzCore layer compositor present the rest. On the NVIDIA driver the layer compositor's output used to be discarded: the default framebuffer of an attached window surface reported `GL_DRAW_BUFFER = GL_NONE`, so the composite never reached the window even though the surface attaches and the drawable is imported correctly. `CGLContextMakeCurrentAndAttachToWindow` now selects `GL_BACK` (or `GL_FRONT` on a single-buffered surface) when the driver reports `GL_NONE`, so the NVIDIA game window renders (a practice match on the GTX 1070 showed the full HUD at 59 FPS / 9 ms). See [troubleshooting](docs/TROUBLESHOOTING.md#nvidia-the-window-attaches-and-the-frame-is-dropped-fixed-2026-10-18).
- **Audio.** CoreAudio and AudioToolbox use PulseAudio backends.

`patches/` holds one patch per component, applied by `scripts/prepare.py`; `tools/` holds the runtime installers and standalone probes, which share the build helper `tools/riot_build.py` (configured CMake flags, clang resource-include refresh and the guest link line), so the per-probe builders no longer re-implement them. See [coordination](docs/COORDINATION.md) for how parallel sessions split this tree. Replacing a framework overlay only takes effect after the Darling namespace restarts, and that restart closes any running client, so the overlay installers refuse to run while a Riot Client or League of Legends process is present unless `RIOT_ALLOW_RUNNING_CLIENT=1` is set.

## Requirements

- x86-64 Linux **5.14 or newer**, an X11 session or Xwayland, and a working hardware Vulkan/OpenGL driver. AMD RADV has been exercised, and an NVIDIA GTX 1070 (driver 580.178.04) now renders the game window; other drivers are not validated. Hybrid laptops usually render on the integrated GPU unless started with PRIME offload; discrete-GPU handling is still being verified. See [hybrid graphics](docs/TROUBLESHOOTING.md#hybrid-graphics-laptops-amdintel-igpu--nvidia).
- Git + Git LFS, Bash, curl, unzip, CMake, Make, Clang/LLD, LLVM development files, a C/C++ compiler, Python 3.12+ and the Darling build dependencies. The patch includes LLVM 22/23 branch-opcode compatibility; the new PC used LLVM/Clang 23. Node.js is needed only for the offline JavaScript checks.
- X11/XCB/SHM development files for the current runtime helpers.
- Enough free disk for Darling sources/build, Git LFS assets and the game: budget at least 50 GB. Building is substantially larger than this source-only repository.

Use the dependency list in the [pinned Darling source](https://github.com/darlinghq/darling/tree/60ba801decee7a00782f74f6be4c8ffb013f79ff) for your distribution. `tools/env-check.sh` provides a starting check; its legacy package names may need adapting to your distro.

## Build on the other PC

```sh
git clone https://github.com/lucannez64/darling-lol.git
cd darling-lol
python3 -m venv build/venv
build/venv/bin/pip install -r requirements.txt
python3 scripts/configure.py --guest-user "$USER"
./scripts/build.sh
sudo cmake --install build/darling-src/build
./scripts/install-runtime.sh
```

The default layout is `/usr/local/libexec/darling`, `~/.darling` and `/Users/$USER` inside the guest. Use the actual guest account name if it differs. Paths are rendered into ignored files under `build/runtime/tools`; do not run the tokenized `tools/` templates directly. See [setup details](docs/SETUP.md).

The install wrapper compiles the paired runtime, shuts down Darling before replacing per-user overrides, and backs up relevant files. Do this with no Riot/League session running.

## Install and launch Riot

After the runtime is installed:

```sh
./scripts/installer.sh euw
```

Sign in and install League through Riot's own UI. For subsequent launches:

```sh
./scripts/run.sh
```

First installation and future Riot updates can still encounter compatibility gaps. An accepted Install action can fail native LaunchAgent registration and leave the download idle. The archived inspector-based workaround is excluded from the manual workflow; the client window-visibility correction is part of the installed runtime (Darling's AppKit overlay), not a patch to Riot's binaries. See [troubleshooting](docs/TROUBLESHOOTING.md) for the known limitation and fixes that are in the runtime.

The anti-cheat is another gap that is **not** a Darling bug: the client's Vanguard integration has no component to reach on this platform, so the client reports the configuration as unsupported (Riot's `VAN -101`) on some launches while others proceed normally. Nothing in this project attempts to spoof it. See [Vanguard](docs/VANGUARD.md).

For another region, set `RCLOL_REGION` and `RCLOL_LOCALE` before launch. For example `RCLOL_REGION=NA RCLOL_LOCALE=en_US ./scripts/run.sh`. Linux display selection follows `$DISPLAY`; the legacy launcher fallback is `:1`.

## Testing

Start with standalone regression checks, then play a match manually. See [testing](docs/TESTING.md). Do not attach a debugger, query client APIs, inject diagnostic hooks or automate client/game input. This project ships no client-side automation, inspection or profiling helpers.

FPS counters, game presentation requests and physical display refresh are different measurements. Record average and p99 frame times, the active scene, graphics settings, charger/power state and whether the game stayed focused. See [current status](docs/STATUS.md).

On the Ryzen 5 5500 / RX 6600 test PC, ARAM on Hexgate went from 84 to 135 FPS average over 2026-10-13/14, with the slowest 10-second stretches around 119 in the best match (one match so far with Hyprland's direct scanout off; [status](docs/STATUS.md#game-fps-2026-10-1314)). The game-process speed switches and their opt-out files are listed in [setup](docs/SETUP.md#game-process-switches), and passive match capture is described in [testing](docs/TESTING.md#passive-match-capture).

To update an existing installation, exit the game and both clients, then:

```sh
git pull
./scripts/update.sh
sh scripts/run.sh
```

`update.sh` re-applies the patches that changed (reverting the earlier version of each, so other edits in the source tree survive), rebuilds incrementally, and reinstalls the base runtime and the per-user overrides. It refuses to run while a Riot or League process is open.

For updating single components, [incremental update instructions](docs/SETUP.md#updating-an-existing-runtime) explain the server and memory installers, user-owned backups and the full Darling restart needed to activate replacements. Perform activation only after manually exiting the game and both clients.

## Layout

```
scripts/             portable entry points
upstream/manifest.json  exact base revisions and patch ownership
patches/             current source changes, one patch per repository
tools/               runtime templates, installers and standalone regression probes
docs/                setup, testing, status and licensing notes
build/               local sources, outputs and rendered tools (ignored)
```

Darling/upstream components retain their existing licenses; see [third-party notes](NOTICE.md). Original integration tooling is distributed under GPL-3.0; patches retain the licensing of their target files. This project is not affiliated with Riot Games.


