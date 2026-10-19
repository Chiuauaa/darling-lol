# Graphics stack reference: OpenGL, Vulkan, Metal and the layers that translate between them

Consolidated from primary sources on 2026-10-19 for the parallel sessions working on
this tree. It answers "how do these APIs actually work, and where does each translation
layer sit" so that frame-path, presentation and telemetry work share one model instead
of four different mental pictures.

Scope note: everything here is read-only knowledge. Nothing in this file changes a patch,
a runtime overlay or a game-start policy. Sources are listed at the end.

---

## 1. The three APIs, side by side

| | OpenGL | Vulkan | Metal |
|---|---|---|---|
| Model | one global state machine, bound to a single current context | object-based, no global state; state is local to a command buffer | object-oriented (Obj-C / Swift / C++), explicit command structure |
| Issue/execute | calls are executed (mostly) immediately and sequentially on the calling thread | commands are recorded into command buffers and submitted to queues | commands are *encoded* into encoders, then the command buffer is committed; CPU encoding is independent per thread |
| Threading | one context current per thread; sharing requires explicit share contexts and locks | designed multi-threaded: pools, buffers and queues per thread | encoding is thread-independent; submission is asynchronous |
| Shaders | GLSL source, compiled by the driver at run time (or SPIR-V via `GL_ARB_gl_spirv`) | SPIR-V bytecode, pre-compiled and validated offline | MSL (C++-based), pre-compiled to AIR |
| Memory | hidden; driver manages it | explicit: allocate, bind, alias, choose memory types/heaps | explicit storage modes (shared / managed / private), CPU/GPU coherent where declared |
| Synchronization | mostly hidden; implicit ordering, `glFinish`/`glFenceSync` | fully explicit: binary and timeline semaphores, fences, barriers, pipeline stages/access masks | `MTLEvent`/`MTLSharedEvent` for GPU ordering, `MTLFence` for encoders, completion handlers on the command buffer |
| Errors | extensive runtime checks, `glGetError` | none at run time in the driver; the validation layer is a separate component | validation layers in Xcode; errors surface as API failures/logging |
| Context/drawable creation | out of spec: GLX (X11), WGL (Windows), CGL (macOS), EGL (portable, used by GLES and as a vendor-neutral surface layer) | out of core: WSI extensions — `VK_KHR_surface` plus `VK_KHR_xlib_surface` / `_xcb_surface` / `_wayland_surface` / `_win32_surface` / `_metal_surface` — and `VK_KHR_swapchain` | `MTLDevice` -> `MTLCommandQueue` -> `MTLCommandBuffer` -> encoders; windows via `CAMetalLayer` + `MTLDrawable` |
| Inheritance | successor is Vulkan; no further development since 4.6 (2017) | successor of OpenGL; adopted the Mantle design | Apple-only, replaced OpenGL on Apple platforms (deprecated there since 2018) |

Two Vulkan facts that shape every layer built on it:

- **A Vulkan driver must ingest SPIR-V.** That is what makes translation layers possible
  at all: an API can be re-implemented by *emitting* Vulkan commands instead of patching
  a driver. It is also why shader translation (`glslang`, `SPIRV-Cross`) is a first-class
  part of any such layer.
- **All synchronization and memory is the application's job.** A layer that gets a
  semaphore, a barrier or a memory type wrong produces hangs, black frames or device-lost
  errors, not an error code. This is the class of bug behind most of the graphics
  findings in this repository.

### Metal's command structure (the part that matters here)

- One `MTLDevice` per GPU; one or more `MTLCommandQueue`s from it.
- A `MTLCommandBuffer` is created, filled by one or more encoders in order
  (`MTLRenderCommandEncoder`, `MTLComputeCommandEncoder`, `MTLBlitCommandEncoder`),
  then `commit`ted; `addCompletedHandler:` runs when the GPU finished it.
- **Encoders are single-use and ordered.** An encoder is ended/closed before the next
  segment of work. This is exactly the ordering the tree's *deferred replay worker*
  re-establishes when it replays a whole command buffer's encoder list.
- Presenting is a drawable handshake: `CAMetalLayer.nextDrawable` -> render ->
  `presentDrawable` -> commit. A drawable is recycled only after its command buffer
  completes.
