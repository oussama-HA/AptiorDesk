"""Inspect a GLB file stored directly or inside a ZIP archive.

This intentionally uses only the Python standard library so it can run in the
project development environment without adding a runtime dependency.
"""

from __future__ import annotations

import argparse
import json
import struct
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


def _read_glb(path: Path) -> tuple[bytes, str]:
    if path.suffix.lower() != ".zip":
        return path.read_bytes(), path.name
    with zipfile.ZipFile(path) as archive:
        candidates = [
            name for name in archive.namelist() if name.lower().endswith(".glb")
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one GLB in {path.name}; found {len(candidates)}: {candidates}"
            )
        return archive.read(candidates[0]), candidates[0]


def _parse_glb(data: bytes) -> dict[str, Any]:
    if len(data) < 20:
        raise ValueError("File is too small to be a GLB")
    magic, version, total_length = struct.unpack_from("<4sII", data)
    if magic != b"glTF":
        raise ValueError("Invalid GLB signature")
    if total_length != len(data):
        raise ValueError(
            f"GLB header length {total_length} does not match file length {len(data)}"
        )

    offset = 12
    document: dict[str, Any] | None = None
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == b"JSON":
            document = json.loads(chunk.rstrip(b"\x00 \t\r\n"))
    if document is None:
        raise ValueError("GLB contains no JSON chunk")
    document["_glb_version"] = version
    document["_byte_length"] = total_length
    return document


def _name(item: dict[str, Any], index: int) -> str:
    return str(item.get("name") or f"#{index}")


def _summary(document: dict[str, Any], member_name: str) -> dict[str, Any]:
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    skins = document.get("skins", [])
    animations = document.get("animations", [])
    materials = document.get("materials", [])
    images = document.get("images", [])

    parented: set[int] = set()
    for node in nodes:
        parented.update(node.get("children", []))

    mesh_details = []
    morph_names: list[str] = []
    for index, mesh in enumerate(meshes):
        target_names = list(mesh.get("extras", {}).get("targetNames", []))
        max_targets = max(
            (len(primitive.get("targets", [])) for primitive in mesh.get("primitives", [])),
            default=0,
        )
        if target_names:
            morph_names.extend(str(value) for value in target_names)
        mesh_details.append(
            {
                "index": index,
                "name": _name(mesh, index),
                "primitives": len(mesh.get("primitives", [])),
                "morph_target_count": max_targets,
                "morph_target_names": target_names,
                "default_weights": mesh.get("weights", []),
            }
        )

    animation_details = []
    animated_nodes: Counter[str] = Counter()
    animated_paths: Counter[str] = Counter()
    for index, animation in enumerate(animations):
        channel_summaries = []
        for channel in animation.get("channels", []):
            target = channel.get("target", {})
            node_index = target.get("node")
            node_name = (
                _name(nodes[node_index], node_index)
                if isinstance(node_index, int) and node_index < len(nodes)
                else "(none)"
            )
            path = str(target.get("path", "(none)"))
            animated_nodes[node_name] += 1
            animated_paths[path] += 1
            channel_summaries.append({"node": node_name, "path": path})
        animation_details.append(
            {
                "index": index,
                "name": _name(animation, index),
                "channels": len(channel_summaries),
                "samplers": len(animation.get("samplers", [])),
                "targets": channel_summaries,
            }
        )

    skin_details = []
    for index, skin in enumerate(skins):
        joint_names = [
            _name(nodes[joint], joint)
            for joint in skin.get("joints", [])
            if isinstance(joint, int) and joint < len(nodes)
        ]
        skin_details.append(
            {
                "index": index,
                "name": _name(skin, index),
                "joint_count": len(joint_names),
                "joints": joint_names,
                "skeleton": skin.get("skeleton"),
            }
        )

    interesting_terms = (
        "head",
        "neck",
        "jaw",
        "mouth",
        "lip",
        "eye",
        "brow",
        "tongue",
        "teeth",
        "face",
        "cheek",
    )
    facial_nodes = [
        _name(node, index)
        for index, node in enumerate(nodes)
        if any(term in _name(node, index).lower() for term in interesting_terms)
    ]

    return {
        "member": member_name,
        "asset": document.get("asset", {}),
        "glb_version": document["_glb_version"],
        "byte_length": document["_byte_length"],
        "extensions_used": document.get("extensionsUsed", []),
        "extensions_required": document.get("extensionsRequired", []),
        "counts": {
            "scenes": len(document.get("scenes", [])),
            "nodes": len(nodes),
            "root_nodes": len(nodes) - len(parented),
            "meshes": len(meshes),
            "skins": len(skins),
            "animations": len(animations),
            "materials": len(materials),
            "textures": len(document.get("textures", [])),
            "images": len(images),
            "accessors": len(document.get("accessors", [])),
        },
        "root_nodes": [
            _name(node, index) for index, node in enumerate(nodes) if index not in parented
        ],
        "facial_nodes": facial_nodes,
        "skins": skin_details,
        "meshes": mesh_details,
        "morph_target_names": morph_names,
        "animations": animation_details,
        "animated_node_channel_counts": animated_nodes.most_common(),
        "animated_path_counts": dict(animated_paths),
        "materials": [_name(item, index) for index, item in enumerate(materials)],
        "images": [
            {
                "name": _name(item, index),
                "mime_type": item.get("mimeType"),
                "embedded": "bufferView" in item,
                "uri": item.get("uri"),
            }
            for index, item in enumerate(images)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Omit per-joint and per-channel details from the rendered report.",
    )
    args = parser.parse_args()
    data, member_name = _read_glb(args.path)
    report = _summary(_parse_glb(data), member_name)
    if args.compact:
        for skin in report["skins"]:
            skin["joints"] = skin["joints"][:24]
            skin["joints_truncated"] = skin["joint_count"] > len(skin["joints"])
        for animation in report["animations"]:
            animation["targets"] = animation["targets"][:24]
            animation["targets_truncated"] = (
                animation["channels"] > len(animation["targets"])
            )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
