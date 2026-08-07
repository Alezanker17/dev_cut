"""Writing cutscene files back out.

Edits are applied to the XML tree the file was parsed from, so anything left alone comes
back out exactly as it went in. Nothing is rebuilt from the parsed model, because the model
does not carry every field of every object type and rebuilding would silently drop them.
"""

import xml.etree.ElementTree as ET
from typing import Optional

from . import cutxml


def format_float(value: float) -> str:
    """Matches how the exporters write floats: no trailing zeros, no exponent."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def set_value(node: Optional[ET.Element], tag: str, value) -> bool:
    if node is None:
        return False

    child = node.find(tag)
    if child is None:
        return False

    if isinstance(value, bool):
        child.set("value", "true" if value else "false")
    elif isinstance(value, float):
        child.set("value", format_float(value))
    else:
        child.set("value", str(value))

    return True


def set_vector(node: Optional[ET.Element], tag: str, value: tuple[float, float, float]) -> bool:
    if node is None:
        return False

    child = node.find(tag)
    if child is None:
        return False

    for axis, component in zip(("x", "y", "z"), value):
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


def save(cutscene: cutxml.Cutscene, filepath: str):
    if cutscene.tree is None:
        raise ValueError("this cutscene was not parsed from a file, there is no tree to write")

    cutscene.tree.write(filepath, encoding="UTF-8", xml_declaration=True)