- **Metal exposes very few concurrent drawables.** The MoltenVK runtime guide documents
  a hard limit of 3 swapchain images, and that the system can hold an image a little
  longer when "Direct to Display" is used (full-screen, no compositor copy). Under
  triple buffering plus a compositor this is what produces `Metal Device timed out`
  when a drawable is not returned to the pool in time — the symptom resolved in
  `docs/WORKLOG-OpenGL-EGL.md` (symptom 4) by flushing the subwindow before EGL first
  attaches.
- MSL is pre-compiled to AIR; importing AIR is Apple-runtime business, so any
  Metal-on-other-API layer must translate the *shader* too, not just the API calls.

---

## 2. Direction matters: the five translation layers in play

Every layer below is one-directional. Confusing the direction is the most common source
of wrong reasoning in these threads.

```
                 ┌──────────────────────────── Apple / this project ───────────────────────────┐
   League (game) │  Metal  ──┬──>  Metal.framework (Darling)  ──>  Indium  ──> Vulkan  ──> GPU   │
                 │          └──>  OpenGL (Riot client, ANGLE) ──> CGL ──> EGL ──> GL/ANGLE     │
                 └─────────────────────────────────────────────────────────────────────────────┘

                 ┌──────────────────────────── Wine / Proton ─────────────────────────────────┐
   Windows game  │  D3D8/9/10/11 ──> DXVK ──> Vulkan        D3D12 ──> vkd3d-proton ──> Vulkan  │
                 │  (alternative) D3D8/9/10/11 ──> wined3d ──> OpenGL  ──> driver                │
                 └─────────────────────────────────────────────────────────────────────────────┘

                 ┌───────────────────────── Apple hardware (reference, opposite direction) ────┐
   macOS Vulkan  │  Vulkan  ──> MoltenVK (deprecated) / KosmicKrisp ──> Metal                   │
                 └─────────────────────────────────────────────────────────────────────────────┘
```

1. **MoltenVK — Vulkan on Metal (Vulkan -> Metal).** Khronos' layered Vulkan 1.4
   implementation built on Metal, plus `MoltenVKShaderConverter` (SPIRV-Cross) for
   SPIR-V -> MSL. Compliance comes from three buckets: direct mapping (the vast
   majority), synthesized behaviour (e.g. an extra shader stage), and non-compliance
   where the APIs are too far apart. **Khronos has deprecated MoltenVK**; the
   recommended Vulkan-on-Metal path on Apple Silicon is now **KosmicKrisp** (Mesa),
   with MoltenVK kept for Intel Macs and iOS. Not our direction, but it is the
   reference implementation of "wrap one API in another" and the source of the
   triple-buffering and swapchain-image constraints quoted above.

2. **Indium — Metal on Vulkan (Metal -> Vulkan).** A C++ implementation of a
   Metal-like API on top of Vulkan, used by Darling's `Metal.framework`. Pinned here at
   `8423a7d2` in `patches/metal--deps--indium.patch`. Its README requires **Vulkan 1.3**
   (or `VK_EXT_extended_dynamic_state`/`2` and timeline semaphores) and states the
   deviances explicitly: `std::vector` instead of `NSArray`, `std::string` instead of
   `NSString`, `std::function` instead of blocks, and `shared_ptr` reference counting
   instead of Obj-C `retain`/`release`. **Iridium** (same repo) translates pre-compiled
   Metal shaders (AIR) to SPIR-V; `mtl2spv` is its CLI. So in this tree the shader path
   is Metal/AIR -> SPIR-V, the mirror image of MoltenVK's SPIR-V -> MSL.
   `src/external/metal` (`patches/metal.patch`) is the Obj-C ABI layer that turns
   `MTLDevice`/`MTLCommandBuffer`/`MTLRenderCommandEncoder`/... calls into Indium.

3. **Darling's OpenGL.framework — CGL on host EGL.** Out of scope for the API
   semantics above but central to presentation here: the framework `dlopen`s the host
   EGL privately (`RTLD_LOCAL`) so native EGL stays out of ANGLE's dependency scope;
   `CGLCreateContext` derives the requested GL profile from the pixel format and walks a
   retry ladder (drop the core-profile mask -> driver defaults -> re-choose the
   `EGLConfig` -> rebuild the EGL display/config from its own private Xlib connection).
   It never depends on AppKit's transient `X11Display` surviving, because
   `CGLRegisterNativeDisplay` is fed that transient connection while NVIDIA's
   threaded-optimizations worker can invalidate a shared display (hence the default
   `__GL_THREADED_OPTIMIZATIONS=0`).

