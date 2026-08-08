"""Building the clip dictionaries a cutscene needs.

A cutscene looks its animations up by name: an actor using model X plays the clip named
"X-<section>". Animating something in Blender is not enough on its own, the animation has
to end up in a clip dictionary under that name, which is what this builds. Exporting the
result with Sollumz produces the .ycd the game expects.
"""

from typing import Optional

import bpy

from ..sollumz_properties import SollumType
from ..ycd.ycdimport import create_anim_obj, create_clip_dictionary_template
from . import cutxml

CAMERA_ANIMATION_NAME = "exportcamera"


def get_animation_names(cutscene: cutxml.Cutscene, section: int) -> dict[int, str]:
    """The name each object's animation has to have for the cutscene to find it.

    Instances sharing a model are told apart by a "^N" suffix, numbered in list order,
    which is the same rule the import side matches on.
    """
    used: dict[str, int] = {}
    names = {}

    for cut_obj in cutscene.objects:
        if cut_obj.is_camera:
            names[cut_obj.object_id] = f"{CAMERA_ANIMATION_NAME}-{section}"
            continue

        model = cut_obj.extra.get("StreamingName")
        if not model:
            continue

        variant = used.get(model, 0)
        used[model] = variant + 1

        suffix = f"^{variant}" if variant else ""
        # Peds whose face is baked into the body animation get a "_dual" clip, which is how
        # the game's own files name them
        if cut_obj.extra.get("bFaceAndBodyAreMerged"):
            suffix += "_dual"

        names[cut_obj.object_id] = f"{model}{suffix}-{section}"

    return names


def get_action(obj: bpy.types.Object) -> Optional[bpy.types.Action]:
    if obj.animation_data is not None and obj.animation_data.action is not None:
        return obj.animation_data.action

    # An animation placed on an NLA track is just as valid a source
    for track in (obj.animation_data.nla_tracks if obj.animation_data else ()):
        for strip in track.strips:
            if strip.action is not None:
                return strip.action

    return None


def add_animation(animations_obj: bpy.types.Object, clips_obj: bpy.types.Object, name: str,
                  action: bpy.types.Action, target: bpy.types.ID,
                  duration: float) -> bpy.types.Object:
    animation_obj = create_anim_obj(SollumType.ANIMATION)
    animation_obj.name = name
    animation_obj.animation_properties.hash = name

    # Target first: assigning it retargets whatever action is already there, and the action
    # is written for this target, so it must not be present yet or it gets converted twice.
    animation_obj.animation_properties.target_id = target
    animation_obj.animation_properties.action = action
    animation_obj.parent = animations_obj

    clip_obj = create_anim_obj(SollumType.CLIP)
    clip_obj.name = name
    clip_obj.clip_properties.hash = name
    clip_obj.clip_properties.name = f"pack:/{name}.clip"
    clip_obj.clip_properties.duration = duration
    clip_obj.clip_properties.animations.clear()

    clip_animation = clip_obj.clip_properties.animations.add()
    clip_animation.animation = animation_obj
    clip_animation.start_frame = 0
    clip_animation.end_frame = max(1, round(duration * (bpy.context.scene.render.fps or 30)))
    clip_obj.parent = clips_obj

    return animation_obj


def build_clip_dictionaries(cutscene: cutxml.Cutscene,
                            sources: dict[int, bpy.types.Object]) -> tuple[list[bpy.types.Object], list[str]]:
    """Builds one clip dictionary per section, named the way the cutscene expects.

    `sources` maps a cutscene object id to the Blender object holding its animation.
    Returns the dictionaries that were created, and the names of the objects that had
    nothing to contribute.
    """
    starts = [0.0] + list(cutscene.section_boundaries)
    ends = list(cutscene.section_boundaries) + [cutscene.duration]

    dictionaries = []
    skipped = []

    for section in range(cutscene.section_count):
        name = f"{cutscene.name}-{section}"
        # Deliberately left unparented: Sollumz exports the topmost Sollumz object of a
        # hierarchy, and under the cutscene these would never be reached
        clip_dict_obj, clips_obj, animations_obj = create_clip_dictionary_template(name)

        duration = max(0.0, ends[section] - starts[section])
        animation_names = get_animation_names(cutscene, section)

        for cut_obj in cutscene.objects:
            animation_name = animation_names.get(cut_obj.object_id)
            if animation_name is None:
                continue

            source = sources.get(cut_obj.object_id)
            if source is None:
                if section == 0:
                    skipped.append(cut_obj.display_name)
                continue

            action = get_action(source)
            if action is None:
                if section == 0:
                    skipped.append(cut_obj.display_name)
                continue

            add_animation(animations_obj, clips_obj, animation_name, action, source.data, duration)

        dictionaries.append(clip_dict_obj)

    return dictionaries, skipped
