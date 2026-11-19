# jupyter-cpp20-compile-kernel

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

一个面向高校 C++ 实验教学的**整格编译型 Jupyter 内核**（基于 `g++ -std=c++20 -O0`），在 [shiroinekotfs/jupyter-cpp-kernel](https://github.com/shiroinekotfs/jupyter-cpp-kernel) 与 [brendan-rius/jupyter-c-kernel](https://github.com/brendan-rius/jupyter-c-kernel) 的思路基础上进行了教学与监控场景增强。

## 为什么需要它？

传统的交互式 C++ 内核（如 `xeus-cling` / `xeus-cpp`）采用全局作用域 REPL 解释执行：
- 学生无法按教材习惯编写标准的 `int main()`；
- 同一单元格内修改函数或变量后反复运行，极易触发 **Redefinition（重定义）** 报错，必须频繁重启内核。

**`jupyter-cpp20-compile-kernel`** 将每个代码单元格作为独立的 C++20 翻译单元进行编译执行，兼具 JupyterLab 在线实验的便利性与本地 IDE（如 VS Code / Dev-C++）一致的编程体验。

## 核心特性

1. **标准 `int main()` 编译运行，零重定义残留**：每次运行自动在隔离临时目录中调用 `g++ -std=c++20 -O0 -Wall -Wextra` 编译并运行，反复修改调试无需重启内核。
2. **标准 Jupyter 错误状态回报**：编译失败、运行超时或异常退出（`SIGSEGV`、`SIGABRT` 等）时，严格发送 Jupyter `error` 消息并返回 `status: "error"`（修复了原版 `jupyter-cpp-kernel` 编译报错仍返回 `status: "ok"` 的问题），可无缝对接教学行为监控与自动评测系统。
3. **报错位置源码行号对照**：编译错误时自动提取出错行前后上下文并用 `>>` 高亮标注具体行号，同时提供一键为 JupyterLab 所有单元格默认开启左侧行号（`lineNumbers: true`）的安装选项。
4. **标准输入**：可在代码顶部用 `// @input: ...` 或 `/* @input: ... */` 预置测试数据。交互运行时，程序需要更多输入才会显示输入框，并把它刚才输出的最后一行用作提示。
5. **非侵入式并存安装**：默认以独立 kernelspec `cpp20_gpp`（显示名 `C++20 (g++ 整格编译)`）安装，不删除、不覆盖镜像中原有的 `xcpp20` 或 `python3` 内核。

## 快速安装

### 前置依赖
- `g++`（支持 C++20）
- Python >= 3.9，以及 `ipykernel` / `jupyterlab`

### 本地安装

```bash
git clone https://github.com/XuYuanDaWang/jupyter-cpp20-compile-kernel.git
cd jupyter-cpp20-compile-kernel

pip install .
jupyter-cpp20-install
```

常用安装选项：
- `--jupyter-share-dir <path>`：指定目标环境的 `<prefix>/share/jupyter` 目录
- `--kernel-name <name>`：自定义 kernelspec 名称（默认 `cpp20_gpp`）
- `--no-line-numbers`：跳过自动开启 JupyterLab 单元格行号配置

### Docker 镜像增量叠加

在现有 JupyterLab 工作台镜像基础上无损叠加本内核（保留原有全部内核）：

```bash
docker build --platform linux/amd64 \
  -f docker/Dockerfile.overlay \
  --build-arg BASE_IMAGE=<your-base-jupyter-image> \
  -t jupyterlab-cpp20-gpp:latest .
```

## 使用示例

可打开 [`examples/cpp20_compile_demo.ipynb`](examples/cpp20_compile_demo.ipynb) 直接体验：

```cpp
// @input: 5
// @input: 10 20 30 40 50
#include <iostream>
#include <vector>
using namespace std;

int main() {
    int n;
    if (!(cin >> n)) return 0;
    vector<int> nums(n);
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        cin >> nums[i];
        sum += nums[i];
    }
    cout << "元素个数: " << n << ", 总和: " << sum << endl;
    return 0;
}
```

## 运行测试

```bash
python -m unittest discover -s tests -v
```

## 致谢与开源协议

本项目基于 MIT 协议开源，设计灵感与基础架构参考了：
- [shiroinekotfs/jupyter-cpp-kernel](https://github.com/shiroinekotfs/jupyter-cpp-kernel)（MIT License）
- [brendan-rius/jupyter-c-kernel](https://github.com/brendan-rius/jupyter-c-kernel)（MIT License）
