#!/usr/bin/env bash
# 此脚本用于包装 skill_gen_cli.py，自动处理环境依赖与执行。
# Agent 只需要原封不动地调用：./scripts/gen.sh --input xxx --output yyy 即可。

set -e

# 获取当前脚本所在目录以及项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SKILL_GEN_DIR="$SCRIPT_DIR/skill-gen"
VENV_DIR="$SKILL_GEN_DIR/.venv"

# 1. 检查有没有安装 uv
if ! command -v uv &> /dev/null; then
    echo "⚠️ 错误: 未找到 'uv' 命令。"
    echo "Skill Generator 需要 'uv' 作为高性能的 Python 环境管理器。"
    echo "请执行以下命令进行安装："
    echo "curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "安装完成后，请打开一个新终端重试。"
    exit 1
fi

# 2. 自动配置虚拟环境并安装依赖
# 我们使用虚拟环境是为了保持宿主系统干净，不污染全局 Python 环境。
cd "$SKILL_GEN_DIR"
if [ ! -d "$VENV_DIR" ]; then
    echo "⏳ 正在初始化隔离的 Python 虚拟环境 (.venv)..."
    uv venv "$VENV_DIR"
    echo "⏳ 正在安装底层依赖项..."
    # 强制静默或者显示进度安装依赖
    uv pip install -r requirements.txt
    echo "✅ 环境依赖准备完毕！"
else
    # 也可以轻量级地 verify 一下，uv pip install 会立刻返回如果已经满足
    uv pip install -r requirements.txt > /dev/null 2>&1 || {
        echo "⏳ 正在更新底层依赖项..."
        uv pip install -r requirements.txt
    }
fi

# 3. 运行主程序并透传所有参数
echo "🚀 正在启动 Skill Generator..."
# 使用 uv run 确保使用的是刚才创建或检查的虚拟环境
uv run skill_gen_cli.py "$@"
