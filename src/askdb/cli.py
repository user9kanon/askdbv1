"""`askdb` command line."""

from __future__ import annotations

import argparse
import os
import sys

from askdb.config import ConfigError, load_config, validate_config
from askdb.config.validate import CONFIG_ENV


def _validate_config(args: argparse.Namespace) -> int:
    path = args.config or os.environ.get(CONFIG_ENV)
    if not path:
        print(f"error: pass --config or set {CONFIG_ENV}", file=sys.stderr)
        return 2
    try:
        cfg = load_config(path)
        warnings = validate_config(cfg)
    except ConfigError as e:
        print(f"{path}: invalid config\n{e}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"{path}: OK ({cfg.name}: {len(cfg.tables)} tables, {len(cfg.metrics)} metrics)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="askdb")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate-config", help="validate the database config (SPEC 4.2)")
    p.add_argument("--config", help="config path (default: $ASKDB_DATABASE_CONFIG)")
    p.set_defaults(func=_validate_config)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
