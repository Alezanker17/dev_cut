import bpy

from .. import logger
from ..sollumz_properties import SollumType
from . import cutanim, cutxml


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
