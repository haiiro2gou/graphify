"""Tests for deterministic Minecraft resource-pack extraction."""
import json
from pathlib import Path

import pytest

from graphify.extractors.base import _make_id
from graphify.extractors.resourcepack import (
    _resource_id, extract_resourcepack, is_resourcepack_path,
)


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_model_parent_textures_and_dedup(tmp_path: Path):
    path = _write(tmp_path, "assets/demo/models/item/stick.json", json.dumps({
        "parent": "item/generated",
        "textures": {"a": "demo:item/stick", "b": "#a", "c": "demo:item/stick"},
    }))
    result = extract_resourcepack(path)
    assert result["nodes"][0] == {
        "id": _resource_id("rp_model", "demo:item/stick"), "label": "demo:item/stick",
        "type": "namespace", "file_type": "code",
        "source_file": str(path), "source_location": "L1",
    }
    assert result["edges"] == [{
        "source": result["nodes"][0]["id"], "target": _resource_id(kind, name),
        "relation": "references", "confidence": "EXTRACTED", "weight": 1.0,
        "source_file": str(path), "source_location": "L1", "context": context,
    } for kind, name, context in [
        ("rp_model", "minecraft:item/generated", "parent"),
        ("rp_texture", "demo:item/stick", "texture"),
    ]]
    assert len(result["nodes"]) == 3
    assert all(n["type"] == "namespace" for n in result["nodes"])
    assert extract_resourcepack(path) == result


def test_item_overrides(tmp_path: Path):
    path = _write(tmp_path, "assets/demo/models/item/nested/stick.json", json.dumps({
        "overrides": [
            {"predicate": {"custom_model_data": 20113}, "model": "demo:blaster"},
            {"predicate": {"custom_model_data": True}, "model": "demo:ignored"},
            {"predicate": {"custom_model_data": 1.5}, "model": "demo:ignored"},
        ],
    }))
    result = extract_resourcepack(path)
    cmd = _resource_id("rp_cmd", "minecraft:stick#20113")
    assert [(e["source"], e["target"], e["context"]) for e in result["edges"]] == [
        (result["nodes"][0]["id"], cmd, "override"),
        (cmd, _resource_id("rp_model", "demo:blaster"), "custom_model_data"),
    ]
    assert result["nodes"][1]["label"] == "minecraft:stick#20113"


def test_sounds(tmp_path: Path):
    path = _write(tmp_path, "assets/demo/sounds.json", json.dumps({
        "blaster": {"sounds": ["demo:blast", {"name": "bare"},
                                {"name": "demo:other", "type": "event"}]},
        "other": {"sounds": []},
    }))
    result = extract_resourcepack(path)
    assert result["nodes"][0]["id"] == _make_id(str(path))
    assert result["nodes"][0]["label"] == "demo:sounds.json"
    assert [(e["target"], e["context"]) for e in result["edges"]] == [
        (_resource_id("rp_sound", "demo:blaster"), "defines"),
        (_resource_id("rp_sound_file", "demo:blast"), "sound"),
        (_resource_id("rp_sound_file", "minecraft:bare"), "sound"),
        (_resource_id("rp_sound", "demo:other"), "sound"),
        (_resource_id("rp_sound", "demo:other"), "defines"),
    ]


def test_font(tmp_path: Path):
    path = _write(tmp_path, "assets/demo/font/ui/main.json", json.dumps({
        "providers": [{"type": "bitmap", "file": "demo:font/glyphs.png"},
                      {"type": "reference", "id": "default"}],
    }))
    result = extract_resourcepack(path)
    assert result["nodes"][0]["id"] == _resource_id("rp_font", "demo:ui/main")
    assert [e["target"] for e in result["edges"]] == [
        _resource_id("rp_texture", "demo:font/glyphs"),
        _resource_id("rp_font", "minecraft:default"),
    ]
    assert all(e["context"] == "font" for e in result["edges"])


@pytest.mark.parametrize("relative", [
    "models/a.json", "data/demo/models/a.json", "assets/demo/blockstates/a.json",
    "assets/demo/models/a.png", "assets/demo/nested/sounds.json",
    "assets/outer/models/assets/nope.json",
])
def test_non_resource_paths(relative: str):
    assert not is_resourcepack_path(Path(relative))


def test_last_assets_and_dispatch(tmp_path: Path):
    from graphify.detect import FileType, classify_file
    from graphify.extract import _get_extractor

    for relative in ["assets/outer/models/assets/demo/models/a.json",
                     "assets/demo/sounds.json", "assets/demo/font/a.json"]:
        path = _write(tmp_path, relative, "{}")
        assert is_resourcepack_path(path)
        assert classify_file(path) == FileType.CODE
        assert _get_extractor(path) is extract_resourcepack
    assert extract_resourcepack(tmp_path / "assets/outer/models/assets/demo/models/a.json")["nodes"][0]["label"] == "demo:a"


@pytest.mark.parametrize(("relative", "text"), [
    ("models/a.json", "{bad"),
    ("models/a.json", "[]"),
    ("models/a.json", '{"parent":"item/generated","textures":[]}'),
    ("models/a.json", '{"textures":{"a":42}}'),
    ("models/item/a.json", '{"overrides":[{"predicate":[]}]}'),
    ("sounds.json", '{"a":{"sounds":["ok",{}]}}'),
    ("sounds.json", '{"a":{"sounds":{}}}'),
    ("font/a.json", '{"providers":[{"file":"ok.png"},{"type":"reference","id":2}]}'),
    ("font/a.json", '{"providers":{}}'),
])
def test_invalid_document_preserves_only_file_node(tmp_path: Path, relative: str, text: str):
    path = _write(tmp_path, "assets/demo/" + relative, text)
    result = extract_resourcepack(path)
    assert result["error"]
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["type"] == "namespace"
    assert result["edges"] == []


def test_non_item_overrides_ignored(tmp_path: Path):
    path = _write(tmp_path, "assets/demo/models/block/a.json", json.dumps({
        "textures": {"a": "#variable"},
        "overrides": [{"predicate": {"custom_model_data": 1}, "model": "demo:a"}],
    }))
    assert extract_resourcepack(path)["edges"] == []


def test_read_error(tmp_path: Path):
    result = extract_resourcepack(tmp_path / "assets/demo/font/missing.json")
    assert result["error"]
    assert len(result["nodes"]) == 1
    assert result["edges"] == []
