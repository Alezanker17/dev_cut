"""Writes a new .cut from scratch, laid out like the smallest one the game ships.

Defaults are whatever the shipped cutscenes use, with the counts noted where they disagree.
"""

import xml.etree.ElementTree as ET
from typing import Optional

from . import cutxml

# Same in all 465 shipped cutscenes
FADE_COLOUR = "0xFF000000"
CAMERA_NAME = "exportcamera"
CAMERA_ANIM_STREAMING_BASE = "-175977911"
CAMERA_NEAR_DRAW_DISTANCE = "0.1"
CAMERA_FAR_DRAW_DISTANCE = "4000000"  # 464/465

# NOTE: literally "dict" everywhere, it is not the cutscene name. The .cut has no name of
# its own, the game goes by the file name.
ANIMATION_DICT_NAME = "dict"

DEFAULT_FLAGS = "281035264 0 0 0"  # most common of the 50 in use
DEFAULT_SECTION_DURATION = "4"  # 331/465
DEFAULT_FADE = "0.8"  # 454-462/465, depending which of the four
DEFAULT_DAY_COC_HOURS = "2097088"  # 446/465

FPS = 30.0  # iRangeEnd is a frame count

ASSET_MANAGER_ID = 0
ANIMATION_MANAGER_ID = 1
CAMERA_ID = 2

EVENT_LOAD_ASSETS = 0        # load event, asset manager
EVENT_LOAD_ANIMATION = 2     # load event, animation manager
EVENT_START = 22             # animation manager, at 0
EVENT_STOP = 23              # animation manager, at the end
EVENT_CAMERA_CUT = 43        # camera, one per cut
EVENT_CAMERA_START = 48      # camera, at 0


def element(parent: Optional[ET.Element], tag: str, **attributes) -> ET.Element:
    node = ET.Element(tag, {k: str(v) for k, v in attributes.items()})
    if parent is not None:
        parent.append(node)

    return node


def value_node(parent: ET.Element, tag: str, value) -> ET.Element:
    if isinstance(value, bool):
        value = "true" if value else "false"

    return element(parent, tag, value=value)


def text_node(parent: ET.Element, tag: str, text: str = "") -> ET.Element:
    node = element(parent, tag)
    if text:
        node.text = text

    return node


def vector_node(parent: ET.Element, tag: str, value) -> ET.Element:
    axes = dict(zip(("x", "y", "z", "w"), (str(v) for v in value)))
    return element(parent, tag, **axes)


def attribute_list(parent: ET.Element):
    """Every object and argument block has one, always zeroed."""
    node = element(parent, "attributeList")
    value_node(node, "UserData1", 0)
    value_node(node, "UserData2", 0)
    element(parent, "cutfAttributes")


def build_object(kind: str, object_id: int) -> ET.Element:
    item = element(None, "Item", type=f"rage__cutf{kind}")
    value_node(item, "iObjectId", object_id)
    attribute_list(item)
    return item


def build_camera_object(object_id: int = CAMERA_ID) -> ET.Element:
    item = build_object("CameraObject", object_id)
    text_node(item, "cName", CAMERA_NAME)
    value_node(item, "AnimStreamingBase", CAMERA_ANIM_STREAMING_BASE)
    value_node(item, "fNearDrawDistance", CAMERA_NEAR_DRAW_DISTANCE)
    value_node(item, "fFarDrawDistance", CAMERA_FAR_DRAW_DISTANCE)
    return item


def build_event(event_id: int, time: float, object_id: int, args_index: int) -> ET.Element:
    item = element(None, "Item", type="rage__cutfObjectIdEvent")
    value_node(item, "fTime", time)
    value_node(item, "iEventId", event_id)
    value_node(item, "iEventArgsIndex", args_index)
    element(item, "pChildEvents")
    value_node(item, "StickyId", 0)
    value_node(item, "IsChild", False)
    value_node(item, "iObjectId", object_id)
    return item


def build_args(kind: str) -> ET.Element:
    item = element(None, "Item", type=f"rage__cutf{kind}")
    attribute_list(item)
    return item


def build_object_id_args(object_id: int) -> ET.Element:
    item = build_args("ObjectIdEventArgs")
    value_node(item, "iObjectId", object_id)
    return item


def build_name_args(name: str) -> ET.Element:
    item = build_args("NameEventArgs")
    text_node(item, "cName", name)
    return item


def build_load_scene_args(offset=(0.0, 0.0, 0.0), rotation: float = 0.0) -> ET.Element:
    item = build_args("LoadSceneEventArgs")
    text_node(item, "cName")
    vector_node(item, "vOffset", offset)
    value_node(item, "fRotation", rotation)
    value_node(item, "fPitch", 0)
    value_node(item, "fRoll", 0)
    return item


