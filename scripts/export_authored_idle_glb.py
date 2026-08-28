"""Export Ari's authored crossed-arm frame as a static, morph-enabled GLB."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if not arguments:
        raise RuntimeError("Pass the output GLB path after '--'.")
    output = Path(arguments[0]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    rig = bpy.data.objects.get("rig")
    action = bpy.data.actions.get("Male poses")
    if rig is None or rig.type != "ARMATURE" or action is None:
        raise RuntimeError("Expected the authored 'rig' and 'Male poses' action.")
    if rig.animation_data is None:
        rig.animation_data_create()
    idle_action = action.copy()
    idle_action.name = "AptiorDesk_Idle_Pose"
    rig.animation_data.action = idle_action
    scene.frame_set(1)
    scene.frame_start = 1
    scene.frame_end = 1
    bpy.context.view_layer.update()

    # The application drives every facial morph directly. Export only the
    # authored body action so no test animation can overwrite blinking or
    # lip-sync controls at runtime.
    for obj in bpy.data.objects:
        shape_keys = getattr(obj.data, "shape_keys", None)
        if shape_keys and shape_keys.animation_data:
            shape_keys.animation_data.action = None

    bpy.ops.object.select_all(action="DESELECT")
    selected = {rig}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        uses_rig = any(
            modifier.type == "ARMATURE" and modifier.object == rig
            for modifier in obj.modifiers
        )
        if uses_rig:
            selected.add(obj)
    for obj in selected:
        obj.hide_set(False)
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig

    print("Exporting authored idle objects:", sorted(obj.name for obj in selected))
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_frame_range=True,
        export_animation_mode="ACTIVE_ACTIONS",
        export_nla_strips_merged_animation_name="AptiorDesk_Idle_Pose",
        export_bake_animation=True,
        export_optimize_animation_size=False,
        export_morph_animation=False,
        export_skins=True,
        # Keep the complete authored hierarchy.  The distributable GLB was
        # exported from this hierarchy, so collapsing it to deformation bones
        # changes parent space and turns otherwise-correct local pose values
        # into incompatible transforms when they are merged into that asset.
        export_def_bones=False,
        export_morph=True,
        export_morph_normal=True,
        export_morph_tangent=False,
        export_lights=False,
        export_cameras=False,
        export_yup=True,
    )
    print(f"Exported authored idle GLB to {output}")


main()
