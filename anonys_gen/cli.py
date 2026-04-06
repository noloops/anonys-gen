# ANONYS FINITE STATE MACHINE FRAMEWORK
# Copyright (c) 2026 Jan Hofmann <anonys@noloops.ch>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://apache.org

"""CLI entry point for anonys-gen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .generator import GeneratorConfig, generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonys C++ FSM code generator")
    parser.add_argument("--config", type=Path, help="JSON config file")
    args = parser.parse_args()

    if args.config:
        data = json.loads(args.config.read_text(encoding="utf-8"))
        config = GeneratorConfig(
            fsm_definitions=[Path(p) for p in data["fsm_definitions"]],
            anonys_output_dir=data["anonys_output_dir"],
            fsm_output_dir=data["fsm_output_dir"],
            project_name=data["project_name"],
        )
        generate(config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
