#!/usr/bin/env python3
"""Build a read-only code-signature probe against Darling's SDK."""
import riot_build as rb

rb.build_c_probe(
    "riot-codesign-check",
    rb.ROOT / "tools/riot-codesign-check.c",
    rb.DARLING_SRC / "build/src/external/security/trust/trustd/CMakeFiles/trustd.dir/flags.make",
    frameworks=("Security", "CoreFoundation"),
)
