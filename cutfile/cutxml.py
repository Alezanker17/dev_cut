import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from szio.gta5.jenkhash import try_resolve_maybe_hashed_name

ROOT_TAG = "rage__cutfCutsceneFile2"
RAGE_PREFIX = "rage__"

ACTOR_KINDS = frozenset((
    "PedModelObject",
    "VehicleModelObject",
    "PropModelObject",
    "WeaponModelObject",
))

BOUNDS_KINDS = frozenset((
    "BlockingBoundsObject",
    "RemovalBoundsObject",
))

COMMON_OBJECT_TAGS = frozenset(("iObjectId", "cName", "attributeList"))
COMMON_ARGS_TAGS = frozenset(("cName", "iObjectId", "iObjectIdList", "attributeList"))


def get_text(node: Optional[ET.Element]) -> str:
    if node is None or node.text is None:
        return ""

    # Names are atHashStrings, so they come out as 'hash_XXXXXXXX' unless a name table has
    # them. Nothing here can reverse a hash, the table is the only way back to the string.
    return try_resolve_maybe_hashed_name(node.text.strip())


def get_value(node: Optional[ET.Element], cast=float, default=0.0):
    if node is None:
        return default

    raw = node.get("value")
    if raw is None:
        return default

    if cast is bool:
        return raw.strip().lower() == "true"

    try:
        return cast(raw)
    except ValueError:
        return default


def get_vector(node: Optional[ET.Element]) -> tuple[float, float, float]:
    if node is None:
        return (0.0, 0.0, 0.0)

    return (float(node.get("x", 0.0)), float(node.get("y", 0.0)), float(node.get("z", 0.0)))


def get_float_array(node: Optional[ET.Element]) -> list[float]:
    if node is None or not node.text:
        return []

    values = []
    for token in node.text.split():
        try:
            values.append(float(token))
        except ValueError:
            pass

    return values


def get_int_array(node: Optional[ET.Element]) -> list[int]:
    if node is None or not node.text:
        return []

    values = []
    for token in node.text.split():
        try:
            values.append(int(token))
        except ValueError:
            pass

    return values


def get_object_kind(node: ET.Element) -> str:
    kind = node.get("type", "")
    kind = kind.removeprefix(RAGE_PREFIX)
    return kind.removeprefix("cutf")


def get_extra_fields(node: ET.Element, skip: frozenset) -> dict[str, Any]:
    extra = {}

    for child in node:
        if child.tag in skip:
            continue

        if child.get("value") is not None:
            raw = child.get("value")
            if raw.strip().lower() in ("true", "false"):
                extra[child.tag] = raw.strip().lower() == "true"
            else:
                try:
                    extra[child.tag] = float(raw) if "." in raw else int(raw)
                except ValueError:
                    extra[child.tag] = raw
        elif child.get("x") is not None:
            extra[child.tag] = get_vector(child)
        elif child.get("content") == "int_array":
            extra[child.tag] = get_int_array(child)
        else:
            text = get_text(child)
            if text:
                extra[child.tag] = text

    return extra


@dataclass
class CutObject:
    object_id: int = -1
    kind: str = ""
    name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    node: Optional[ET.Element] = None

    @property
    def is_camera(self) -> bool:
        return self.kind == "CameraObject"

    @property
    def is_actor(self) -> bool:
        return self.kind in ACTOR_KINDS

    @property
    def is_bounds(self) -> bool:
        return self.kind in BOUNDS_KINDS

    @property
    def display_name(self) -> str:
        """A name fit to show in the UI.

        cName is an atHashString: shipped files only store its JOAAT hash, and a hash
        cannot be turned back into a string. So it reads as 'hash_XXXXXXXX' unless a name
        table happens to contain it.

        Models get away with it because they also have StreamingName, which is always plain
        text. Bounds, lights and the like have no such field, so they fall back to their
        kind. Either way the original cName stays in `name`, nothing is lost.
        """
        if self.name and not self.name.startswith("hash_"):
            return self.name

        return self.extra.get("StreamingName") or self.kind

    def __str__(self) -> str:
        return f"[{self.object_id}] {self.kind} {self.display_name!r}"


@dataclass
class CutEventArgs:
    index: int = -1
    kind: str = ""
    name: str = ""
    object_id: Optional[int] = None
    object_id_list: list[int] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    node: Optional[ET.Element] = None

    def __str__(self) -> str:
        parts = [self.kind]
        if self.name:
            parts.append(repr(self.name))
        if self.object_id is not None:
            parts.append(f"obj={self.object_id}")
        if self.object_id_list:
            parts.append(f"objs={self.object_id_list}")

        return " ".join(parts)


@dataclass
class CutEvent:
    time: float = 0.0
    event_id: int = 0
    object_id: int = -1
    args_ref: Optional[int] = None
    is_child: bool = False
    kind: str = ""
    node: Optional[ET.Element] = None

    def resolve(self, event_args: list[CutEventArgs]) -> Optional[CutEventArgs]:
        if self.args_ref is None or not 0 <= self.args_ref < len(event_args):
            return None

        return event_args[self.args_ref]


TimelineEntry = tuple[float, CutEvent, Optional[CutEventArgs], Optional[CutObject]]


