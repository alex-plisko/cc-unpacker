"""Tests for source map extraction logic."""

import json
import base64
import tempfile
from pathlib import Path

import pytest

from cc_unpacker.extractor import (
    extract_sources_from_map,
    extract_inline_sourcemap,
    extract_all_sources,
    SourceFile,
)


def _write_map(path: Path, data: dict) -> Path:
    map_path = path / "bundle.js.map"
    map_path.write_text(json.dumps(data))
    return map_path


class TestExtractSourcesFromMap:
    def test_extracts_sources_content(self, tmp_path):
        data = {
            "version": 3,
            "sources": ["src/foo.ts", "src/bar.ts"],
            "sourcesContent": ["const x = 1;", "const y = 2;"],
            "mappings": "",
        }
        map_path = _write_map(tmp_path, data)
        result = extract_sources_from_map(map_path)
        assert len(result) == 2
        assert result[0].name == "src/foo.ts"
        assert result[0].content == "const x = 1;"
        assert result[1].name == "src/bar.ts"

    def test_skips_null_content(self, tmp_path):
        data = {
            "version": 3,
            "sources": ["src/a.ts", "src/b.ts"],
            "sourcesContent": ["export default 1;", None],
            "mappings": "",
        }
        map_path = _write_map(tmp_path, data)
        result = extract_sources_from_map(map_path)
        assert len(result) == 1
        assert result[0].name == "src/a.ts"

    def test_cleans_webpack_prefix(self, tmp_path):
        data = {
            "version": 3,
            "sources": ["webpack:///./src/utils.ts"],
            "sourcesContent": ["export const noop = () => {};"],
            "mappings": "",
        }
        map_path = _write_map(tmp_path, data)
        result = extract_sources_from_map(map_path)
        assert result[0].name == "src/utils.ts"

    def test_handles_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.js.map"
        bad.write_text("NOT JSON {{{")
        result = extract_sources_from_map(bad)
        assert result == []

    def test_empty_sources(self, tmp_path):
        data = {"version": 3, "sources": [], "mappings": ""}
        map_path = _write_map(tmp_path, data)
        result = extract_sources_from_map(map_path)
        assert result == []


class TestExtractInlineSourcemap:
    def _make_js_with_inline_map(self, tmp_path: Path, source_name: str, content: str) -> Path:
        map_data = {
            "version": 3,
            "sources": [source_name],
            "sourcesContent": [content],
            "mappings": "",
        }
        encoded = base64.b64encode(json.dumps(map_data).encode()).decode()
        js = tmp_path / "bundle.js"
        js.write_text(f"var x=1;\n//# sourceMappingURL=data:application/json;base64,{encoded}\n")
        return js

    def test_extracts_inline_map(self, tmp_path):
        js = self._make_js_with_inline_map(tmp_path, "src/inline.ts", "const inline = true;")
        result = extract_inline_sourcemap(js)
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "src/inline.ts"
        assert result[0].content == "const inline = true;"

    def test_returns_none_if_no_inline_map(self, tmp_path):
        js = tmp_path / "plain.js"
        js.write_text("console.log('hello');")
        result = extract_inline_sourcemap(js)
        assert result is None


class TestExtractAllSources:
    def test_finds_external_map_files(self, tmp_path):
        data = {
            "version": 3,
            "sources": ["src/main.ts"],
            "sourcesContent": ["export {}"],
            "mappings": "",
        }
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "main.js.map").write_text(json.dumps(data))
        result = extract_all_sources(tmp_path)
        assert "src/main.ts" in result

    def test_deduplicates_across_maps(self, tmp_path):
        data = {
            "version": 3,
            "sources": ["src/shared.ts"],
            "sourcesContent": ["const shared = 1;"],
            "mappings": "",
        }
        (tmp_path / "a.js.map").write_text(json.dumps(data))
        (tmp_path / "b.js.map").write_text(json.dumps(data))
        result = extract_all_sources(tmp_path)
        assert len(result) == 1  # deduped


class TestDB:
    def test_save_and_retrieve(self, tmp_path, monkeypatch):
        import cc_unpacker.db as db_module
        test_db = tmp_path / "test.db"
        monkeypatch.setattr(db_module, "DB_PATH", test_db)
        monkeypatch.setattr(db_module, "DB_DIR", tmp_path)

        rid = db_module.save_analysis("test-pkg", "1.0.0", 5, "Summary here", "Full report")
        assert rid == 1

        rows = db_module.list_analyses()
        assert len(rows) == 1
        assert rows[0]["package_name"] == "test-pkg"

        row = db_module.get_analysis(1)
        assert row is not None
        assert row["full_report"] == "Full report"

    def test_get_nonexistent(self, tmp_path, monkeypatch):
        import cc_unpacker.db as db_module
        test_db = tmp_path / "test2.db"
        monkeypatch.setattr(db_module, "DB_PATH", test_db)
        monkeypatch.setattr(db_module, "DB_DIR", tmp_path)

        result = db_module.get_analysis(999)
        assert result is None
