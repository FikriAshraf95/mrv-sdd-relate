"""SDD Graph: a spec-driven repo as one Relate graph (distribution ``relate-sdd``)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("relate-sdd")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
