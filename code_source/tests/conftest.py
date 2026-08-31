"""Configuration pytest commune : sortie console en UTF-8 (émojis des modules applicatifs)."""
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
