import collections
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import bpy

from ..sollumz_properties import SollumType
from ..tools.blenderhelper import get_data_obj
from ..ycd.ycdimport import import_ycd
from . import cutxml

ANIMATION_NAME = re.compile(r"^(?P<name>.+?)(?:\^(?P<variant>\d+))?(?P<dual>_dual)?-(?P<section>\d+)$")

CAMERA_ANIMATION_NAME = "exportcamera"


@dataclass
class CutsceneImportReport:
    """What the import found and what it could not, so the user knows what to go get."""
    clip_dictionaries: list[str] = field(default_factory=list)
    missing_clip_dictionaries: list[str] = field(default_factory=list)
    animated: list[str] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        lines = []

        if self.missing_clip_dictionaries:
            lines.append("Missing clip dictionaries, expected next to the cutscene file:")
            lines += [f"    {name}" for name in self.missing_clip_dictionaries]

        if self.copied:
            counts = collections.Counter(self.copied)
            lines.append("Copied to cover repeated instances: "
                         + ", ".join(f"{name} x{n}" for name, n in sorted(counts.items())))

        if self.missing_models:
            lines.append("Missing models, import them and run 'Bind Cutscene Animations':")
            lines += [f"    {name}" for name in sorted(set(self.missing_models))]

        if not lines:
            lines.append("Everything the cutscene needs was found.")

        return lines


def parse_animation_name(hash_name: str) -> Optional[tuple[str, int, int]]:
    """Splits a cutscene animation name into (model name, variant, section)."""
    match = ANIMATION_NAME.match(hash_name)
    if match is None:
        return None

    variant = match.group("variant")
    return match.group("name"), int(variant) if variant else 0, int(match.group("section"))


def find_clip_dictionary_files(filepath: str, cutscene: cutxml.Cutscene) -> list[tuple[str, str]]:
    """Looks for the clip dictionaries of each section next to the cutscene file.

    Returns one (expected name, found path) pair per section, with an empty path when the
    file is not there.
    """
    directory = os.path.dirname(filepath)
    name = cutscene.name or os.path.basename(filepath).split(".")[0]

    found = []
    for section in range(cutscene.section_count):
        expected = f"{name}-{section}.ycd"
        for extension in (".ycd.xml", ".ycd"):
            candidate = os.path.join(directory, f"{name}-{section}{extension}")
            if os.path.exists(candidate):
                found.append((expected, candidate))
                break
        else:
            found.append((expected, ""))

    return found


def find_clip_dictionary_obj(name: str) -> Optional[bpy.types.Object]:
    """A clip dictionary already imported by the user, matched by name."""
    for obj in bpy.data.objects:
        if obj.sollum_type != SollumType.CLIP_DICTIONARY:
            continue

        if obj.name == name or obj.name.startswith(f"{name}."):
            return obj

    return None


def collect_animations(clip_dictionary_obj: bpy.types.Object) -> dict[str, bpy.types.Object]:
    animations = {}

    for child in clip_dictionary_obj.children_recursive:
        if child.sollum_type != SollumType.ANIMATION:
            continue

        animations[child.animation_properties.hash] = child

    return animations


def match_animations(cutscene: cutxml.Cutscene, animation_names: list[str]) -> dict[int, str]:
    """Maps each animated cutscene object to its animation name, without the section suffix.

    Objects sharing a model are matched to the variants of that model in list order. The
    exporter does not always number the variants contiguously, so the pairing within such a
    group is arbitrary, but every instance still gets a distinct animation.
    """
    variants: dict[str, list[str]] = {}
    for hash_name in animation_names:
        parsed = parse_animation_name(hash_name)
        if parsed is None:
            continue

        name, variant, _section = parsed
        variants.setdefault(name, []).append((variant, hash_name.rsplit("-", 1)[0]))

    for group in variants.values():
        group.sort()

    used: dict[str, int] = {}
    matched = {}

    for cut_obj in cutscene.objects:
        name = CAMERA_ANIMATION_NAME if cut_obj.is_camera else cut_obj.extra.get("StreamingName", "")
        group = variants.get(name)
        if not group:
            continue

        index = used.get(name, 0)
        if index >= len(group):
            continue

        used[name] = index + 1
        matched[cut_obj.object_id] = group[index][1]

    return matched


def find_armatures(model_name: str) -> list[bpy.types.Object]:
    """All armatures for a model, by name or by the mark left on a previous bind."""
    return [obj for obj in bpy.data.objects
            if obj.type == "ARMATURE"
            and (obj.get("cut_model") == model_name
                 or obj.name == model_name
                 or obj.name.startswith(f"{model_name}."))]


def copy_branch(source_obj: bpy.types.Object, parent: Optional[bpy.types.Object],
                armature_obj: Optional[bpy.types.Object]) -> bpy.types.Object:
    new_obj = source_obj.copy()
    new_obj.animation_data_clear()

    if parent is not None:
        new_obj.parent = parent
        new_obj.matrix_parent_inverse = source_obj.matrix_parent_inverse.copy()

    for collection in source_obj.users_collection:
        collection.objects.link(new_obj)

    if armature_obj is not None:
        for modifier in new_obj.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = armature_obj

    for child in source_obj.children:
        copy_branch(child, new_obj, armature_obj)

    return new_obj


