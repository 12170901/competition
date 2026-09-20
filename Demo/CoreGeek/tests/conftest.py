"""pytest 共享夹具。

职责:
1. 把 Demo/CoreGeek/src 注入 sys.path,让测试可以 `from agent import ...`;
2. 每用例重置 tasks.MEMORY 全局状态,避免跨用例污染;
3. 以 docs/request.txt 为基底,提供可按场景覆写的 payload 构造器。

约定:一切以 docs/任务书.md、docs/接口文档.md 为准;
payload 字段名必须与 docs/request.txt 完全一致。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent import tasks as tasks_mod  # noqa: E402

DOCS_REQUEST = ROOT.parent.parent / "docs" / "request.txt"


@pytest.fixture(autouse=True)
def _reset_memory():
    """decide 依赖进程级 MEMORY,每个用例前重置,模拟冷启动。"""
    tasks_mod.MEMORY = tasks_mod.Memory()
    yield
    tasks_mod.MEMORY = tasks_mod.Memory()


@pytest.fixture(scope="session")
def base_payload() -> dict[str, Any]:
    """加载 docs/request.txt 作为标准基底 payload(合法 JSON)。"""
    if not DOCS_REQUEST.exists():
        pytest.skip(f"缺少基准请求文件: {DOCS_REQUEST}")
    text = DOCS_REQUEST.read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture
def make_payload(base_payload):
    """场景构造器:在基底上覆写个别字段,返回新 payload(不改动基底)。

    用法: make_payload(roundNo=5) -> dict
    支持顶层 key 覆写;未识别的 key 会抛错,防止拼错字段名。
    """

    def _make(**overrides: Any) -> dict[str, Any]:
        payload = copy.deepcopy(base_payload)
        for key, value in overrides.items():
            if key not in payload:
                raise KeyError(f"payload 中不存在的顶层字段: {key}")
            payload[key] = value
        return payload

    return _make
