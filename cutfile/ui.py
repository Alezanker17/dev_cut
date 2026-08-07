import bpy

from ..sollumz_properties import SollumType
from . import cutxml
from .operators import find_cutscene_obj

SECTION_ICON = "SEQUENCE"


def get_cutscenes(context) -> list[bpy.types.Object]:
    return [obj for obj in context.scene.objects if obj.sollum_type == SollumType.CUTSCENE]


def draw_missing(layout: bpy.types.UILayout, names: list[str]):
    column = layout.column(align=True)
    column.label(text="Missing models:", icon="ERROR")
    for name in sorted(set(names))[:6]:
        column.label(text=name, icon="DOT")

    if len(set(names)) > 6:
        column.label(text=f"...and {len(set(names)) - 6} more", icon="DOT")


class SOLLUMZ_PT_CUTSCENE_TOOL_PANEL(bpy.types.Panel):
    bl_label = "Cutscenes"
    bl_idname = "SOLLUMZ_PT_CUTSCENE_TOOL_PANEL"
    bl_category = "Sollumz Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 5

    def draw_header(self, context):
        self.layout.label(text="", icon="CAMERA_DATA")

    def draw(self, context):
        layout = self.layout
        cutscenes = get_cutscenes(context)

        if not cutscenes:
            column = layout.column(align=True)
            column.label(text="No cutscene in the scene.", icon="INFO")
            column.operator("sollumz.import_assets", text="Import a .cut", icon="IMPORT")
            return

        cutscene_obj = find_cutscene_obj(context) or cutscenes[0]

        box = layout.box()
        row = box.row()
        row.label(text=cutscene_obj.get("cut_name", cutscene_obj.name), icon="CAMERA_DATA")
        if len(cutscenes) > 1:
            row.label(text=f"1 of {len(cutscenes)}")

        duration = cutscene_obj.get("cut_duration", 0.0)
        fps = context.scene.render.fps or 30
        column = box.column(align=True)
        column.label(text=f"{duration:.1f} s  ({round(duration * fps)} frames)", icon="TIME")

        actors = [o for o in cutscene_obj.children_recursive
                  if o.sollum_type == SollumType.CUTSCENE_ACTOR]
        bound = sum(1 for a in actors if any(c.type == "ARMATURE" for c in a.children))
        column.label(text=f"{bound} of {len(actors)} actors bound", icon="OUTLINER_OB_ARMATURE")


class CutsceneToolChildPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = SOLLUMZ_PT_CUTSCENE_TOOL_PANEL.bl_idname
    bl_category = SOLLUMZ_PT_CUTSCENE_TOOL_PANEL.bl_category

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None


class SOLLUMZ_PT_CUTSCENE_ACTORS_PANEL(CutsceneToolChildPanel, bpy.types.Panel):
    bl_label = "Actors"
    bl_idname = "SOLLUMZ_PT_CUTSCENE_ACTORS_PANEL"
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(text="", icon="OUTLINER_OB_ARMATURE")

    def draw(self, context):
        layout = self.layout
        cutscene_obj = find_cutscene_obj(context)

        actors = [o for o in cutscene_obj.children_recursive
                  if o.sollum_type == SollumType.CUTSCENE_ACTOR]

        missing = [a.get("cut_StreamingName", a.name) for a in actors
                   if not any(c.type == "ARMATURE" for c in a.children)]

        if missing:
            draw_missing(layout, missing)
            layout.separator()

        layout.operator("sollumz.bind_cutscene_animations", icon="LINKED")


class SOLLUMZ_PT_CUTSCENE_ANIMATION_PANEL(CutsceneToolChildPanel, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "SOLLUMZ_PT_CUTSCENE_ANIMATION_PANEL"
    bl_order = 1

    def draw_header(self, context):
        self.layout.label(text="", icon=SECTION_ICON)

    def draw(self, context):
        layout = self.layout
        cutscene_obj = find_cutscene_obj(context)

        dictionaries = [o for o in context.scene.objects
                        if o.sollum_type == SollumType.CLIP_DICTIONARY
                        and o.name.startswith(cutscene_obj.get("cut_name", ""))]

        column = layout.column(align=True)
        column.label(text=f"{len(dictionaries)} clip dictionaries", icon=SECTION_ICON)

        layout.operator("sollumz.build_cutscene_animations", icon="FILE_REFRESH")

        row = layout.row()
        row.enabled = bool(dictionaries)
        row.operator("sollumz.export_assets", text="Export .ycd", icon="EXPORT")


class SOLLUMZ_PT_CUTSCENE_FILE_PANEL(CutsceneToolChildPanel, bpy.types.Panel):
    bl_label = "File"
    bl_idname = "SOLLUMZ_PT_CUTSCENE_FILE_PANEL"
    bl_order = 2

    def draw_header(self, context):
        self.layout.label(text="", icon="FILE_BLANK")

    def draw(self, context):
        layout = self.layout
        cutscene_obj = find_cutscene_obj(context)

        source = cutscene_obj.get("cut_filepath", "")
        column = layout.column(align=True)
        if source:
            column.label(text=bpy.path.basename(source), icon="FILE_BLANK")
        else:
            column.label(text="Imported before this was tracked", icon="ERROR")

        layout.operator("sollumz.export_cutscene", icon="EXPORT")
