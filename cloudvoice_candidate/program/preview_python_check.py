"""File-based probe avoids PowerShell 5 native -c quoting differences."""
import struct
import sys
import json


def main():
    if sys.version_info[:2] not in ((3, 11), (3, 12)) or struct.calcsize("P") != 8:
        raise SystemExit(1)
    try:
        import tkinter
    except ImportError:
        raise SystemExit(1)
    print(json.dumps(sys.executable, ensure_ascii=True))


if __name__ == "__main__":
    main()
