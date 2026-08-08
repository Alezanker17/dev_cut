import math
import os
import shutil

import bpy

from .. import logger
from ..sollumz_properties import SollumType
from . import cutanim, cutbuild, cutimport, cutnew, cutwrite, cutxml

CUT_SUFFIX = ".cut.pso.xml"


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


def find_actor_obj(context) -> bpy.types.Object:
    obj = context.active_object
    while obj is not None:
        if obj.sollum_type == SollumType.CUTSCENE_ACTOR:
            return obj
        obj = obj.parent

    return None


class SOLLUMZ_OT_new_cutscene(bpy.types.Operator):
    bl_idname = "sollumz.new_cutscene"
    bl_label = "New Cutscene"
    bl_description = ("Start a cutscene of your own from an existing one. The file is copied "
                      "under the new name and imported, so editing and exporting never touch "
                      "the original")
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        name="Start From",
        items=(
            ("SCRATCH", "Nothing", "Write a new cutscene: a camera, and what starts and stops "
                                   "it. Add the cast yourself"),
            ("BASE", "An Existing Cutscene", "Copy a cutscene that already works, cast and "
                                             "events included, and edit it"),
        ),
        default="SCRATCH",
    )
    duration: bpy.props.FloatProperty(name="Seconds", min=0.1, default=10.0)
    base: bpy.props.StringProperty(
        name="Based On",
        description="The .cut file to copy. Pick one built like the cutscene you want",
        subtype="FILE_PATH",
    )
    directory: bpy.props.StringProperty(
        name="Folder",
        description="Where the new cutscene is written",
        subtype="DIR_PATH",
    )
    name: bpy.props.StringProperty(
        name="Name",
        description="Name of the new cutscene. The .cut and its .ycd files all carry it",
        default="my_cutscene",
    )

    def invoke(self, context, event):
        if not self.directory:
            self.directory = os.path.dirname(bpy.data.filepath) or self.directory

        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "mode")
        if self.mode == "BASE":
            layout.prop(self, "base")
        else:
            layout.prop(self, "duration")
        layout.prop(self, "directory")
        layout.prop(self, "name")

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({"ERROR"}, "Give the cutscene a name.")
            return {"CANCELLED"}

        base = bpy.path.abspath(self.base) if self.mode == "BASE" else ""
        if self.mode == "BASE" and not os.path.isfile(base):
            self.report({"ERROR"}, "Pick an existing .cut file to base this one on.")
            return {"CANCELLED"}

        directory = bpy.path.abspath(self.directory) or os.path.dirname(base)
        if not directory:
            self.report({"ERROR"}, "Pick a folder to write the cutscene into.")
            return {"CANCELLED"}

        filepath = os.path.join(directory, name + CUT_SUFFIX)
        if os.path.exists(filepath):
            self.report({"ERROR"}, f"'{os.path.basename(filepath)}' already exists, pick another name.")
            return {"CANCELLED"}

        os.makedirs(directory, exist_ok=True)

        if self.mode == "BASE":
            try:
                cutxml.parse(base)
            except Exception as exc:
                self.report({"ERROR"}, f"'{os.path.basename(base)}' could not be read: {exc}")
                return {"CANCELLED"}

            shutil.copyfile(base, filepath)
            source = os.path.basename(base)
        else:
            cutnew.create(filepath, duration=self.duration)
            source = "nothing"

        # no animations under this name yet, so the actors come in as placeholders to bind later
        cutscene_obj, cutscene, _ = cutimport.import_cutscene(filepath, import_animations=False)
        cutscene_obj.name = name
        cutscene_obj["cut_name"] = name

        logger.info(f"New cutscene '{name}' from {source}: {len(cutscene.objects)} objects, "
                    f"{cutscene.duration:.2f}s, {cutscene.section_count} sections at {filepath}")
        self.report({"INFO"}, f"Created '{name}' from {source}, "
                              f"{len(cutscene.objects)} objects.")
        return {"FINISHED"}


class SOLLUMZ_OT_cutscene_set_duration(bpy.types.Operator):
    bl_idname = "sollumz.cutscene_set_duration"
    bl_label = "Set Duration"
    bl_description = ("Change how long the cutscene runs. Events sitting at the old end move "
                      "with it, so what stops and unloads keeps doing it")
    bl_options = {"REGISTER", "UNDO"}

    duration: bpy.props.FloatProperty(name="Seconds", min=0.1, default=10.0)

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None

    def invoke(self, context, event):
        self.duration = float(find_cutscene_obj(context).get("cut_duration", 10.0)) or 10.0
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        cutscene_obj = find_cutscene_obj(context)
        cutscene_obj["cut_duration"] = self.duration

        fps = context.scene.render.fps or 30
        context.scene.frame_start = 0
        context.scene.frame_end = max(1, round(self.duration * fps))

        self.report({"INFO"}, f"Duration set to {self.duration:.2f}s, export to write it.")
        return {"FINISHED"}