@dataclass
class Cutscene:
    name: str = ""
    name_hash: int = 0
    duration: float = 0.0
    flags: list[int] = field(default_factory=list)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: float = 0.0
    extra_room: str = ""
    extra_room_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fade_in_duration: float = 0.0
    fade_out_duration: float = 0.0

    # Animation is split into time slices; each slice has its own clip dictionary,
    # named "<cutscene>-<slice>.ycd". Slice boundaries, in seconds.
    section_boundaries: list[float] = field(default_factory=list)
    section_duration: float = 0.0
    face_dir: str = ""
    tree: Optional[ET.ElementTree] = None

    objects: list[CutObject] = field(default_factory=list)
    event_args: list[CutEventArgs] = field(default_factory=list)
    load_events: list[CutEvent] = field(default_factory=list)
    events: list[CutEvent] = field(default_factory=list)

    def object_by_id(self, object_id: int) -> Optional[CutObject]:
        for obj in self.objects:
            if obj.object_id == object_id:
                return obj

        return None

    @property
    def section_count(self) -> int:
        return len(self.section_boundaries) + 1

    def section_at(self, time: float) -> int:
        for index, boundary in enumerate(self.section_boundaries):
            if time < boundary:
                return index

        return len(self.section_boundaries)

    @property
    def cameras(self) -> list[CutObject]:
        return [obj for obj in self.objects if obj.is_camera]

    @property
    def actors(self) -> list[CutObject]:
        return [obj for obj in self.objects if obj.is_actor]

    def timeline(self) -> list[TimelineEntry]:
        return [
            (event.time, event, event.resolve(self.event_args), self.object_by_id(event.object_id))
            for event in sorted(self.events, key=lambda e: e.time)
        ]


def parse_object(node: ET.Element) -> CutObject:
    return CutObject(
        object_id=get_value(node.find("iObjectId"), int, -1),
        kind=get_object_kind(node),
        name=get_text(node.find("cName")),
        extra=get_extra_fields(node, COMMON_OBJECT_TAGS),
        node=node,
    )


def parse_event_args(node: ET.Element, index: int) -> CutEventArgs:
    object_id_node = node.find("iObjectId")

    return CutEventArgs(
        index=index,
        kind=get_object_kind(node),
        name=get_text(node.find("cName")),
        object_id=get_value(object_id_node, int, -1) if object_id_node is not None else None,
        object_id_list=get_int_array(node.find("iObjectIdList")),
        extra=get_extra_fields(node, COMMON_ARGS_TAGS),
        node=node,
    )


def get_event_args_ref(node: ET.Element) -> Optional[int]:
    # Events reference their arguments by index into pCutsceneEventArgsList.
    # CodeWalker's PSO XML writes iEventArgsIndex, other exporters write a pEventArgs ref.
    index_node = node.find("iEventArgsIndex")
    if index_node is not None:
        index = get_value(index_node, int, -1)
        return index if index >= 0 else None  # -1 means the event takes no arguments

    args_node = node.find("pEventArgs")
    if args_node is not None:
        raw = (args_node.get("ref") or "").strip()
        if raw and raw != "null":
            try:
                return int(raw)
            except ValueError:
                pass

    return None


def parse_event(node: ET.Element) -> CutEvent:
    return CutEvent(
        time=get_value(node.find("fTime"), float, 0.0),
        event_id=get_value(node.find("iEventId"), int, 0),
        object_id=get_value(node.find("iObjectId"), int, -1),
        args_ref=get_event_args_ref(node),
        is_child=get_value(node.find("IsChild"), bool, False),
        kind=get_object_kind(node),
        node=node,
    )


def parse_item_list(root: ET.Element, tag: str, parse_func) -> list:
    holder = root.find(tag)
    if holder is None:
        return []

    return [parse_func(node) for node in holder.findall("Item")]


def parse(filepath: str) -> Cutscene:
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Identify by contents rather than by root tag name, exporters do not agree on it
    if root.find("pCutsceneObjects") is None:
        raise ValueError(f"'{root.tag}' is not a cutscene file, expected a '{ROOT_TAG}' structure")

    cutscene = Cutscene(
        name=get_text(root.find("cName")),
        name_hash=get_value(root.find("iNameHash"), int, 0),
        duration=get_value(root.find("fTotalDuration"), float, 0.0),
        flags=get_int_array(root.find("iCutsceneFlags")),
        offset=get_vector(root.find("vOffset")),
        rotation=get_value(root.find("fRotation"), float, 0.0),
        extra_room=get_text(root.find("cExtraRoom")),
        extra_room_pos=get_vector(root.find("vExtraRoomPos")),
        fade_in_duration=get_value(root.find("fFadeInGameDuration"), float, 0.0),
        fade_out_duration=get_value(root.find("fFadeOutGameDuration"), float, 0.0),
        section_boundaries=get_float_array(root.find("cameraCutList")),
        section_duration=get_value(root.find("fSectionByTimeSliceDuration"), float, 0.0),
        face_dir=get_text(root.find("cFaceDir")),
        tree=tree,
    )

    cutscene.objects = parse_item_list(root, "pCutsceneObjects", parse_object)
    cutscene.load_events = parse_item_list(root, "pCutsceneLoadEventList", parse_event)
    cutscene.events = parse_item_list(root, "pCutsceneEventList", parse_event)

    holder = root.find("pCutsceneEventArgsList")
    if holder is not None:
        cutscene.event_args = [parse_event_args(node, i) for i, node in enumerate(holder.findall("Item"))]

    return cutscene
