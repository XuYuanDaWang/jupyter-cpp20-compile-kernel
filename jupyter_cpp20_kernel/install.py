"""Installer for jupyter-cpp20-compile-kernel.

Installs the `cpp20_gpp` (or custom-named) kernelspec alongside existing kernels
without removing or overwriting `xcpp20` / `python3`, and optionally enables
JupyterLab cell line numbers by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_KERNEL_NAME = "cpp20_gpp"
DEFAULT_DISPLAY_NAME = "C++20 (g++ 整格编译)"


def install_kernelspec(
    jupyter_share_dir: Path,
    *,
    python_executable: str = sys.executable,
    kernel_name: str = DEFAULT_KERNEL_NAME,
    display_name: str = DEFAULT_DISPLAY_NAME,
    enable_line_numbers: bool = True,
) -> Path:
    target_kernel_dir = jupyter_share_dir / "kernels" / kernel_name
    target_kernel_dir.mkdir(parents=True, exist_ok=True)

    kernel_spec = {
        "argv": [
            python_executable,
            "-m",
            "jupyter_cpp20_kernel.kernel",
            "-f",
            "{connection_file}",
        ],
        "display_name": display_name,
        "language": "cpp",
        "metadata": {"debugger": False},
        "kernel_protocol_version": "5.5",
    }
    (target_kernel_dir / "kernel.json").write_text(
        json.dumps(kernel_spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if enable_line_numbers:
        _merge_line_numbers(jupyter_share_dir)

    return target_kernel_dir


def _merge_line_numbers(jupyter_share_dir: Path) -> None:
    settings_dir = jupyter_share_dir / "lab" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    overrides_path = settings_dir / "overrides.json"

    overrides: dict[str, object] = {}
    if overrides_path.is_file():
        try:
            loaded = json.loads(overrides_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                overrides = loaded
        except Exception:
            overrides = {}

    tracker_cfg = overrides.setdefault("@jupyterlab/notebook-extension:tracker", {})
    if isinstance(tracker_cfg, dict):
        for cell_key in ("codeCellConfig", "markdownCellConfig", "rawCellConfig"):
            cell_cfg = tracker_cfg.setdefault(cell_key, {})
            if isinstance(cell_cfg, dict):
                cell_cfg["lineNumbers"] = True

    editor_cfg = overrides.setdefault("@jupyterlab/fileeditor-extension:plugin", {})
    if isinstance(editor_cfg, dict):
        inner = editor_cfg.setdefault("editorConfig", {})
        if isinstance(inner, dict):
            inner["lineNumbers"] = True

    overrides_path.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    tracker_schema = (
        jupyter_share_dir
        / "lab"
        / "schemas"
        / "@jupyterlab"
        / "notebook-extension"
        / "tracker.json"
    )
    if tracker_schema.is_file():
        data = json.loads(tracker_schema.read_text(encoding="utf-8"))
        props = data.get("properties", {})
        if isinstance(props, dict):
            for key in ("codeCellConfig", "markdownCellConfig", "rawCellConfig"):
                prop = props.get(key, {})
                if isinstance(prop, dict) and isinstance(prop.get("default"), dict):
                    prop["default"]["lineNumbers"] = True
        tracker_schema.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Install the C++20 g++ compile-and-run Jupyter kernel."
    )
    parser.add_argument(
        "--jupyter-share-dir",
        type=Path,
        default=Path(sys.prefix) / "share" / "jupyter",
        help="Target <sys.prefix>/share/jupyter directory (default: current Python prefix).",
    )
    parser.add_argument(
        "--kernel-name",
        type=str,
        default=DEFAULT_KERNEL_NAME,
        help="Kernelspec directory name (default: cpp20_gpp).",
    )
    parser.add_argument(
        "--display-name",
        type=str,
        default=DEFAULT_DISPLAY_NAME,
        help="Kernel display name in JupyterLab.",
    )
    parser.add_argument(
        "--no-line-numbers",
        action="store_true",
        help="Do not modify JupyterLab overrides.json to enable cell line numbers.",
    )
    args = parser.parse_args(argv)

    installed_dir = install_kernelspec(
        args.jupyter_share_dir.resolve(),
        kernel_name=args.kernel_name,
        display_name=args.display_name,
        enable_line_numbers=not args.no_line_numbers,
    )
    print(f"Installed '{args.kernel_name}' ({args.display_name}) into: {installed_dir}")


if __name__ == "__main__":
    main()
