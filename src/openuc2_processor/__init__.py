"""openUC2 Processor — download and process ImSwitch/openUC2 datasets in napari."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openuc2-processor")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
