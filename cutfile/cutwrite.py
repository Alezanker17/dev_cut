"""Writing cutscene files back out.

Edits are applied to the XML tree the file was parsed from, so anything left alone comes
back out exactly as it went in. Nothing is rebuilt from the parsed model, because the model
does not carry every field of every object type and rebuilding would silently drop them.
"""

import copy
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


def set_duration(cutscene: cutxml.Cutscene, duration: float) -> bool:
    """Sets the cutscene length, and the events that mark its end move with it."""
    root = cutscene.tree.getroot()
    old = cutscene.duration
    if not set_value(root, "fTotalDuration", duration):
        return False

    # Events sitting at the old end are the ones that stop and unload things; keep them
    # there. The load event list matters too, that is where the unloads live.
    for event in cutscene.events + cutscene.load_events:
        if old > 0.0 and abs(event.time - old) < 0.05:
            set_event_time(event, duration)

    set_value(root, "iRangeEnd", int(round(duration * 30.0)))
    cutscene.duration = duration
    return True


def set_placement(cutscene: cutxml.Cutscene, offset: tuple[float, float, float],
                  rotation: float = 0.0) -> bool:
    root = cutscene.tree.getroot()
    changed = set_vector(root, "vOffset", offset)
    changed = set_value(root, "fRotation", rotation) or changed
    cutscene.offset = offset
    cutscene.rotation = rotation
    return changed


# A cutscene carries no name of its own: none of the game's 465 cutscene files has a cName
# or an iNameHash. The name is the file name, so renaming one is a matter of renaming the
# .cut and its .ycd files, nothing has to be written inside.


def set_model(cut_obj: cutxml.CutObject, model_name: str) -> bool:
    """Points a model object at a different model.

    Only StreamingName is touched. cName is a hash the game never resolves back to text,
    so leaving it alone costs nothing and avoids inventing a name.
    """
    if cut_obj.node is None:
        return False

    node = cut_obj.node.find("StreamingName")
    if node is None:
        return False

    node.text = model_name
    cut_obj.extra["StreamingName"] = model_name
    return True


def next_object_id(cutscene: cutxml.Cutscene) -> int:
    return max((obj.object_id for obj in cutscene.objects), default=-1) + 1


def clone_object(cutscene: cutxml.Cutscene, source: cutxml.CutObject) -> Optional[cutxml.CutObject]:
    """Adds a copy of an existing object, with a fresh id.

    Cloning rather than building a node from scratch keeps every field the game expects,
    in the order it expects them, without having to know what they all are.
    """
    holder = cutscene.tree.getroot().find("pCutsceneObjects")
    if holder is None or source.node is None:
        return None

    node = copy.deepcopy(source.node)
    holder.append(node)

    obj = cutxml.parse_object(node)
    obj.object_id = next_object_id(cutscene)
    set_value(node, "iObjectId", obj.object_id)

    cutscene.objects.append(obj)
    return obj


def clone_event_args(cutscene: cutxml.Cutscene,
                     source: cutxml.CutEventArgs) -> Optional[cutxml.CutEventArgs]:
    """Adds a copy of an existing argument block and returns it, ready to be pointed at.

    Arguments are referenced by their position in the list, so they can only be appended:
    inserting or removing one would silently shift every reference after it.
    """
    holder = cutscene.tree.getroot().find("pCutsceneEventArgsList")
    if holder is None or source.node is None:
        return None

    node = copy.deepcopy(source.node)
    holder.append(node)

    args = cutxml.parse_event_args(node, len(cutscene.event_args))
    cutscene.event_args.append(args)
    return args


def clone_event(cutscene: cutxml.Cutscene, source: cutxml.CutEvent, time: float,
                object_id: Optional[int] = None,
                args: Optional[cutxml.CutEventArgs] = None,
                load_event: bool = False) -> Optional[cutxml.CutEvent]:
    """Adds a copy of an existing event at a new time, optionally retargeted."""
    holder_tag = "pCutsceneLoadEventList" if load_event else "pCutsceneEventList"
    holder = cutscene.tree.getroot().find(holder_tag)
    if holder is None or source.node is None:
        return None

    node = copy.deepcopy(source.node)
    holder.append(node)

    set_value(node, "fTime", float(time))
    if object_id is not None:
        set_value(node, "iObjectId", object_id)

    if args is not None:
        if node.find("iEventArgsIndex") is not None:
            set_value(node, "iEventArgsIndex", args.index)
        else:
            # exporters other than CodeWalker use a ref instead of an index
            ref = node.find("pEventArgs")
            if ref is None:
                holder.remove(node)  # better no event than one that cannot reach its args
                return None
            ref.set("ref", str(args.index))

    event = cutxml.parse_event(node)
    (cutscene.load_events if load_event else cutscene.events).append(event)
    return event


