"""Writing cutscene files back out.

Edits are applied to the XML tree the file was parsed from, so anything left alone comes
back out exactly as it went in. Nothing is rebuilt from the parsed model, because the model
does not carry every field of every object type and rebuilding would silently drop them.
"""

import math
import xml.etree.ElementTree as ET
from typing import Optional

from . import cutxml


def format_float(value: float) -> str:
    """Matches how the exporters write floats: no trailing zeros, no exponent."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


EPSILON = 1e-4


def same_number(raw: Optional[str], value: float) -> bool:
    """True when the file already holds this value, so it can be left alone.

    The tolerance grows with the magnitude: Blender keeps these as 32 bit floats, and world
    coordinates in the thousands come back with more error than a fixed epsilon allows.
    """
    if raw is None:
        return False

    try:
        original = float(raw)
    except ValueError:
        return False

    return abs(original - float(value)) <= max(EPSILON, abs(original) * 1e-6)


def set_value(node: Optional[ET.Element], tag: str, value) -> bool:
    """Writes a value only if it actually differs, so untouched fields keep their
    original text and the file diff stays down to what really changed."""
    if node is None:
        return False

    child = node.find(tag)
    if child is None:
        return False

    if isinstance(value, bool):
        text = "true" if value else "false"
        if (child.get("value") or "").strip().lower() == text:
            return False
    elif isinstance(value, (int, float)):
        if same_number(child.get("value"), value):
            return False
        text = format_float(float(value))
    else:
        text = str(value)
        if child.get("value") == text:
            return False

    child.set("value", text)
    return True


def set_vector(node: Optional[ET.Element], tag: str, value) -> bool:
    if node is None:
        return False

    child = node.find(tag)
    if child is None:
        return False

    axes = ("x", "y", "z", "w")[:len(value)]
    if all(same_number(child.get(axis), component) for axis, component in zip(axes, value)):
        return False

    for axis, component in zip(axes, value):
        child.set(axis, format_float(component))

    return True


def set_event_time(event: cutxml.CutEvent, time: float) -> bool:
    if not set_value(event.node, "fTime", float(time)):
        return False

    event.time = time
    return True


def set_camera_cut(args: cutxml.CutEventArgs, position: Optional[tuple[float, float, float]] = None,
                   rotation: Optional[tuple[float, float, float, float]] = None) -> bool:
    """Moves a camera cut. Rotation is a quaternion, stored without its w component."""
    ok = True

    if position is not None:
        ok = set_vector(args.node, "vPosition", position) and ok
        args.extra["vPosition"] = position

    if rotation is not None and args.node is not None:
        child = args.node.find("vRotationQuaternion")
        if child is None:
            ok = False
        else:
            for axis, component in zip(("x", "y", "z", "w"), rotation):
                child.set(axis, format_float(component))
            args.extra["vRotationQuaternion"] = rotation[:3]

    return ok


def set_object_field(cut_obj: cutxml.CutObject, tag: str, value) -> bool:
    if isinstance(value, tuple):
        ok = set_vector(cut_obj.node, tag, value)
    else:
        ok = set_value(cut_obj.node, tag, value)

    if ok:
        cut_obj.extra[tag] = value

    return ok


def apply_light(cut_obj: cutxml.CutObject, obj) -> bool:
    """Writes a Blender light back into its cutscene object."""
    light = obj.data
    changed = set_vector(cut_obj.node, "vPosition", tuple(obj.location))
    changed = set_vector(cut_obj.node, "vColour", tuple(light.color)) or changed
    changed = set_value(cut_obj.node, "fIntensity", float(light.energy)) or changed

    # A light points down its own -Z, which is the third column of its matrix, negated
    axis = obj.matrix_local.col[2]
    length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2) or 1.0
    direction = (-axis[0] / length, -axis[1] / length, -axis[2] / length)
    changed = set_vector(cut_obj.node, "vDirection", direction) or changed

    if light.type == "SPOT":
        cone = math.degrees(light.spot_size)
        changed = set_value(cut_obj.node, "fConeAngle", cone) or changed
        inner = cone * (1.0 - light.spot_blend)
        changed = set_value(cut_obj.node, "fInnerConeAngle", inner) or changed

    if light.use_custom_distance:
        changed = set_value(cut_obj.node, "fFallOff", float(light.cutoff_distance)) or changed

    return changed


def apply_sphere(cut_obj: cutxml.CutObject, obj, to_world) -> bool:
    """Writes a hidden or fixup volume back. These are stored in world coordinates."""
    world = to_world @ obj.location
    changed = set_vector(cut_obj.node, "vPosition", (world[0], world[1], world[2]))
    return set_value(cut_obj.node, "fRadius", float(obj.empty_display_size)) or changed


def save(cutscene: cutxml.Cutscene, filepath: str):
    if cutscene.tree is None:
        raise ValueError("this cutscene was not parsed from a file, there is no tree to write")

    cutscene.tree.write(filepath, encoding="UTF-8", xml_declaration=True)
