import io
import asyncio

import pytest
from docx import Document

from backend.schemas import ApiConfig, WebSearchConfig
from backend.services.document_parser import parse_document
from backend.services.llm import _build_model
from backend.services.web_search import WebSearchNotConfiguredError, build_search_context, tavily_search


def make_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def test_parse_txt_document():
    assert parse_document("招标.txt", "项目名称：测试项目".encode("utf-8")) == "项目名称：测试项目"


def test_parse_docx_document():
    parsed = parse_document("招标.docx", make_docx_bytes("项目名称：DOCX 项目"))
    assert "DOCX 项目" in parsed


def test_empty_file_error():
    with pytest.raises(ValueError, match="文件为空"):
        parse_document("empty.txt", b"")


def test_unsupported_file_error():
    with pytest.raises(ValueError, match="仅支持"):
        parse_document("old.doc", b"abc")


def test_openai_compatible_agent_accepts_base_url():
    model = _build_model(
        ApiConfig(
            provider="DeepSeek",
            base_url="https://api.deepseek.com",
            api_key="test-key",
            model="deepseek-chat",
        )
    )
    assert model is not None
    assert model.model_name == "deepseek-chat"


def test_tavily_search_requires_api_key(monkeypatch):
    monkeypatch.setattr("backend.services.web_search.workbench_store.resolve_tavily_api_key", lambda user_id: None)
    monkeypatch.setattr("backend.services.web_search.workbench_store.get_web_search_config", lambda user_id: WebSearchConfig())

    with pytest.raises(WebSearchNotConfiguredError, match="TAVILY_API_KEY"):
        asyncio.run(tavily_search("test-user", "AI workbench"))


def test_tavily_search_calls_api_and_builds_context(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "Result A", "url": "https://example.com/a", "content": "A summary"},
                    {"title": "Result B", "url": "https://example.com/b", "content": "B summary"},
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 20

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("backend.services.web_search.workbench_store.resolve_tavily_api_key", lambda user_id: "test-key")
    monkeypatch.setattr(
        "backend.services.web_search.workbench_store.get_web_search_config",
        lambda user_id: WebSearchConfig(has_key=True, source="db", max_results=2, search_depth="basic"),
    )
    monkeypatch.setattr("backend.services.web_search.httpx.AsyncClient", FakeClient)

    results = asyncio.run(tavily_search("test-user", "AI workbench"))
    context = build_search_context(results)

    assert captured["endpoint"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["query"] == "AI workbench"
    assert captured["json"]["max_results"] == 2
    assert results[0].title == "Result A"
    assert "[1] Result A" in context
    assert "https://example.com/b" in context