def set_int_array(node: Optional[ET.Element], tag: str, values: list[int]) -> bool:
    if node is None:
        return False

    child = node.find(tag)
    if child is None:
        return False

    text = " ".join(str(value) for value in values)
    if (child.text or "").split() == text.split():
        return False

    child.text = text
    return True


def args_mention_object(args: cutxml.CutEventArgs, object_id: int) -> bool:
    return args.object_id == object_id or object_id in args.object_id_list


def retarget_args(args: cutxml.CutEventArgs, old_id: int, new_id: int) -> bool:
    """Point an argument block at another object, in both places one can be named."""
    changed = False

    if args.object_id == old_id:
        changed = set_value(args.node, "iObjectId", new_id)
        args.object_id = new_id

    if old_id in args.object_id_list:
        ids = [new_id if i == old_id else i for i in args.object_id_list]
        changed = set_int_array(args.node, "iObjectIdList", ids) or changed
        args.object_id_list = ids

    return changed


def add_to_object_list(args: cutxml.CutEventArgs, object_id: int) -> bool:
    ids = list(args.object_id_list) + [object_id]
    if not set_int_array(args.node, "iObjectIdList", ids):
        return False

    args.object_id_list = ids
    return True


def all_events(cutscene: cutxml.Cutscene) -> list[tuple[cutxml.CutEvent, bool]]:
    """Both event lists as one, flagged by which they came from. A copy: callers append."""
    return ([(event, False) for event in cutscene.events]
            + [(event, True) for event in cutscene.load_events])


def events_for_object(cutscene: cutxml.Cutscene, object_id: int) -> list[tuple[cutxml.CutEvent, bool]]:
    """Events driving an object, either by iObjectId or through their arguments.

    Both routes count. Of the 3957 actors in the shipped cutscenes not one is reached by
    iObjectId alone, 3355 only through the arguments.
    """
    driving = []

    for event, is_load in all_events(cutscene):
        args = event.resolve(cutscene.event_args)
        if event.object_id == object_id or (args is not None and args_mention_object(args, object_id)):
            driving.append((event, is_load))

    return driving


def clone_actor(cutscene: cutxml.Cutscene, source: cutxml.CutObject,
                model_name: str = "") -> Optional[cutxml.CutObject]:
    """Add an actor modelled on an existing one, wired up the same way.

    An object alone never shows up in game, the events are what load and play it. The two
    kinds of argument block need opposite treatment: an ObjectIdListEventArgs names the
    whole cast, so the new actor just joins the list, while a block naming a single object
    gets copied and repointed.
    """
    clone = clone_object(cutscene, source)
    if clone is None:
        return None

    if model_name:
        set_model(clone, model_name)

    old, new = source.object_id, clone.object_id

    for args in list(cutscene.event_args):
        if old in args.object_id_list and new not in args.object_id_list:
            add_to_object_list(args, new)

    # keyed by the index they were copied from, so the events can find them again
    replacements: dict[int, cutxml.CutEventArgs] = {}
    for args in list(cutscene.event_args):
        if args.object_id != old:
            continue

        copy = clone_event_args(cutscene, args)
        if copy is not None:
            retarget_args(copy, old, new)
            replacements[args.index] = copy

    for event, is_load in all_events(cutscene):
        args = event.resolve(cutscene.event_args)
        copy = replacements.get(args.index) if args is not None else None
        if copy is None and event.object_id != old:
            continue

        clone_event(cutscene, event, event.time,
                    object_id=new if event.object_id == old else None,
                    args=copy, load_event=is_load)

    return clone


def validate(cutscene: cutxml.Cutscene) -> list[str]:
    """Checks the cross references hold up. An empty list means the file is coherent."""
    problems = []

    ids = [obj.object_id for obj in cutscene.objects]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        problems.append(f"duplicate object ids: {sorted(duplicates)}")

    for event in cutscene.events + cutscene.load_events:
        if event.args_ref is not None and not 0 <= event.args_ref < len(cutscene.event_args):
            problems.append(f"event at {event.time:.2f}s points at argument {event.args_ref}, "
                            f"but there are {len(cutscene.event_args)}")

        if event.object_id >= 0 and cutscene.object_by_id(event.object_id) is None:
            problems.append(f"event at {event.time:.2f}s points at object {event.object_id}, "
                            "which does not exist")

        if event.time < 0.0 or (cutscene.duration and event.time > cutscene.duration + 0.01):
            problems.append(f"event at {event.time:.2f}s falls outside the cutscene "
                            f"({cutscene.duration:.2f}s)")

    return sorted(set(problems))


def save(cutscene: cutxml.Cutscene, filepath: str):
    if cutscene.tree is None:
        raise ValueError("this cutscene was not parsed from a file, there is no tree to write")

    cutscene.tree.write(filepath, encoding="UTF-8", xml_declaration=True)
