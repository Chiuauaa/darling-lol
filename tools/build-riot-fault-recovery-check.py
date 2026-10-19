#!/usr/bin/env python3
"""Compile the guest signal recovery probe using Darling's configured headers."""
import riot_build as rb

rb.build_c_probe(
    "riot-fault-recovery-check",
    rb.ROOT / "tools/riot-fault-recovery-check.c",
    rb.DARLING_SRC / "build/src/external/security/trust/trustd/CMakeFiles/trustd.dir/flags.make",
    extra=("-fno-omit-frame-pointer",),
)
