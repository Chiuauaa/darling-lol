#!/usr/bin/env python3
"""Build the DNS configuration parser probe against Darling's SDK."""
import riot_build as rb

rb.build_c_probe(
    "riot-dns-config-check",
    rb.ROOT / "tools/riot-dns-config-check.c",
    rb.DARLING_SRC / "build/src/external/configd/CMakeFiles/system_configuration.dir/flags.make",
)
