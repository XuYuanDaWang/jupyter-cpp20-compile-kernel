"""Unit tests for jupyter-cpp20-compile-kernel."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupyter_cpp20_kernel.install import install_kernelspec
from jupyter_cpp20_kernel.kernel import (
    CppCompileKernel,
    code_uses_stdin,
    extract_stdin_from_source,
    format_error_source_context,
)


class _DummyKernel(CppCompileKernel):
    def __init__(self) -> None:
        self.execution_count = 1
        self.iopub_socket = None
        self.messages: list[tuple[str, dict]] = []

    def send_response(self, sock, msg_type, content):  # type: ignore[override]
        self.messages.append((msg_type, content))


class TestHelpers(unittest.TestCase):
    def test_extract_stdin_single_line_and_block(self) -> None:
        single = "// @input: 3\n// @input: 10 20 30\nint main() { return 0; }"
        self.assertEqual(extract_stdin_from_source(single), "3\n10 20 30\n")

        block = "/* @input:\n5\n1 2 3 4 5\n*/\nint main() { return 0; }"
        self.assertEqual(extract_stdin_from_source(block), "5\n1 2 3 4 5\n")

        self.assertIsNone(extract_stdin_from_source("int main() { return 0; }"))

    def test_code_uses_stdin_ignores_comments_and_strings(self) -> None:
        self.assertFalse(code_uses_stdin('// cin >> x;\nint main() { const char* s = "scanf"; return 0; }'))
        self.assertTrue(code_uses_stdin("#include <iostream>\nint main() { int x; std::cin >> x; }"))

    def test_format_error_source_context_marks_error_line(self) -> None:
        code = "#include <iostream>\nint main() {\n    int a = 1;\n    return 0\n}\n"
        clean_err = "main.cpp:4:13: error: expected ';' after return statement"
        ctx = format_error_source_context(code, clean_err)
        self.assertTrue(any(">>   4 |     return 0" in line for line in ctx))


@unittest.skipIf(shutil.which("g++") is None, "g++ compiler is required")
class TestKernelExecution(unittest.TestCase):
    def test_compile_error_emits_error_status_and_line_context(self) -> None:
        k = _DummyKernel()
        res = k.do_execute("#include <iostream>\nint main() {\n    int x = 1\n    return 0;\n}\n", silent=False)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["ename"], "CompileError")
        self.assertEqual(k.messages[-1][0], "error")
        tb = "\n".join(res["traceback"])
        self.assertIn("报错位置源码对照", tb)

    def test_repeated_execution_with_int_main_and_input_has_no_redefinition(self) -> None:
        k = _DummyKernel()
        code = (
            "// @input: 3\n"
            "// @input: 10 20 30\n"
            "#include <iostream>\n"
            "using namespace std;\n"
            "int helper(int x) { return x * 2; }\n"
            "int main() {\n"
            "    int n, v, s = 0;\n"
            "    cin >> n;\n"
            "    for (int i = 0; i < n; ++i) { cin >> v; s += helper(v); }\n"
            "    cout << \"Result=\" << s << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        r1 = k.do_execute(code, silent=False)
        r2 = k.do_execute(code, silent=False)
        self.assertEqual(r1["status"], "ok")
        self.assertEqual(r2["status"], "ok")
        self.assertIn(("stream", {"name": "stdout", "text": "Result=120\n"}), k.messages)

    def test_nonzero_exit_code_emits_error(self) -> None:
        k = _DummyKernel()
        res = k.do_execute("int main() { return 2; }", silent=False)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["ename"], "ExitCode2")


class TestInstaller(unittest.TestCase):
    def test_install_preserves_existing_kernels_and_merges_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            share_dir = Path(tmp) / "share" / "jupyter"
            existing_kernel = share_dir / "kernels" / "xcpp20"
            existing_kernel.mkdir(parents=True)
            (existing_kernel / "kernel.json").write_text('{"display_name": "C++20"}', encoding="utf-8")

            settings_dir = share_dir / "lab" / "settings"
            settings_dir.mkdir(parents=True)
            (settings_dir / "overrides.json").write_text('{"custom": {"flag": 1}}', encoding="utf-8")

            installed = install_kernelspec(share_dir)
            self.assertTrue((installed / "kernel.json").is_file())
            self.assertTrue((existing_kernel / "kernel.json").is_file())

            overrides = json.loads((settings_dir / "overrides.json").read_text(encoding="utf-8"))
            self.assertEqual(overrides["custom"], {"flag": 1})
            self.assertTrue(overrides["@jupyterlab/notebook-extension:tracker"]["codeCellConfig"]["lineNumbers"])


if __name__ == "__main__":
    unittest.main()