class SOLLUMZ_OT_cutscene_set_model(bpy.types.Operator):
    bl_idname = "sollumz.cutscene_set_model"
    bl_label = "Set Model"
    bl_description = ("Point the selected actor at a different model. Only StreamingName "
                      "changes: cName is a hash the game never reads back as text")
    bl_options = {"REGISTER", "UNDO"}

    model: bpy.props.StringProperty(name="Model", description="Streaming name, e.g. player_zero")

    @classmethod
    def poll(cls, context):
        return find_actor_obj(context) is not None

    def invoke(self, context, event):
        self.model = find_actor_obj(context).get("cut_StreamingName", "")
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        actor = find_actor_obj(context)
        model = self.model.strip()
        if not model:
            self.report({"ERROR"}, "Give the actor a model name.")
            return {"CANCELLED"}

        actor["cut_StreamingName"] = model
        actor.name = f"{actor.get('cut_object_id', -1)} {model}"

        self.report({"INFO"}, f"Actor set to '{model}', bind and export to apply it.")
        return {"FINISHED"}


class SOLLUMZ_OT_cutscene_add_actor(bpy.types.Operator):
    bl_idname = "sollumz.cutscene_add_actor"
    bl_label = "Add Actor"
    bl_description = ("Add an actor modelled on the selected one. It is written into the file "
                      "on export, along with copies of the events that drive it")
    bl_options = {"REGISTER", "UNDO"}

    model: bpy.props.StringProperty(name="Model", description="Streaming name, e.g. player_zero")

    @classmethod
    def poll(cls, context):
        return find_actor_obj(context) is not None

    def invoke(self, context, event):
        self.model = find_actor_obj(context).get("cut_StreamingName", "")
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        template = find_actor_obj(context)
        model = self.model.strip()
        if not model:
            self.report({"ERROR"}, "Give the actor a model name.")
            return {"CANCELLED"}

        template_id = template.get("cut_object_id", -1)
        if template_id < 0:
            self.report({"ERROR"}, "The selected actor is not in the file yet, export first.")
            return {"CANCELLED"}

        actor = cutimport.create_empty(f"new {model}", template.empty_display_type,
                                       template.empty_display_size)
        actor.sollum_type = SollumType.CUTSCENE_ACTOR
        actor.parent = template.parent
        actor.location = template.location
        # no id until the export gives it one, the template says what to copy meanwhile
        actor["cut_object_id"] = -1
        actor["cut_clone_of"] = template_id
        actor["cut_object_kind"] = template.get("cut_object_kind", "PedModelObject")
        actor["cut_StreamingName"] = model
        context.collection.objects.link(actor)

        self.report({"INFO"}, f"Added '{model}' from object {template_id}, export to write it.")
        return {"FINISHED"}


