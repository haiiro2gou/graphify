"""Tests for deterministic Minecraft datapack extraction."""
from pathlib import Path
import json

import pytest

from graphify.extractors.base import _make_id
from graphify.extractors.mcfunction import extract_mcfunction, is_function_tag_path


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("directory", ["function", "functions"])
def test_function_node_and_cross_file_calls(tmp_path: Path, directory: str):
    caller = _write(tmp_path, f"data/demo/{directory}/nested/start.mcfunction",
                    "function demo:finish\n")
    target = _write(tmp_path, f"data/demo/{directory}/finish.mcfunction", "")
    result = extract_mcfunction(caller)
    assert result["nodes"] == [{
        "id": _make_id("mcfunction", "demo:nested/start"),
        "label": "demo:nested/start", "file_type": "code",
        "source_file": str(caller), "source_location": "L1",
    }]
    assert result["edges"] == [{
        "source": result["nodes"][0]["id"],
        "target": extract_mcfunction(target)["nodes"][0]["id"],
        "relation": "calls", "confidence": "EXTRACTED",
        "source_file": str(caller), "source_location": "L1",
        "weight": 1.0, "context": "call",
    }]


@pytest.mark.parametrize(("command", "reference", "context"), [
    ("function a:direct", "a:direct", "call"),
    ("execute as @s run function a:nested", "a:nested", "call"),
    ("execute if function a:condition run say yes", "a:condition", "call"),
    ("return run function a:return", "a:return", "call"),
    ("function a:storage with storage x:y z", "a:storage", "call"),
    ("function a:args {k:1}", "a:args", "call"),
    ("function bare/path", "minecraft:bare/path", "call"),
    ("$function a:macro {k:$(value)}", "a:macro", "call"),
    ("schedule function a:later 1t", "a:later", "schedule"),
    ("schedule function a:later 2s append", "a:later", "schedule"),
    ("execute as @s run schedule function a:later 3d replace", "a:later", "schedule"),
])
def test_call_forms(tmp_path: Path, command: str, reference: str, context: str):
    path = _write(tmp_path, "data/demo/function/start.mcfunction", "\n  " + command)
    result = extract_mcfunction(path)
    assert "error" not in result
    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert edge["target"] == _make_id("mcfunction", reference)
    assert edge["source_location"] == "L2"
    assert edge["context"] == context


def test_skips_comments_dynamic_references_self_calls_and_duplicates(tmp_path: Path):
    path = _write(tmp_path, "data/demo/function/start.mcfunction", "\n".join([
        "  # function a:comment", "schedule clear a:cleared",
        "function $(namespace):dynamic", "$function a:$(path)",
        "schedule function a:prefix$(suffix) 1t", "function demo:start",
        "schedule function a:once 1t", "function a:once",
        "function a:once", "notfunction a:wrong",
        "execute if function a:condition run function a:body",
    ]))
    result = extract_mcfunction(path)
    assert len(result["nodes"]) == 1
    assert [(e["target"], e["context"], e["source_location"]) for e in result["edges"]] == [
        (_make_id("mcfunction", "a:once"), "schedule", "L7"),
        (_make_id("mcfunction", "a:condition"), "call", "L11"),
        (_make_id("mcfunction", "a:body"), "call", "L11"),
    ]
    assert extract_mcfunction(path) == result


@pytest.mark.parametrize("directory", ["function", "functions"])
def test_function_tags(tmp_path: Path, directory: str):
    tag = _write(tmp_path, f"data/demo/tags/{directory}/nested/tick.json", json.dumps({
        "values": ["demo:start", {"id": "bare", "required": False},
                   "#demo:other", {"id": "#default", "required": True},
                   "demo:start", "#demo:nested/tick", "a:$(dynamic)",
                   {}, 42, None],
    }))
    assert is_function_tag_path(tag)
    result = extract_mcfunction(tag)
    assert "error" not in result
    assert result["nodes"] == [{
        "id": _make_id("mcfunction_tag", "demo:nested/tick"),
        "label": "#demo:nested/tick", "file_type": "code",
        "source_file": str(tag), "source_location": "L1",
    }]
    assert [e["target"] for e in result["edges"]] == [
        _make_id("mcfunction", "demo:start"), _make_id("mcfunction", "minecraft:bare"),
        _make_id("mcfunction_tag", "demo:other"),
        _make_id("mcfunction_tag", "minecraft:default"),
    ]
    assert all(e["context"] == "tag" and e["relation"] == "calls"
               and e["source_location"] == "L1" for e in result["edges"])
    caller = _write(tmp_path, "data/demo/function/start.mcfunction",
                    "function #demo:nested/tick\nschedule function #default 1t")
    edges = extract_mcfunction(caller)["edges"]
    assert edges[0]["target"] == result["nodes"][0]["id"]
    assert edges[1]["target"] == _make_id("mcfunction_tag", "minecraft:default")
    assert edges[1]["context"] == "schedule"


@pytest.mark.parametrize("relative", [
    "data/demo/function/tick.json", "data/demo/tags/advancements/tick.json",
    "data/demo/tags/functions/tick.mcfunction", "demo/tags/function/tick.json",
    "data/demo/other/tags/function/tick.json", "data/demo/tags/function.json",
    "data/demo/tags/functions/tick.json.bak",
])
def test_non_tag_layouts(relative: str):
    assert not is_function_tag_path(Path(relative))


@pytest.mark.parametrize(("relative", "label"), [
    ("data/outer/function/data/inner/functions/deep/start.mcfunction", "inner:deep/start"),
    ("data/outer/function/deep/data/start.mcfunction", "outer:deep/data/start"),
    ("data/outer/tags/function/data/inner/tags/functions/tick.json", "#inner:tick"),
])
def test_last_matching_data_directory(tmp_path: Path, relative: str, label: str):
    path = _write(tmp_path, relative, "{}" if relative.endswith(".json") else "")
    assert extract_mcfunction(path)["nodes"][0]["label"] == label


def test_unresolved_layout(tmp_path: Path):
    path = _write(tmp_path, "loose.mcfunction", "function demo:target")
    result = extract_mcfunction(path)
    assert result == {"nodes": [{
        "id": _make_id(str(path)), "label": path.name, "file_type": "code",
        "source_file": str(path), "source_location": "L1",
    }], "edges": []}


@pytest.mark.parametrize("text", ["{invalid", "[]", '{"values": {}}'])
def test_invalid_tag_preserves_node(tmp_path: Path, text: str):
    path = _write(tmp_path, "data/demo/tags/function/tick.json", text)
    result = extract_mcfunction(path)
    assert result["error"]
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == _make_id("mcfunction_tag", "demo:tick")
    assert result["edges"] == []


def test_read_error_and_utf8_replacement(tmp_path: Path):
    path = tmp_path / "data/demo/function/start.mcfunction"
    result = extract_mcfunction(path)
    assert result["error"]
    assert len(result["nodes"]) == 1
    assert result["edges"] == []
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# invalid \xff\nfunction demo:target\n")
    result = extract_mcfunction(path)
    assert "error" not in result
    assert result["edges"][0]["target"] == _make_id("mcfunction", "demo:target")


def test_dispatch_routes_functions_and_tags(tmp_path: Path):
    from graphify.detect import FileType, classify_file
    from graphify.extract import _get_extractor

    function = _write(tmp_path, "data/ns/function/a.mcfunction", "say hi\n")
    tag = _write(tmp_path, "data/ns/tags/function/load.json", '{"values": []}')
    assert classify_file(function) == FileType.CODE
    assert _get_extractor(function) is extract_mcfunction
    assert _get_extractor(tag) is extract_mcfunction
