"""Restore validated materials/textures onto an authored-pose GLB.

The Blender source is authoritative for the rig and authored pose, while the
previous production GLB is authoritative for Qt-compatible material export.
Both assets use the same mesh primitive and material slot ordering.  This tool
keeps the posed asset's geometry, skeleton, morph targets, and animation, then
copies the production material/texture payload without re-encoding it.
"""

from __future__ import annotations

import argparse
import copy
import json
import struct
from pathlib import Path
from typing import Any

JSON_CHUNK = b"JSON"
BIN_CHUNK = b"BIN\x00"


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or total_length != len(data):
        raise ValueError(f"{path} is not a valid GLB 2.0 file.")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == JSON_CHUNK:
            document = json.loads(chunk.rstrip(b"\x00 \t\r\n"))
        elif chunk_type == BIN_CHUNK:
            binary = chunk
    if document is None:
        raise ValueError(f"{path} contains no JSON chunk.")
    return document, binary


def _write_glb(path: Path, document: dict[str, Any], binary: bytes) -> None:
    document["buffers"][0]["byteLength"] = len(binary)
    json_chunk = json.dumps(
        document, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary += b"\x00" * ((-len(binary)) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<I4s", len(json_chunk), JSON_CHUNK)
        + json_chunk
        + struct.pack("<I4s", len(binary), BIN_CHUNK)
        + binary
    )


def _material_names(document: dict[str, Any]) -> list[str | None]:
    return [material.get("name") for material in document.get("materials", [])]


def _primitive_materials(document: dict[str, Any]) -> list[list[int | None]]:
    return [
        [primitive.get("material") for primitive in mesh.get("primitives", [])]
        for mesh in document.get("meshes", [])
    ]


def restore_materials(
    pose_document: dict[str, Any],
    pose_binary: bytes,
    material_document: dict[str, Any],
    material_binary: bytes,
) -> tuple[dict[str, Any], bytes]:
    if _material_names(pose_document) != _material_names(material_document):
        raise ValueError("Material names/order differ between the two GLBs.")
    if _primitive_materials(pose_document) != _primitive_materials(material_document):
        raise ValueError("Mesh primitive material slots differ between the two GLBs.")

    result = copy.deepcopy(pose_document)
    binary = bytearray(pose_binary)
    result_views = result.setdefault("bufferViews", [])
    source_views = material_document.get("bufferViews", [])
    view_map: dict[int, int] = {}

    def copy_view(source_index: int) -> int:
        if source_index in view_map:
            return view_map[source_index]
        source_view = copy.deepcopy(source_views[source_index])
        start = source_view.get("byteOffset", 0)
        end = start + source_view["byteLength"]
        binary.extend(b"\x00" * ((-len(binary)) % 4))
        source_view["buffer"] = 0
        source_view["byteOffset"] = len(binary)
        binary.extend(material_binary[start:end])
        target_index = len(result_views)
        result_views.append(source_view)
        view_map[source_index] = target_index
        return target_index

    images = copy.deepcopy(material_document.get("images", []))
    for image in images:
        source_view_index = image.get("bufferView")
        if source_view_index is not None:
            image["bufferView"] = copy_view(source_view_index)

    result["materials"] = copy.deepcopy(material_document.get("materials", []))
    result["samplers"] = copy.deepcopy(material_document.get("samplers", []))
    result["images"] = images
    result["textures"] = copy.deepcopy(material_document.get("textures", []))

    for key in ("extensionsUsed", "extensionsRequired"):
        values = list(
            dict.fromkeys(
                result.get(key, []) + material_document.get(key, [])
            )
        )
        if values:
            result[key] = values
        else:
            result.pop(key, None)
    result["buffers"][0]["byteLength"] = len(binary)
    return result, bytes(binary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pose", type=Path)
    parser.add_argument("materials", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pose_document, pose_binary = _read_glb(args.pose)
    material_document, material_binary = _read_glb(args.materials)
    result, binary = restore_materials(
        pose_document,
        pose_binary,
        material_document,
        material_binary,
    )
    _write_glb(args.output, result, binary)
    print(
        f"Restored {len(result.get('materials', []))} materials and "
        f"{len(result.get('images', []))} images into {args.output}."
    )


if __name__ == "__main__":
    main()