class SOLLUMZ_OT_cutscene_validate(bpy.types.Operator):
    bl_idname = "sollumz.cutscene_validate"
    bl_label = "Validate"
    bl_description = "Check that the cutscene file on disk still holds together"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None

    def execute(self, context):
        filepath = find_cutscene_obj(context).get("cut_filepath", "")
        if not filepath or not os.path.exists(filepath):
            self.report({"ERROR"}, "The file this cutscene came from is gone.")
            return {"CANCELLED"}

        problems = cutwrite.validate(cutxml.parse(filepath))
        if problems:
            logger.warning(f"'{os.path.basename(filepath)}':\n" + "\n".join(problems))
            self.report({"WARNING"}, f"{len(problems)} problems, see the Sollumz log.")
        else:
            self.report({"INFO"}, "The cutscene is coherent.")

        return {"FINISHED"}


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

        duration = float(cutscene_obj.get("cut_duration", 0.0) or 0.0)
        if duration > 0.0:
            cutwrite.set_duration(cutscene, duration)

        # first, they take their ids here and everything below works by id
        added = export_new_objects(cutscene, cutscene_obj)

        by_id = {obj.get("cut_object_id"): obj for obj in cutscene_obj.children_recursive}
        updated = 0

        for cut_obj in cutscene.objects:
            obj = by_id.get(cut_obj.object_id)
            if obj is None:
                continue

            model = obj.get("cut_StreamingName", "")
            if model and model != cut_obj.extra.get("StreamingName", ""):
                updated += bool(cutwrite.set_model(cut_obj, model))

            if obj.type == "LIGHT":
                updated += bool(cutwrite.apply_light(cut_obj, obj))
            elif cut_obj.kind in ("HiddenModelObject", "FixupModelObject"):
                updated += bool(cutwrite.apply_sphere(cut_obj, obj, cutscene_obj.matrix_world))

        # check before saving, the game crashes on an incoherent .cut
        problems = cutwrite.validate(cutscene)
        if problems:
            logger.error(f"Cutscene '{cutscene.name}' was not written:\n" + "\n".join(problems))
            self.report({"ERROR"}, f"{problems[0]} ({len(problems)} problems, see the Sollumz log.)")
            return {"CANCELLED"}

        cutwrite.save(cutscene, self.filepath)
        # the ids we just handed out belong to this file, follow it if it moved
        cutscene_obj["cut_filepath"] = self.filepath

        logger.info(f"Cutscene '{cutscene.name}': wrote {updated} objects, added {added}, "
                    f"to {self.filepath}")
        self.report({"INFO"}, f"Wrote {updated} objects and added {added} to "
                              f"{os.path.basename(self.filepath)}")
        return {"FINISHED"}


class SOLLUMZ_OT_build_cutscene_animations(bpy.types.Operator):
    bl_idname = "sollumz.build_cutscene_animations"
    bl_label = "Build Cutscene Animations"
    bl_description = ("Collect the animations of the models bound to this cutscene into clip "
                      "dictionaries named the way the cutscene looks them up. Export those "
                      "with Sollumz to get the .ycd files")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return find_cutscene_obj(context) is not None

    def execute(self, context):
        cutscene_obj = find_cutscene_obj(context)

        filepath = cutscene_obj.get("cut_filepath", "")
        if not filepath or not os.path.exists(filepath):
            self.report({"ERROR"}, "The file this cutscene came from is gone.")
            return {"CANCELLED"}

        cutscene = cutxml.parse(filepath)
        cutscene.name = cutscene_obj.get("cut_name", cutscene.name)

        # A placeholder's bound model is its child, that is where the animation lives
        sources = {}
        for obj in cutscene_obj.children_recursive:
            object_id = obj.get("cut_object_id")
            if object_id is None:
                continue

            if obj.type == "CAMERA":
                sources[object_id] = obj
            else:
                for child in obj.children:
                    if child.type == "ARMATURE":
                        sources[object_id] = child
                        break

        dictionaries, skipped = cutbuild.build_clip_dictionaries(cutscene, sources)

        lines = [f"Cutscene '{cutscene.name}': built {len(dictionaries)} clip "
                 f"{'dictionary' if len(dictionaries) == 1 else 'dictionaries'}."]
        if skipped:
            lines.append("Nothing to export for: " + ", ".join(sorted(set(skipped))))
        lines.append("Select them and use Sollumz export to write the .ycd files.")

        logger.info("\n".join(lines))
        self.report({"INFO"}, lines[0])
        return {"FINISHED"}


def set_root_placement(cutscene: cutxml.Cutscene, cutscene_obj: bpy.types.Object):
    root = cutscene.tree.getroot()
    cutwrite.set_vector(root, "vOffset", tuple(cutscene_obj.location))
    cutwrite.set_value(root, "fRotation", math.degrees(cutscene_obj.rotation_euler.z))


def export_new_objects(cutscene: cutxml.Cutscene, cutscene_obj: bpy.types.Object) -> int:
    """Write the actors added in Blender into the file.

    They keep the id they get back, so a second export updates them instead of adding again.
    """
    added = 0

    for obj in cutscene_obj.children_recursive:
        if obj.get("cut_object_id", -1) >= 0:
            continue

        source = cutscene.object_by_id(obj.get("cut_clone_of", -1))
        if source is None:
            continue

        clone = cutwrite.clone_actor(cutscene, source, obj.get("cut_StreamingName", ""))
        if clone is None:
            logger.warning(f"'{obj.name}' could not be added, object {source.object_id} "
                           "has nothing to copy from.")
            continue

        obj["cut_object_id"] = clone.object_id
        obj.name = f"{clone.object_id} {clone.display_name}"
        added += 1

    return added
