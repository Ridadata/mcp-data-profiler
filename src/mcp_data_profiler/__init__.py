"""Profile local datasets for AI agents over the Model Context Protocol."""

from .profiler import ProfileError, profile_dataset, profile_to_json

__version__ = "0.1.0"
__all__ = ["ProfileError", "__version__", "profile_dataset", "profile_to_json"]
