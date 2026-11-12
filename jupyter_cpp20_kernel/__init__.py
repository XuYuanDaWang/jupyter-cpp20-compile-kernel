"""Compile-and-run C++20 Jupyter kernel."""

__version__ = "1.1.0"

from .kernel import CppCompileKernel

__all__ = ["CppCompileKernel", "__version__"]
