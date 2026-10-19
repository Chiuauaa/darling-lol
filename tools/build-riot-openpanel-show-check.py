#!/usr/bin/env python3
"""Build the NSOpenPanel presentation probe against AppKit."""
from pathlib import Path
import json
import shlex
import subprocess

here = Path(__file__).resolve()
root = here.parent
while not (root / "scripts" / "common.py").exists():
    root = root.parent

sdk = json.loads((root / "build" / "config.json").read_text())["sdk"]
appkit = root / "build/darling-src/build/src/external/cocotron/AppKit"
flags = {}
for line in (appkit / "CMakeFiles/AppKit.dir/flags.make").read_text().splitlines():
    if line.startswith("C_") and " = " in line:
        key, value = line.split(" = ", 1)
        flags[key] = shlex.split(value)

name = "riot-openpanel-show-check"
source = root / f"tools/{name}.m"
obj = root / f"build/{name}.o"
binary = root / f"build/{name}"
subprocess.run(["clang", *flags["C_DEFINES"], *flags["C_INCLUDES"], *flags["C_FLAGS"],
                "-fblocks", "-c", str(source), "-o", str(obj)], check=True)
subprocess.run(["clang", "-target", "x86_64-apple-macosx11.0", "-fuse-ld=lld", "-nostdlib",
                "-isysroot", sdk, str(obj), "-lSystem",
                "-framework", "AppKit", "-framework", "Foundation",
                "-framework", "CoreGraphics", "-lobjc", "-o", str(binary)],
               check=True)
