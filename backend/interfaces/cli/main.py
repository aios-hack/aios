from __future__ import annotations

import sys
from importlib import import_module
from typing import Callable, Sequence

from backend.interfaces.cli.runner import EXIT_VALIDATION, run

COMMANDS: dict[str, str] = {
    "campaign": "backend.interfaces.cli.final_campaign",
    "emit": "backend.interfaces.cli.emit",
    "jarvis": "backend.interfaces.cli.jarvis",
    "npv": "backend.interfaces.cli.npv",
    "run": "backend.interfaces.cli.run",
    "selfcheck": "backend.interfaces.cli.selfcheck",
    "showcase": "backend.contexts.showcase.application.build_showcase",
    "surrogate-adapt": "backend.interfaces.cli.surrogate.adapt",
    "surrogate-adapt-audit": "backend.interfaces.cli.surrogate.adapt_audit",
    "surrogate-audit": "backend.interfaces.cli.surrogate.audit",
    "surrogate-check": "backend.interfaces.cli.surrogate.check",
    "surrogate-release": "backend.interfaces.cli.surrogate.release",
    "surrogate-screen": "backend.interfaces.cli.surrogate.screen",
    "surrogate-screen-verify": "backend.interfaces.cli.surrogate.screen_verify",
    "surrogate-weight-soup": "backend.interfaces.cli.surrogate.weight_soup",
    "verify-reference": "backend.interfaces.cli.verify_reference",
    "web": "backend.interfaces.cli.web",
}

NO_ARGUMENT_COMMANDS: frozenset[str] = frozenset({"showcase"})

USAGE = "usage: aios <command> [arguments]\n\ncommands:\n" + "".join(
    f"  {name}\n" for name in sorted(COMMANDS)
)


def resolve(command: str) -> Callable[..., int | None]:
    module = import_module(COMMANDS[command])
    entrypoint = getattr(module, "main")
    return entrypoint


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        sys.stdout.write(USAGE)
        return 0
    command = args[0]
    if command not in COMMANDS:
        sys.stderr.write(f"unknown command: {command}\n\n{USAGE}")
        return EXIT_VALIDATION
    entrypoint = resolve(command)
    rest = args[1:]
    if command in NO_ARGUMENT_COMMANDS:
        if rest:
            sys.stderr.write(f"{command} takes no arguments\n")
            return EXIT_VALIDATION
        return run(entrypoint)
    return run(entrypoint, rest)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMMANDS",
    "NO_ARGUMENT_COMMANDS",
    "USAGE",
    "main",
    "resolve",
]
