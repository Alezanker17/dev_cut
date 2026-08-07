import math
import os

import bpy
from mathutils import Vector

from .. import logger
from ..sollumz_properties import SOLLUMZ_UI_NAMES, SollumType
from . import cutanim, cutxml

EMPTY_DISPLAY: dict[str, tuple[str, float]] = {
    "PedModelObject": ("ARROWS", 0.6),
    "VehicleModelObject": ("CUBE", 1.2),
    "PropModelObject": ("PLAIN_AXES", 0.4),
    "WeaponModelObject": ("PLAIN_AXES", 0.25),
    "LightObject": ("SPHERE", 0.3),
    "AnimatedLightObject": ("SPHERE", 0.3),
    "AudioObject": ("SPHERE", 0.2),
    "ParticleEffectObject": ("SPHERE", 0.25),
    "AnimatedParticleEffectObject": ("SPHERE", 0.25),
    "DecalObject": ("PLAIN_AXES", 0.2),
    "SubtitleObject": ("PLAIN_AXES", 0.2),
}


def create_empty(name: str, display_type: str = "PLAIN_AXES", size: float = 0.5) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = display_type
    obj.empty_display_size = size
    return obj


def parse_corners(raw: str) -> list[Vector]:
    values = []
    for token in raw.split():
        try:
            values.append(float(token))
        except ValueError:
            pass

    return [Vector(values[i:i + 3]) for i in range(0, len(values) - 2, 3)]


def create_bounds_obj(cut_obj: cutxml.CutObject, name: str) -> bpy.types.Object:
    corners = parse_corners(cut_obj.extra.get("vCorners", ""))
    if len(corners) < 3:
        return create_empty(name, "CUBE", 1.0)

    height = float(cut_obj.extra.get("fHeight", 0.0) or 0.0)
    verts = list(corners)
    if height:
        verts += [Vector((c.x, c.y, c.z + height)) for c in corners]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [])
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj.display_type = "WIRE"
    return obj


LIGHT_KINDS = frozenset(("LightObject", "AnimatedLightObject"))
SPHERE_KINDS = frozenset(("HiddenModelObject", "FixupModelObject"))

# iLightType, the only two values the game ships
LIGHT_TYPES = {1: "POINT", 2: "SPOT"}


def create_light_obj(cut_obj: cutxml.CutObject, name: str) -> bpy.types.Object:
    light = bpy.data.lights.new(name, LIGHT_TYPES.get(cut_obj.extra.get("iLightType"), "POINT"))
    light.color = cut_obj.extra.get("vColour", (1.0, 1.0, 1.0))
    light.energy = float(cut_obj.extra.get("fIntensity", 1.0) or 0.0)

    falloff = float(cut_obj.extra.get("fFallOff", 0.0) or 0.0)
    if falloff > 0.0:
        light.use_custom_distance = True
        light.cutoff_distance = falloff

    if light.type == "SPOT":
        light.spot_size = math.radians(float(cut_obj.extra.get("fConeAngle", 45.0) or 45.0))
        inner = float(cut_obj.extra.get("fInnerConeAngle", 0.0) or 0.0)
        if light.spot_size > 0.0:
            light.spot_blend = max(0.0, 1.0 - math.radians(inner) / light.spot_size)

    obj = bpy.data.objects.new(name, light)
    obj.location = Vector(cut_obj.extra.get("vPosition", (0.0, 0.0, 0.0)))

    direction = Vector(cut_obj.extra.get("vDirection", (0.0, 0.0, -1.0)))
    if direction.length > 0.0:
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Vector((0.0, 0.0, -1.0)).rotation_difference(direction.normalized())

    return obj


def create_sphere_obj(cut_obj: cutxml.CutObject, name: str) -> bpy.types.Object:
    obj = create_empty(name, "SPHERE", float(cut_obj.extra.get("fRadius", 0.5) or 0.5))
    obj.location = Vector(cut_obj.extra.get("vPosition", (0.0, 0.0, 0.0)))
    return obj


def store_object_properties(obj: bpy.types.Object, cut_obj: cutxml.CutObject):
    obj["cut_object_id"] = cut_obj.object_id
    obj["cut_object_kind"] = cut_obj.kind
    obj["cut_object_name"] = cut_obj.name

    for key, value in cut_obj.extra.items():
        if isinstance(value, (int, float, str, bool)):
            obj[f"cut_{key}"] = value


