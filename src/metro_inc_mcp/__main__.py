import sys


def main() -> None:
    if sys.argv[1:2] == ["login"]:
        from .login import main as login

        login(sys.argv[2:])
        return
    from .server import (
        run,  # imported here: the server module needs METRO_BANNER at import time
    )

    run()


if __name__ == "__main__":
    main()