def duplicate_model(source_obj: bpy.types.Object) -> bpy.types.Object:
    """Copies a model, with everything under it, so a second instance can play its own
    animation.

    The armature data is copied rather than linked, because an animation targets armature
    data and there must be exactly one object using it. Meshes stay linked, they are
    identical, so the copies cost almost nothing.
    """
    new_obj = source_obj.copy()
    new_obj.data = source_obj.data.copy()
    new_obj.animation_data_clear()

    for collection in source_obj.users_collection:
        collection.objects.link(new_obj)

    for child in source_obj.children:
        copy_branch(child, new_obj, new_obj)

    return new_obj


def find_target_obj(obj: bpy.types.Object, model_name: str,
                    used: set[str]) -> tuple[Optional[bpy.types.Object], bool]:
    """Picks the model for this cutscene object, copying it if every instance is taken."""
    if obj.sollum_type == SollumType.CUTSCENE_CAMERA:
        return obj, False

    armatures = find_armatures(model_name)
    if not armatures:
        return None, False

    for armature_obj in armatures:
        if armature_obj.name not in used:
            return armature_obj, False

    return duplicate_model(armatures[0]), True


def place_in_cutscene(target_obj: bpy.types.Object, placeholder: bpy.types.Object):
    """Parents a model to its cutscene placeholder.

    Animations are authored around the cutscene origin, not the world origin, so a model
    imported on its own would play its animation wherever it happens to sit. Parenting it
    to the placeholder puts it under the cutscene offset and rotation, and the mover track
    takes it from there.
    """
    if target_obj == placeholder or target_obj.parent == placeholder:
        return

    target_obj.parent = placeholder
    target_obj.matrix_parent_inverse.identity()
    target_obj.location = (0.0, 0.0, 0.0)
    target_obj.rotation_euler = (0.0, 0.0, 0.0)
    target_obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)


def build_nla_track(target_obj: bpy.types.Object, actions: list[tuple[float, bpy.types.Action]], fps: int):
    if target_obj.animation_data is None:
        target_obj.animation_data_create()

    # Rebinding replaces the previous strips instead of stacking a second track
    for track in [t for t in target_obj.animation_data.nla_tracks if t.name == "Cutscene"]:
        target_obj.animation_data.nla_tracks.remove(track)

    track = target_obj.animation_data.nla_tracks.new()
    track.name = "Cutscene"

    for start_time, action in actions:
        strip = track.strips.new(action.name, round(start_time * fps), action)
        strip.blend_type = "COMBINE"
        strip.extrapolation = "NOTHING"


def import_cutscene_animations(filepath: str, cutscene: cutxml.Cutscene,
                               cutscene_obj: bpy.types.Object) -> CutsceneImportReport:
    """Imports the clip dictionaries next to the cutscene and binds them to its objects."""
    report = CutsceneImportReport()

    section_animations: list[dict[str, bpy.types.Object]] = []
    animation_names: list[str] = []

    for expected, path in find_clip_dictionary_files(filepath, cutscene):
        # A dictionary the user already imported wins over the file on disk
        existing = find_clip_dictionary_obj(expected.removesuffix(".ycd"))
        if existing is not None:
            animations = collect_animations(existing)
        elif path:
            animations = collect_animations(import_ycd(path))
        else:
            report.missing_clip_dictionaries.append(expected)
            section_animations.append({})
            continue

        report.clip_dictionaries.append(expected)
        section_animations.append(animations)
        if not animation_names:
            animation_names = list(animations)

    if not report.clip_dictionaries:
        return report

    matched = match_animations(cutscene, animation_names)
    objects_by_id = {obj.get("cut_object_id"): obj for obj in cutscene_obj.children_recursive}

    fps = bpy.context.scene.render.fps or 30
    start_times = [0.0] + list(cutscene.section_boundaries)
    used: set[str] = set()

    for object_id, animation_name in matched.items():
        obj = objects_by_id.get(object_id)
        if obj is None:
            continue

        cut_obj = cutscene.object_by_id(object_id)
        model_name = cut_obj.extra.get("StreamingName", animation_name)

        obj["cut_animation"] = animation_name

        target_obj, copied = find_target_obj(obj, model_name, used)
        if target_obj is None:
            # Only models can be bound to something; effects and the like have no armature
            if cut_obj.is_actor:
                report.missing_models.append(model_name)
            continue

        used.add(target_obj.name)
        target_id = target_obj.data

        actions = []
        for section, animations in enumerate(section_animations):
            animation_obj = animations.get(f"{animation_name}-{section}")
            if animation_obj is None:
                continue

            animation_obj.animation_properties.target_id = target_id
            action = animation_obj.animation_properties.action
            if action is not None and section < len(start_times):
                actions.append((start_times[section], action))

        if not actions:
            report.missing_models.append(model_name)
            continue

        target_obj["cut_model"] = model_name
        place_in_cutscene(target_obj, obj)
        build_nla_track(target_obj, actions, fps)
        report.animated.append(model_name)
        if copied:
            report.copied.append(model_name)

    return report
