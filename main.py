"""Forge Lite entry point.  Run with:  python main.py"""
import sys


def main() -> int:
    try:
        from forge.console import ConsoleApp
    except ImportError as error:
        print(f"A required package is missing ({error}).\n"
              "Install everything with:  pip install -r requirements.txt")
        return 1
    ConsoleApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
