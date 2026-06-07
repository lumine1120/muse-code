# Muse Code

一个轻量级 CLI Agent 框架，灵感来自 Claude Code Lite。

## 环境准备

需要安装 [uv](https://github.com/astral-sh/uv)。

## 启动方式

### 1. 配置环境变量（可选，按需设置 OpenAI 兼容接口）

```bash
export MUSE_BACKEND="openai" # 默认使用 openai 即 OpenAI Compatible 模式
export OPENAI_API_KEY="sk-da55231cfba049438b776410797e5032"
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_MODEL="deepseek-v4-flash"

# 或者若想使用 Anthropic 原生支持：
# export MUSE_BACKEND="anthropic"
# export ANTHROPIC_API_KEY="sk-ant-..."
```

### 2. 开发模式（需在项目目录下执行，始终使用最新代码）

```bash
uv run python -m muse_code
# 或者使用 entry point
uv run muse
```

### 3. 全局安装（任意目录一键启动）

```bash
uv tool install .
uv tool update-shell
```

安装完成后，在任意目录输入 `muse` 即可直接启动。

> **注意：** `uv tool install` 会将当前代码打包成一份快照安装到全局。代码更新后需要执行 `uv tool install --reinstall .` 来刷新。日常开发建议使用 `uv run muse`，无需重新安装即可始终运行最新代码。
