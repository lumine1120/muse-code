from pathlib import Path


def get_memory_dir() -> Path:
    path = Path.cwd() / ".muse_memory"
    path.mkdir(exist_ok=True, parents=True)
    return path


def build_memory_prompt_section() -> str:
    """构建 memory 相关的 prompt 片段，注入到系统提示中。"""
    # TODO: 读取 .muse_memory/ 下的记忆文件，拼接为 prompt
    return ""
