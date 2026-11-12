"""Fine-tuned C++20 compile-and-run Jupyter kernel (based on jupyter-cpp-kernel).

Designed for university C++ lab courses:
1. Students write standard C++ programs with `int main()` in each cell.
2. Every cell execution compiles a fresh translation unit via `g++ -std=c++20 -O0`,
   eliminating Cling/REPL redefinition errors on repeated edits.
3. Compile errors and runtime crashes emit standard Jupyter `error` messages and
   return `status: 'error'` with a numbered source context block around the error line.
4. Standard output emits via `stream` (`stdout`) cleanly.
5. Supports `// @input: ...` or `/* @input: ... */` comments for `std::cin` test
   inputs, with an interactive input box fallback when `cin`/`scanf`/`getline` is
   detected.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ipykernel.kernelbase import Kernel

COMPILER = os.environ.get("JUPYTER_CPP_COMPILER", "g++")
COMPILE_FLAGS = ("-std=c++20", "-O0", "-Wall", "-Wextra")
COMPILE_TIMEOUT_SEC = 10
RUN_TIMEOUT_SEC = 10
MAX_OUTPUT_CHARS = 16_384

_SINGLE_LINE_INPUT_RE = re.compile(
    r"^[ \t]*//[ \t]*@input:[ \t]*(.*)$",
    re.MULTILINE,
)
_BLOCK_INPUT_RE = re.compile(
    r"/\*[ \t]*@input:[ \t]*\r?\n?([\s\S]*?)\*/",
    re.MULTILINE,
)
_CPP_COMMENTS_AND_STRINGS_RE = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[^\n]|[^\'\\\n])*\'',
    re.MULTILINE,
)
_STDIN_USAGE_RE = re.compile(r"\b(?:cin|scanf|getline|getchar|gets|fread)\b")
_ERROR_LINE_RE = re.compile(r"main\.cpp:(\d+)(?::(\d+))?:\s*(?:fatal )?error:")

_SIGNAL_NAMES = {
    signal.SIGSEGV: "SIGSEGV (段错误 / 内存越界或空指针访问)",
    signal.SIGABRT: "SIGABRT (程序异常中止 / abort)",
    signal.SIGFPE: "SIGFPE (浮点或除零异常)",
    signal.SIGILL: "SIGILL (非法指令)",
    signal.SIGBUS: "SIGBUS (总线错误 / 非法内存对齐)",
}


def extract_stdin_from_source(code: str) -> str | None:
    """Extract test stdin from `/* @input: ... */` or `// @input: ...` comments."""
    block_matches = _BLOCK_INPUT_RE.findall(code)
    if block_matches:
        text = "\n".join(part.strip("\r\n") for part in block_matches)
        return text + "\n"

    line_matches = _SINGLE_LINE_INPUT_RE.findall(code)
    if line_matches:
        text = "\n".join(line_matches)
        return text + "\n"

    return None


def code_uses_stdin(code: str) -> bool:
    """Detect whether C++ source likely reads from standard input."""
    stripped = _CPP_COMMENTS_AND_STRINGS_RE.sub(" ", code)
    return bool(_STDIN_USAGE_RE.search(stripped))


def sanitize_compiler_output(stderr: str, source_path: Path) -> str:
    """Replace temporary file paths with `main.cpp` for readable diagnostics."""
    text = stderr.replace(str(source_path), "main.cpp")
    try:
        resolved = str(source_path.resolve())
        text = text.replace(resolved, "main.cpp")
    except OSError:
        pass
    return text.strip()


def first_compiler_error_summary(clean_stderr: str) -> str:
    """Pick the most informative first error line for diagnostics."""
    lines = [line.strip() for line in clean_stderr.splitlines() if line.strip()]
    for line in lines:
        if "error:" in line or "fatal error:" in line:
            return line[:300]
    for line in lines:
        if "Undefined symbols" in line or "undefined reference" in line:
            return "链接错误：未找到 int main() 入口函数或存在未定义符号"
    return (lines[0] if lines else "C++ 编译失败")[:300]


def format_error_source_context(code: str, clean_stderr: str, context_radius: int = 3) -> list[str]:
    """Build a numbered source code snippet around the first reported error line."""
    match = _ERROR_LINE_RE.search(clean_stderr)
    if not match:
        return []
    error_line = int(match.group(1))
    source_lines = code.splitlines()
    if not (1 <= error_line <= len(source_lines)):
        return []

    start = max(1, error_line - context_radius)
    end = min(len(source_lines), error_line + context_radius)
    width = max(3, len(str(end)))

    snippet = ["", f"--- 报错位置源码对照（第 {error_line} 行附近）---"]
    for idx in range(start, end + 1):
        marker = ">>" if idx == error_line else "  "
        snippet.append(f"{marker} {idx:>{width}} | {source_lines[idx - 1]}")
    return snippet


class CppCompileKernel(Kernel):
    implementation = "jupyter_cpp20_compile_kernel"
    implementation_version = "1.1.0"
    language = "cpp"
    language_version = "C++20"
    language_info = {
        "name": "cpp",
        "mimetype": "text/x-c++src",
        "file_extension": ".cpp",
        "codemirror_mode": "text/x-c++src",
        "pygments_lexer": "cpp",
    }
    banner = "C++20 Compile Kernel (g++ -std=c++20 -O0, standard int main() mode)"

    def do_execute(
        self,
        code: str,
        silent: bool,
        store_history: bool = True,
        user_expressions: dict[str, Any] | None = None,
        allow_stdin: bool = False,
        *,
        cell_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del store_history, user_expressions, cell_id, kwargs

        stripped = code.strip()
        if not stripped:
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Compatibility for legacy notebooks that had a separate `main();` cell
        if stripped in {"main();", "main()"}:
            if not silent:
                self._send_stdout(
                    "[提示] 当前 C++20 编译型内核在运行包含 int main() 的单元格时已直接完成编译与执行，无需单独调用 main()。\n"
                )
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        stdin_data = extract_stdin_from_source(code)
        if stdin_data is None and code_uses_stdin(code):
            if allow_stdin and getattr(self, "_allow_stdin", False):
                try:
                    raw = self.raw_input(
                        "检测到 cin/标准输入，请输入测试数据（多行可用 \\n 分隔，也可在代码中写 // @input: 数据）："
                    )
                    stdin_data = raw.replace("\\n", "\n") + "\n"
                except Exception:
                    stdin_data = ""
            else:
                stdin_data = ""

        with tempfile.TemporaryDirectory(prefix="jupyter-cpp20-") as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "main.cpp"
            executable_path = root / "main"
            source_path.write_text(code, encoding="utf-8")

            # 1. Compile with g++ -std=c++20 -O0
            try:
                compile_proc = subprocess.run(
                    [
                        COMPILER,
                        *COMPILE_FLAGS,
                        str(source_path),
                        "-o",
                        str(executable_path),
                    ],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=COMPILE_TIMEOUT_SEC,
                    check=False,
                )
            except FileNotFoundError:
                return self._emit_error(
                    silent=silent,
                    ename="CompilerUnavailableError",
                    evalue=f"未找到 C++ 编译器：{COMPILER}",
                    traceback_lines=[
                        f"系统环境中未找到编译器 '{COMPILER}'，请确认已安装 g++ / Xcode Command Line Tools。"
                    ],
                )
            except subprocess.TimeoutExpired:
                return self._emit_error(
                    silent=silent,
                    ename="CompileTimeoutError",
                    evalue=f"C++ 编译超时（超过 {COMPILE_TIMEOUT_SEC} 秒）",
                    traceback_lines=[
                        f"g++ 编译耗时超过 {COMPILE_TIMEOUT_SEC} 秒，已自动终止。"
                    ],
                )

            if compile_proc.returncode != 0 or not executable_path.is_file():
                clean_err = sanitize_compiler_output(compile_proc.stderr, source_path)
                evalue = first_compiler_error_summary(clean_err)
                lines = clean_err.splitlines() if clean_err else [evalue]
                lines.extend(format_error_source_context(code, clean_err))
                if (
                    "_main" in clean_err
                    or "undefined reference to `main'" in clean_err
                    or "undefined reference to 'main'" in clean_err
                ):
                    lines.append("")
                    lines.append(
                        "[提示] 请在单元格中编写完整的入口函数：int main() { ... }"
                    )
                return self._emit_error(
                    silent=silent,
                    ename="CompileError",
                    evalue=evalue,
                    traceback_lines=lines,
                )

            # 2. Execute the compiled binary
            try:
                run_proc = subprocess.run(
                    [str(executable_path)],
                    cwd=str(root),
                    input=stdin_data if stdin_data is not None else "",
                    capture_output=True,
                    text=True,
                    timeout=RUN_TIMEOUT_SEC,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                partial_out = self._decode_timeout_stream(exc.stdout)
                if partial_out and not silent:
                    self._send_stdout(self._truncate(partial_out))
                return self._emit_error(
                    silent=silent,
                    ename="TimeoutError",
                    evalue=f"程序运行超时（超过 {RUN_TIMEOUT_SEC} 秒）",
                    traceback_lines=[
                        f"程序运行超过 {RUN_TIMEOUT_SEC} 秒未结束，可能存在死循环或等待额外的 cin 输入。",
                        "提示：如果程序包含 cin，请在代码顶部添加注释提供测试输入，例如：",
                        "// @input: 5 10 20",
                    ],
                )

            stdout_text = run_proc.stdout or ""
            stderr_text = run_proc.stderr or ""

            if run_proc.returncode != 0:
                if stdout_text and not silent:
                    self._send_stdout(self._truncate(stdout_text))
                ename, evalue, tb_lines = self._format_runtime_failure(
                    run_proc.returncode, stderr_text
                )
                return self._emit_error(
                    silent=silent,
                    ename=ename,
                    evalue=evalue,
                    traceback_lines=tb_lines,
                )

            combined_out = stdout_text
            if stderr_text:
                combined_out = (
                    f"{stdout_text}\n[stderr]\n{stderr_text}"
                    if stdout_text
                    else f"[stderr]\n{stderr_text}"
                )
            if combined_out and not silent:
                self._send_stdout(self._truncate(combined_out))

            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

    def _send_stdout(self, text: str) -> None:
        self.send_response(
            self.iopub_socket,
            "stream",
            {"name": "stdout", "text": text},
        )

    def _emit_error(
        self,
        *,
        silent: bool,
        ename: str,
        evalue: str,
        traceback_lines: list[str],
    ) -> dict[str, Any]:
        if not silent:
            self.send_response(
                self.iopub_socket,
                "error",
                {
                    "ename": ename,
                    "evalue": evalue,
                    "traceback": traceback_lines,
                },
            )
        return {
            "status": "error",
            "ename": ename,
            "evalue": evalue,
            "traceback": traceback_lines,
            "execution_count": self.execution_count,
        }

    @staticmethod
    def _format_runtime_failure(
        returncode: int, stderr_text: str
    ) -> tuple[str, str, list[str]]:
        if returncode < 0:
            sig_num = -returncode
            sig_desc = _SIGNAL_NAMES.get(sig_num, f"Signal {sig_num}")
            ename = "RuntimeSignalError"
            evalue = f"程序异常终止：{sig_desc}"
        else:
            ename = f"ExitCode{returncode}"
            first_line = next(
                (line.strip() for line in stderr_text.splitlines() if line.strip()),
                "",
            )
            evalue = (
                f"程序返回非零退出码 {returncode}：{first_line}"
                if first_line
                else f"程序返回非零退出码 {returncode}"
            )

        tb_lines = [evalue]
        if stderr_text.strip():
            tb_lines.extend(stderr_text.strip().splitlines())
        return ename, evalue[:300], tb_lines

    @staticmethod
    def _decode_timeout_stream(raw: bytes | str | None) -> str:
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= MAX_OUTPUT_CHARS:
            return text
        return f"{text[:MAX_OUTPUT_CHARS]}\n... [输出已截断，超过 {MAX_OUTPUT_CHARS} 字符] ...\n"


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp

    IPKernelApp.launch_instance(kernel_class=CppCompileKernel)
