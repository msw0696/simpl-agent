"""SIMPL Windows file format: lossless raw layer and semantic model."""

from .rawfile import RawFile, Record, parse, read

__all__ = ["RawFile", "Record", "parse", "read"]