def create_cutscene_obj(cut_obj: cutxml.CutObject) -> bpy.types.Object:
    name = f"{cut_obj.object_id} {cut_obj.display_name}"

    if cut_obj.is_camera:
        obj = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        obj.sollum_type = SollumType.CUTSCENE_CAMERA
    elif cut_obj.is_bounds:
        obj = create_bounds_obj(cut_obj, name)
        obj.sollum_type = SollumType.CUTSCENE_BOUNDS
    elif cut_obj.kind in LIGHT_KINDS:
        obj = create_light_obj(cut_obj, name)
        obj.sollum_type = SollumType.CUTSCENE_OBJECT
    elif cut_obj.kind in SPHERE_KINDS:
        obj = create_sphere_obj(cut_obj, name)
        obj.sollum_type = SollumType.CUTSCENE_OBJECT
    elif cut_obj.is_actor:
        obj = create_empty(name, *EMPTY_DISPLAY.get(cut_obj.kind, ("ARROWS", 0.5)))
        obj.sollum_type = SollumType.CUTSCENE_ACTOR
    else:
        obj = create_empty(name, *EMPTY_DISPLAY.get(cut_obj.kind, ("PLAIN_AXES", 0.3)))
        obj.sollum_type = SollumType.CUTSCENE_OBJECT

    store_object_properties(obj, cut_obj)
    return obj


def create_event_markers(cutscene: cutxml.Cutscene, fps: int) -> int:
    markers = bpy.context.scene.timeline_markers

    for time, event, args, cut_obj in cutscene.timeline():
        label = f"ev{event.event_id}"
        if cut_obj is not None:
            label += f" {cut_obj.display_name}"
        elif args is not None and args.name:
            label += f" {args.name}"

        marker = markers.new(label, frame=round(time * fps))
        marker.select = False

    return len(cutscene.events)


def import_cutscene(filepath: str, create_markers: bool = True, set_frame_range: bool = True,
                    import_animations: bool = True):
    cutscene = cutxml.parse(filepath)

    # The PSO XML does not store the cutscene name, only its hash, so take it from the file name
    if not cutscene.name:
        cutscene.name = os.path.basename(filepath).split(".")[0]

    collection = bpy.context.collection
    fps = bpy.context.scene.render.fps or 30

    cutscene_obj = create_empty(cutscene.name or SOLLUMZ_UI_NAMES[SollumType.CUTSCENE], "SPHERE", 1.0)
    cutscene_obj.sollum_type = SollumType.CUTSCENE
    # Everything in a cutscene is authored around its own origin, this places it in the world
    cutscene_obj.location = Vector(cutscene.offset)
    cutscene_obj.rotation_euler = (0.0, 0.0, math.radians(cutscene.rotation))
    cutscene_obj["cut_filepath"] = filepath
    cutscene_obj["cut_name"] = cutscene.name
    cutscene_obj["cut_name_hash"] = cutscene.name_hash
    cutscene_obj["cut_duration"] = cutscene.duration
    cutscene_obj["cut_rotation"] = cutscene.rotation
    cutscene_obj["cut_fade_in"] = cutscene.fade_in_duration
    cutscene_obj["cut_fade_out"] = cutscene.fade_out_duration
    collection.objects.link(cutscene_obj)

    groups: dict[str, bpy.types.Object] = {}

    def get_group(name: str) -> bpy.types.Object:
        if name not in groups:
            group = create_empty(name, "PLAIN_AXES", 0.2)
            group.parent = cutscene_obj
            collection.objects.link(group)
            groups[name] = group

        return groups[name]

    group_names = {
        SollumType.CUTSCENE_CAMERA: "Cameras",
        SollumType.CUTSCENE_ACTOR: "Actors",
        SollumType.CUTSCENE_BOUNDS: "Bounds",
        SollumType.CUTSCENE_OBJECT: "Objects",
    }

    for cut_obj in cutscene.objects:
        obj = create_cutscene_obj(cut_obj)
        obj.parent = get_group(group_names[obj.sollum_type])
        collection.objects.link(obj)

    if set_frame_range and cutscene.duration > 0:
        bpy.context.scene.frame_start = 0
        bpy.context.scene.frame_end = max(1, round(cutscene.duration * fps))

    markers = create_event_markers(cutscene, fps) if create_markers else 0

    if import_animations:
        report = cutanim.import_cutscene_animations(filepath, cutscene, cutscene_obj)

        total = len(report.animated) + len(report.missing_models)
        logger.info(
            f"Cutscene '{cutscene.name}': {len(report.clip_dictionaries)} of "
            f"{cutscene.section_count} clip dictionaries, {len(report.animated)} of {total} "
            f"objects animated.\n" + "\n".join(report.lines())
        )

    return cutscene_obj, cutscene, markers
