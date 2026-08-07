import math
import os

import bpy

from .. import logger
from ..sollumz_properties import SollumType
from . import cutanim, cutwrite, cutxml


def find_cutscene_obj(context) -> bpy.types.Object:
    obj = context.active_object
    while obj is not None:
        if obj.sollum_type == SollumType.CUTSCENE:
            return obj
        obj = obj.parent

    for obj in context.scene.objects:
        if obj.sollum_type == SollumType.CUTSCENE:
            return obj

    return None


class SOLLUMZ_OT_bind_cutscene_animations(bpy.types.Operator):
    bl_idname = "sollumz.bind_cutscene_animations"
    bl_label = "Bind Cutscene Animations"
    bl_description = ("Bind the cutscene clips to the models now present in the scene, "
                      "without importing the cutscene again")
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None

    def execute(self, context):
        cutscene_obj = find_cutscene_obj(context)

        filepath = cutscene_obj.get("cut_filepath", "")
        if not filepath:
            self.report({"ERROR"}, "This cutscene was imported before rebinding existed, import it again once.")
            return {"CANCELLED"}

        cutscene = cutxml.parse(filepath)
        cutscene.name = cutscene_obj.get("cut_name", cutscene.name)

        report = cutanim.import_cutscene_animations(filepath, cutscene, cutscene_obj)

        total = len(report.animated) + len(report.missing_models)
        logger.info(f"Cutscene '{cutscene.name}': {len(report.animated)} of {total} objects animated.\n"
                    + "\n".join(report.lines()))

        self.report({"INFO"}, f"Animated {len(report.animated)} of {total} objects, see the Sollumz log.")
        return {"FINISHED"}


class SOLLUMZ_OT_export_cutscene(bpy.types.Operator):
    bl_idname = "sollumz.export_cutscene"
    bl_label = "Export Cutscene"
    bl_description = ("Write the scene back into the cutscene file it came from. Only the "
                      "values Sollumz understands are updated, the rest of the file is left "
                      "untouched")
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.cut.pso.xml;*.cut.xml", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None

    def invoke(self, context, event):
        cutscene_obj = find_cutscene_obj(context)
        source = cutscene_obj.get("cut_filepath", "")
        if source:
            directory, name = os.path.split(source)
            self.filepath = os.path.join(directory, name)

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        cutscene_obj = find_cutscene_obj(context)

        source = cutscene_obj.get("cut_filepath", "")
        if not source or not os.path.exists(source):
            self.report({"ERROR"}, "The file this cutscene came from is gone, cannot write it back.")
            return {"CANCELLED"}

        cutscene = cutxml.parse(source)

        cutscene.tree.getroot()  # parsed tree is what gets written, edits go into it
        set_root_placement(cutscene, cutscene_obj)

        by_id = {obj.get("cut_object_id"): obj for obj in cutscene_obj.children_recursive}
        updated = 0

        for cut_obj in cutscene.objects:
            obj = by_id.get(cut_obj.object_id)
            if obj is None:
                continue

            if obj.type == "LIGHT":
                updated += bool(cutwrite.apply_light(cut_obj, obj))
            elif cut_obj.kind in ("HiddenModelObject", "FixupModelObject"):
                updated += bool(cutwrite.apply_sphere(cut_obj, obj, cutscene_obj.matrix_world))

        cutwrite.save(cutscene, self.filepath)

        logger.info(f"Cutscene '{cutscene.name}': wrote {updated} objects to {self.filepath}")
        self.report({"INFO"}, f"Wrote {updated} objects to {os.path.basename(self.filepath)}")
        return {"FINISHED"}


def set_root_placement(cutscene: cutxml.Cutscene, cutscene_obj: bpy.types.Object):
    root = cutscene.tree.getroot()
    cutwrite.set_vector(root, "vOffset", tuple(cutscene_obj.location))
    cutwrite.set_value(root, "fRotation", math.degrees(cutscene_obj.rotation_euler.z))
