"""`golem` console script — dispatches subcommands."""
import sys

from forge import server as forge_server


_COMMANDS = {
    "forge": forge_server.main,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        names = ", ".join(_COMMANDS)
        print(f"usage: golem <command>\ncommands: {names}", file=sys.stderr)
        sys.exit(0 if len(sys.argv) >= 2 else 2)

    cmd = sys.argv.pop(1)
    if cmd not in _COMMANDS:
        print(f"golem: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(2)
    _COMMANDS[cmd]()


if __name__ == "__main__":
    main()