4. **DXVK / vkd3d-proton — D3D on Vulkan (Proton's answer to the same problem).**
   DXVK implements D3D8/9/10/11 by emitting Vulkan, with an internal shader cache and
   `VK_EXT_graphics_pipeline_library` support to move shader compilation to load time
   instead of draw time. vkd3d-proton implements D3D12 on Vulkan 1.3 and states hard
   driver requirements (descriptor indexing, `VK_EXT_robustness2`,
   `VK_KHR_push_descriptor`, timeline semaphores), i.e. the same "modern features are
   mandatory" posture Indium takes. `wined3d` is the alternative: D3D on OpenGL, which
   is why `PROTON_USE_WINED3D=1` changes the whole backend.

5. **Wine's own Vulkan plumbing — the layer that has no counterpart in Darling.**
   Worth understanding because it is the closest solved problem to what Indium does:
   - `winevulkan.dll` is an **ICD** (ICD version 4): it wraps *dispatchable handles*
     (`VkInstance`, `VkDevice`, ...) because the Vulkan loader stores private data at
     the start of each dispatchable handle, and it converts structure layouts where
     Win32 and 32-bit Linux alignment differ. The code is generated from `vk.xml` by
     `dlls/winevulkan/make_vulkan`.
   - Window-system integration is split per driver: `winex11.drv/vulkan.c` builds a
     `VkXlibSurfaceCreateInfoKHR` from the X11 display and window and hands it to the
     host loader; `winewayland.drv` does the equivalent for Wayland. The surface is the
     only part the driver layer owns.
   - Wine's own notes warn that changes in one WSI driver usually need mirroring in the
     others — the same coupling that shows up here as "the same EGL/drawable bug exists
     for the toplevel and for the subwindow".

---

## 3. Darling specifics that sit under the graphics stack

From `docs.darlinghq.org` (*internals*):

- **Mach-O world vs ELF host.** `mldr` loads Mach-O binaries and also acts as the ELF
  bridge: it populates `struct elf_calls` (via the `applep` environment array) with host
  function pointers, so Mach-O code can call ELF functions. `wrapgen` generates Mach-O
  wrapper libraries whose *symbol resolvers* `dlopen`/`dlsym` a host ELF library at load
  time, installed under `/usr/lib/native` in the prefix. This is precisely how the
  native EGL/X11 libraries are reached from the Mach-O OpenGL/CGL code.
- **darlingserver** carries process/thread emulation, Mach ports and exceptions, kqueue
  channels and interrupts. Anything graphics-adjacent that needs a Mach port, a
  semaphore or an IOSurface crosses this boundary.
- **Overlay activation** is a namespace property: replacing a framework on disk does not
  reach a running namespace; it needs `darling shutdown` + `sh scripts/run.sh`. This is
  why a rebuilt `libindium` must not be judged until a restart has happened.
- **The Mach-O side keeps its own Obj-C ABI**, so Metal here is a hand-written
  `Metal.framework`, and QuartzCore's `CALayer`/`CAMetalLayer` compositor sits above it
  and publishes frames for other windows through `/dev/shm/darling-ca-frame-*`
  (`presentRemoteCAFrame`), bypassing `CARenderer`.

## 4. Where the presentation boundary actually is in this tree

Two different present paths coexist, and conflating them wastes debugging time:

- **AppKit/GL path.** `AppKit` -> `CGLFlushDrawable` -> EGL `eglSwapBuffers` on a window
  surface. Requires a valid `CGLGetWindow` (a drawable), and a usable default
  framebuffer: the NVIDIA `GL_DRAW_BUFFER == GL_NONE` defect fixed in
  `CGLContextMakeCurrentAndAttachToWindow` is in this path.
- **Layer/Metal path.** `CAMetalLayer` drawable -> `QuartzCore` compositor ->
  `CARenderer`/`CALayerContext` render -> GL present, or the remote CA frame path for
  Chromium windows.

The Metal frame is handed to an **OpenGL (EGL) context that presents it**, using opaque
file descriptors — the Vulkan/GL external-object handoff (`GL_EXT_external_objects` /
`_fd`, on the Vulkan side `VK_KHR_external_memory_fd` / `VK_KHR_external_semaphore_fd`).
Two consequences that are documented in `docs/TROUBLESHOOTING.md` and confirmed by the
trace logs (`drawable GL import ... vkTiling=optimal glTiling=optimal ok`,
`drawable GL semaphore ... import_error=0x0 wait_error=0x0 ok`):

- The fds are only valid when Vulkan and GL are on the **same GPU**. Hybrid laptops put
  Indium on the first enumerated Vulkan device (normally the iGPU) and the EGL context
  follows it, so the discrete GPU stays idle and an NVIDIA-only run is unvalidated.
- Import/semaphore errors here look like *presentation* failures (black window, timeouts),
  not like rendering failures, even when the rendered texture is correct.

## 5. What the frame path costs, in API terms

The measured bottleneck (`docs/WORKLOG-FPS-2026-10-18.md`, `docs/STATUS.md`) is CPU-side
Vulkan work on **one ordered deferred-replay worker** (`indium-submit`): ~0.55 core,
~0.53 of it kernel time, `State: R`, few page faults — syscall-bound, not compute-bound,
while the presenting thread waits in `drain@commit` and `vkQueueSubmit2` itself is ~0 ms.
Read against the API model above, that is the predictable cost of Metal-on-Vulkan:

- Metal's encoder model lets an app record many small encoders; Indium must **replay**
  them as Vulkan command buffers, and the replay is inherently serialized because the
  Metal ordering guarantee has to be preserved.
- **Kernel time, not user time, means the cost is in the driver entries and
  submissions** (barrier `vkCmdPipelineBarrier*`, `vkQueueSubmit2`, fence/semaphore
  waits, memory binding), matching the tree's open items: per-frame
  `vkCreateFramebuffer`/`vkDestroyFramebuffer` churn (~26/frame), binary-semaphore
  destruction in the completion callback (~2 ms/frame), and the deliberately disabled
  async upload fence (measured slower when enabled).
- **Timeline semaphores** are what Indium requires for a reason: they collapse
  per-frame binary-semaphore create/destroy into counter waits. Any change that moves
  this tree toward timeline semaphores on the presentation boundary attacks the
  measured kernel time directly; any change that keeps creating a binary semaphore per
  commit conserves the cost that was measured.

## 6. Sources

- Khronos: `MoltenVK` README and `Docs/MoltenVK_Runtime_UserGuide.md` (swapchains,
  limitations, shader conversion, deprecation notice pointing at KosmicKrisp);
  `khronos.org/opengl` (OpenGL 4.6 profile/GLSL/registry layout).
- `darlinghq/indium` README and `devnotes.md` (Vulkan 1.3 / timeline semaphore
  requirements, ABI deviances, Iridium AIR -> SPIR-V).
- Darling docs, *internals*: "Calling host system APIs" (mldr ELF bridge, `elf_calls`,
  `wrapgen` symbol resolvers, `wrap_elf`), plus the loader/threading/darlingserver
  chapters.
- Wine: `dlls/winevulkan/loader.c` and `make_vulkan` header comments (ICD version 4,
  dispatchable-handle wrapping, alignment conversion, code generated from `vk.xml`),
  `dlls/winex11.drv/vulkan.c` (`VkXlibSurfaceCreateInfoKHR` from `gdi_display` + window),
  `dlls/wined3d/wined3d_main.c` (D3D on OpenGL, with VKD3D/Vulkan pieces alongside).
- Proton README (component list: Wine fork, DXVK, vkd3d-proton, dxvk-nvapi, FEX,
  GStreamer, OpenXR; `PROTON_*` runtime knobs) ; DXVK README (D3D8–11 -> Vulkan,
  HUD, GPL shader compilation); vkd3d-proton README (D3D12 -> Vulkan 1.3, hard driver
  feature requirements).
- ANGLE README (GLES -> Vulkan / desktop GL / D3D / Metal; implements EGL 1.5).
- Wikipedia: *Metal (API)* (command structure, MSL, storage modes, Metal 4), *Vulkan*
  (OpenGL-vs-Vulkan table, WSI, versions, MoltenVK history), *OpenGL* (design, context
  toolkits, GLX/WGL/CGL bindings, version history).
