"""Minecraft datapack function and function-tag extractor (regex and stdlib JSON)."""
from __future__ import annotations

import json
import re

from pathlib import Path
from graphify.extractors.base import _make_id


_CALL_RE = re.compile(r"(?<!\S)(?:(?P<schedule>schedule)\s+)?function\s+(?P<ref>\S+)")
_RESOURCE_RE = re.compile(r"(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+")


def _resource_name(path: Path, tag: bool = False) -> str | None:
    """Resolve a resource from the last matching datapack data directory."""
    parts = path.parts
    suffix = ".json" if tag else ".mcfunction"
    if path.suffix != suffix:
        return None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] != "data":
            continue
        tail = parts[i + 1:]
        directory = 2 if tag else 1
        if len(tail) < directory + 2:
            continue
        if tag and tail[1] != "tags":
            continue
        if tail[directory] not in {"function", "functions"}:
            continue
        relative = "/".join(tail[directory + 1:])[:-len(suffix)]
        if relative:
            return f"{tail[0]}:{relative}"
    return None


def is_function_tag_path(path: Path) -> bool:
    """Return whether path has a datapack function-tag JSON layout."""
    return _resource_name(path, tag=True) is not None


def _reference_id(reference: str) -> str | None:
    """Resolve a static function or tag reference, defaulting to minecraft."""
    tag = reference.startswith("#")
    name = reference[1:] if tag else reference
    if "$(" in name or not _RESOURCE_RE.fullmatch(name):
        return None
    if ":" not in name:
        name = f"minecraft:{name}"
    # ponytail: ID-normalization ceiling: a:b_c and a:b/c collide via _make_id.
    return _make_id("mcfunction_tag" if tag else "mcfunction", name)


def extract_mcfunction(path: Path) -> dict:
    """Extract one file node and static calls from datapack functions or tags.

    Function nodes use resource names so calls connect across files. Tags use
    a separate ID prefix. Unresolved file layouts retain a file node only.
    Edges are deduplicated by source, target, and relation; the first call's
    location and context win. JSON tag membership uses the file location L1.
    """
    str_path = str(path)
    tag = is_function_tag_path(path)
    name = _resource_name(path, tag=tag)
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(nid: str, label: str) -> None:
        if nid not in seen_ids:
            seen_ids.add(nid)
            nodes.append({
                "id": nid, "label": label, "file_type": "code",
                "source_file": str_path, "source_location": "L1",
            })

    def add_edge(reference: str, line: int, context: str) -> None:
        target = _reference_id(reference)
        if not target or target == file_nid:
            return
        key = (file_nid, target, "calls")
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({
            "source": file_nid, "target": target, "relation": "calls",
            "confidence": "EXTRACTED", "source_file": str_path,
            "source_location": f"L{line}", "weight": 1.0, "context": context,
        })

    file_nid = (_make_id("mcfunction_tag" if tag else "mcfunction", name)
                if name else _make_id(str_path))
    add_node(file_nid, ("#" if tag else "") + name if name else path.name)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if name is None:
            return {"nodes": nodes, "edges": edges}
        if tag:
            document = json.loads(text)
            if not isinstance(document, dict):
                raise ValueError("Function tag must be a JSON object")
            values = document.get("values", [])
            if not isinstance(values, list):
                raise ValueError("Function tag values must be a list")
            for entry in values:
                reference = entry.get("id") if isinstance(entry, dict) else entry
                if isinstance(reference, str):
                    add_edge(reference, 1, "tag")
        else:
            for line, raw in enumerate(text.splitlines(), 1):
                command = raw.lstrip()
                if command.startswith("#"):
                    continue
                command = command.removeprefix("$")
                for match in _CALL_RE.finditer(command):
                    context = "schedule" if match.group("schedule") else "call"
                    add_edge(match.group("ref"), line, context)
    except (OSError, ValueError) as error:
        return {"nodes": nodes, "edges": edges, "error": str(error)}
    return {"nodes": nodes, "edges": edges}
