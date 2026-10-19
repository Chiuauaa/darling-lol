#!/usr/bin/env python3
"""Shared helpers for the per-component rebuild and guest-probe builders.

Every ``build-riot-*.py`` used to re-implement the same steps: read a CMake
``flags.make``, refresh the clang resource include, compile an object and link
it against the guest SDK. Centralising them keeps a single definition of the
resource-directory fix and of the guest link line.

``load_flags`` always refreshes the clang resource include. A tree configured
with an older clang otherwise keeps ``/usr/lib/clang/<major>/include`` and every
object that includes a clang header fails to build after an upgrade.

Scripts run before ``configure.py`` renders ``tools/`` into ``build/runtime/tools``
still carry the literal SDK token. ``darling_sdk`` falls back to
``build/config.json`` so a builder works from either location.
"""
from pathlib import Path
import json
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent.parent
DARLING_SRC = ROOT / "build/darling-src"

# Flags.make files reused as a generic source of the configured toolchain flags.
COREVIDEO_FLAGS = DARLING_SRC / "build/src/frameworks/CoreVideo/CMakeFiles/CoreVideo.dir/flags.make"
METAL_FLAGS = DARLING_SRC / "build/src/external/metal/CMakeFiles/Metal.dir/flags.make"
# Guest startup headers the low-level probes (clock, ulock, kqueue objects) need.
ELFCALLS = DARLING_SRC / "src/startup/mldr/elfcalls"

# Split so configure.py's str.replace does not rewrite this fallback.
SDK_TOKEN = "@DARLING_" + "SDK@"


def clang_resource_dir(compiler="clang"):
    return subprocess.check_output([compiler, "-print-resource-dir"], text=True).strip()


def refresh_clang_includes(values, resource_dir=None):
    """Point any ``/usr/lib/clang/<major>/include`` at the running clang's own
    resource directory."""
    resource_dir = resource_dir or clang_resource_dir()
    return [re.sub(r"/usr/lib/clang/\d+/include", resource_dir + "/include", value)
            for value in values]


def load_flags(flags_file, prefix="C", resource_dir=None):
    """Parse a CMake ``flags.make`` into ``{token: [arguments]}``.

    Only ``<prefix>_*`` keys are returned (``C_DEFINES``/``C_INCLUDES``/``C_FLAGS``
    or their ``CXX_*`` equivalents), with the clang resource include refreshed.
    """
    resource_dir = resource_dir if resource_dir is not None else clang_resource_dir()
    flags = {}
    for line in Path(flags_file).read_text().splitlines():
        if line.startswith(prefix + "_") and " = " in line:
            key, value = line.split(" = ", 1)
            flags[key] = refresh_clang_includes(shlex.split(value), resource_dir)
    return flags


def compile_object(compiler, flags, prefix, source, output, extra=()):
    """Compile one object with the configured defines/includes/flags."""
    subprocess.run([compiler, *flags[prefix + "_DEFINES"], *flags[prefix + "_INCLUDES"],
                    *flags[prefix + "_FLAGS"], *extra, "-c", str(source), "-o", str(output)],
                   check=True)


def link_probe(compiler, objects, output, libraries=("-lSystem",), frameworks=(),
               isysroot=None, extra=()):
    """Link guest objects against the Darling SDK into a runnable probe."""
    isysroot = isysroot or darling_sdk()
    arguments = [compiler, "-target", "x86_64-apple-macosx11.0", "-fuse-ld=lld", "-nostdlib",
                 "-isysroot", isysroot, *[str(obj) for obj in objects], *libraries]
    for framework in frameworks:
        arguments += ["-framework", framework]
    arguments += list(extra)
    arguments += ["-o", str(output)]
    subprocess.run(arguments, check=True)


def darling_sdk():
    """The guest SDK path, read from ``build/config.json`` when present so the
    builder also runs from an unrendered ``tools/`` copy."""
    config = ROOT / "build/config.json"
    if config.is_file():
        return json.loads(config.read_text())["sdk"]
    return SDK_TOKEN


def build_c_probe(name, source, flags_file, *, extra=(), frameworks=(),
                  libraries=("-lSystem",), link_extra=(), compiler="clang"):
    """Compile ``source`` and link the ``build/<name>`` guest probe.

    The object lands at ``build/<name>.o`` and the binary at ``build/<name>``,
    matching the layout the existing ``build-riot-*-check.py`` scripts used.
    """
    flags = load_flags(flags_file, "C")
    obj = ROOT / "build" / (name + ".o")
    compile_object(compiler, flags, "C", source, obj, extra=extra)
    link_probe(compiler, (obj,), ROOT / "build" / name,
               libraries=libraries, frameworks=frameworks, extra=link_extra)
    return obj
