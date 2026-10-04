"""Deterministic Minecraft resource-pack extraction using stdlib JSON."""
from __future__ import annotations

import json
from pathlib import Path

from graphify.extractors.base import _make_id
# mcfunction emits edges to these IDs, so both sides must share one ID scheme.
from graphify.extractors.mcfunction import _resource_id


def _resource_path(path: Path) -> tuple[str, str] | None:
    """Classify only the layout beneath the last assets component."""
    parts = path.parts
    if "assets" not in parts or path.suffix != ".json":
        return None
    assets_index = len(parts) - 1 - parts[::-1].index("assets")
    tail = parts[assets_index + 1:]
    if len(tail) == 2 and tail[1] == "sounds.json":
        return "sounds", f"{tail[0]}:sounds.json"
    if len(tail) >= 3 and tail[1] in {"models", "font"}:
        return tail[1], f"{tail[0]}:{'/'.join(tail[2:])[:-5]}"
    return None


def is_resourcepack_path(path: Path) -> bool:
    """Return whether path is a model, sound definition, or font JSON file."""
    return _resource_path(path) is not None


def extract_resourcepack(path: Path) -> dict:
    """Extract shared resource nodes and deduplicated references from one file.

    All nodes are namespace anchors so the builder can merge references across
    files. Invalid documents retain only their own file node and an error.
    """
    str_path = str(path)
    resource = _resource_path(path)
    kind, name = resource if resource else ("", path.name)
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(nid: str, label: str) -> None:
        if nid not in seen_ids:
            seen_ids.add(nid)
            nodes.append({
                "id": nid, "label": label, "type": "namespace", "file_type": "code",
                "source_file": str_path, "source_location": "L1",
            })

    def add_edge(source: str, target_kind: str, reference: str, context: str) -> str:
        reference = reference if ":" in reference else f"minecraft:{reference}"
        target = _resource_id(target_kind, reference)
        add_node(target, reference)
        key = (source, target, "references")
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({
                "source": source, "target": target, "relation": "references",
                "confidence": "EXTRACTED", "source_file": str_path,
                "source_location": "L1", "weight": 1.0, "context": context,
            })
        return target

    file_nid = (_resource_id("rp_model" if kind == "models" else "rp_font", name)
                if kind in {"models", "font"} else _make_id(str_path))
    add_node(file_nid, name)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if resource is None:
            return {"nodes": nodes, "edges": edges}
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError("Resource pack document must be a JSON object")
        if kind == "models":
            if "parent" in document:
                if not isinstance(document["parent"], str):
                    raise ValueError("Model parent must be a string")
                add_edge(file_nid, "rp_model", document["parent"], "parent")
            textures = document.get("textures", {})
            if not isinstance(textures, dict):
                raise ValueError("Model textures must be an object")
            for texture in textures.values():
                if not isinstance(texture, str):
                    raise ValueError("Model texture must be a string")
                if not texture.startswith("#"):
                    add_edge(file_nid, "rp_texture", texture, "texture")
            if name.split(":", 1)[1].startswith("item/"):
                overrides = document.get("overrides", [])
                if not isinstance(overrides, list):
                    raise ValueError("Model overrides must be a list")
                for override in overrides:
                    if not isinstance(override, dict):
                        raise ValueError("Model override must be an object")
                    predicate = override.get("predicate", {})
                    if not isinstance(predicate, dict):
                        raise ValueError("Override predicate must be an object")
                    number = predicate.get("custom_model_data")
                    model = override.get("model")
                    if type(number) is int and isinstance(model, str):
                        cmd = add_edge(file_nid, "rp_cmd", f"minecraft:{path.stem}#{number}", "override")
                        add_edge(cmd, "rp_model", model, "custom_model_data")
        elif kind == "sounds":
            namespace = name.split(":", 1)[0]
            for event, definition in document.items():
                if not isinstance(definition, dict):
                    raise ValueError("Sound definition must be an object")
                sound = add_edge(file_nid, "rp_sound", f"{namespace}:{event}", "defines")
                sounds = definition.get("sounds", [])
                if not isinstance(sounds, list):
                    raise ValueError("Sounds must be a list")
                for entry in sounds:
                    reference = entry.get("name") if isinstance(entry, dict) else entry
                    sound_type = entry.get("type", "file") if isinstance(entry, dict) else "file"
                    if not isinstance(reference, str) or not isinstance(sound_type, str):
                        raise ValueError("Sound name and type must be strings")
                    add_edge(sound, "rp_sound" if sound_type == "event" else "rp_sound_file", reference, "sound")
        else:
            providers = document.get("providers", [])
            if not isinstance(providers, list):
                raise ValueError("Font providers must be a list")
            for provider in providers:
                if not isinstance(provider, dict):
                    raise ValueError("Font provider must be an object")
                if "file" in provider:
                    if not isinstance(provider["file"], str):
                        raise ValueError("Font file must be a string")
                    add_edge(file_nid, "rp_texture", provider["file"].removesuffix(".png"), "font")
                if provider.get("type") == "reference":
                    if not isinstance(provider.get("id"), str):
                        raise ValueError("Font reference id must be a string")
                    add_edge(file_nid, "rp_font", provider["id"], "font")
    except (OSError, ValueError) as error:
        return {"nodes": nodes[:1], "edges": [], "error": str(error)}
    return {"nodes": nodes, "edges": edges}