# Most common value across the 6103 shipped camera cuts. -1 means no override.
CAMERA_CUT_DEFAULTS = (
    ("fNearDrawDistance", "0.15"),
    ("fFarDrawDistance", "-1"),
    ("fMapLodScale", "1"),
    ("ReflectionLodRangeStart", "-1"),
    ("ReflectionLodRangeEnd", "-1"),
    ("ReflectionSLodRangeStart", "-1"),
    ("ReflectionSLodRangeEnd", "-1"),
    ("LodMultHD", "-1"),
    ("LodMultOrphanedHD", "-1"),
    ("LodMultLod", "-1"),
    ("LodMultSLod1", "-1"),
    ("LodMultSLod2", "-1"),
    ("LodMultSLod3", "-1"),
    ("LodMultSLod4", "-1"),
    ("WaterReflectionFarClip", "-1"),
    ("SSAOLightInten", "-1"),
    ("ExposurePush", "0"),
    ("LightFadeDistanceMult", "1"),
    ("LightShadowFadeDistanceMult", "1"),
    ("LightSpecularFadeDistMult", "1"),
    ("LightVolumetricFadeDistanceMult", "1"),
    ("DirectionalLightMultiplier", "-1"),
    ("LensArtefactMultiplier", "-1"),
    ("BloomMax", "-1"),
    ("DisableHighQualityDof", "false"),
    ("FreezeReflectionMap", "false"),
    ("DisableDirectionalLighting", "false"),
    ("AbsoluteIntensityEnabled", "true"),
)


def build_camera_cut_args(name: str = "", position=(0.0, 0.0, 0.0),
                          rotation=(0.0, 0.0, 0.0, 1.0)) -> ET.Element:
    item = build_args("CameraCutEventArgs")
    text_node(item, "cName", name)
    vector_node(item, "vPosition", position)
    vector_node(item, "vRotationQuaternion", rotation)

    for tag, default in CAMERA_CUT_DEFAULTS:
        value_node(item, tag, default)

    light = element(item, "CharacterLight")
    value_node(light, "bUseTimeCycleValues", False)
    vector_node(light, "vDirection", (0, 1, 0))
    vector_node(light, "vColour", (0, 0, 0))
    value_node(light, "fIntensity", 0)

    element(item, "TimeOfDayDofModifers")
    return item


def build_tree(duration: float, offset=(0.0, 0.0, 0.0), rotation: float = 0.0,
               section_duration: float = 4.0) -> ET.ElementTree:
    """Root tags in the order every shipped cutscene writes them."""
    root = ET.Element(cutxml.ROOT_TAG)

    value_node(root, "fTotalDuration", duration)
    text_node(root, "cFaceDir")
    text_node(root, "iCutsceneFlags", DEFAULT_FLAGS)
    vector_node(root, "vOffset", offset)
    value_node(root, "fRotation", rotation)
    vector_node(root, "vTriggerOffset", (0, 0, 0))

    objects = element(root, "pCutsceneObjects")
    load_events = element(root, "pCutsceneLoadEventList")
    events = element(root, "pCutsceneEventList")
    args_list = element(root, "pCutsceneEventArgsList")

    element(root, "attributes")
    element(root, "cutfAttributes")
    value_node(root, "iRangeStart", 0)
    value_node(root, "iRangeEnd", int(round(duration * FPS)))
    value_node(root, "iAltRangeEnd", 0)
    value_node(root, "fSectionByTimeSliceDuration", section_duration)
    value_node(root, "fFadeOutCutsceneDuration", DEFAULT_FADE)
    value_node(root, "fFadeInGameDuration", DEFAULT_FADE)
    value_node(root, "fadeInColor", FADE_COLOUR)
    value_node(root, "iBlendOutCutsceneDuration", 0)
    value_node(root, "iBlendOutCutsceneOffset", 0)
    value_node(root, "fFadeOutGameDuration", DEFAULT_FADE)
    value_node(root, "fFadeInCutsceneDuration", DEFAULT_FADE)
    value_node(root, "fadeOutColor", FADE_COLOUR)
    value_node(root, "DayCoCHours", DEFAULT_DAY_COC_HOURS)

    # empty means one section, so one clip dictionary
    text_node(root, "cameraCutList")
    text_node(root, "sectionSplitList")
    element(root, "concatDataList", itemType="rage__cutfCutsceneFile2__SConcatData")
    element(root, "discardFrameList", itemType="vHaltFrequency")

    objects.append(build_object("AssetManagerObject", ASSET_MANAGER_ID))
    objects.append(build_object("AnimationManagerObject", ANIMATION_MANAGER_ID))
    objects.append(build_camera_object(CAMERA_ID))

    args_list.append(build_load_scene_args(offset, rotation))       # 0
    args_list.append(build_name_args(ANIMATION_DICT_NAME))          # 1
    args_list.append(build_object_id_args(ANIMATION_MANAGER_ID))    # 2
    args_list.append(build_camera_cut_args())                       # 3
    args_list.append(build_object_id_args(CAMERA_ID))               # 4

    load_events.append(build_event(EVENT_LOAD_ASSETS, 0.0, ASSET_MANAGER_ID, 0))
    load_events.append(build_event(EVENT_LOAD_ANIMATION, 0.0, ANIMATION_MANAGER_ID, 1))

    events.append(build_event(EVENT_START, 0.0, ANIMATION_MANAGER_ID, 2))
    events.append(build_event(EVENT_CAMERA_CUT, 0.0, CAMERA_ID, 3))
    events.append(build_event(EVENT_CAMERA_START, 0.0, CAMERA_ID, 4))
    events.append(build_event(EVENT_STOP, duration, ANIMATION_MANAGER_ID, 2))

    ET.indent(root, space=" ")
    return ET.ElementTree(root)


def create(filepath: str, duration: float = 10.0, offset=(0.0, 0.0, 0.0),
           rotation: float = 0.0, section_duration: float = 4.0) -> cutxml.Cutscene:
    """Write a new cutscene and return it parsed, ready for cutwrite."""
    tree = build_tree(duration, offset, rotation, section_duration)
    tree.write(filepath, encoding="UTF-8", xml_declaration=True)
    return cutxml.parse(filepath)
