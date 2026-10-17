"""支持通过 `python -m micro` 启动 micro。"""

from cli import app

# 将模块执行转交给 Typer 命令行应用。
app()
