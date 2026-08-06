"""Standalone check for the cutscene parser. Does not require Blender.

    python test_cutxml.py <file.cut.pso.xml>

Cutscene files can be exported with CodeWalker's RPF Explorer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cutxml  # noqa: E402


def print_summary(cutscene: cutxml.Cutscene):
    kinds = {}
    for obj in cutscene.objects:
        kinds[obj.kind] = kinds.get(obj.kind, 0) + 1

    print(f"cutscene: {cutscene.name or '(unnamed)'}")
    print(f"  duration     : {cutscene.duration:.2f} s")
    print(f"  name hash    : {cutscene.name_hash}")
    print(f"  objects      : {len(cutscene.objects)} "
          f"({len(cutscene.cameras)} cameras, {len(cutscene.actors)} actors)")
    print(f"  event args   : {len(cutscene.event_args)}")
    print(f"  load events  : {len(cutscene.load_events)}")
    print(f"  events       : {len(cutscene.events)}")
    print("  kinds        : " + ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items())))


def print_timeline(cutscene: cutxml.Cutscene, limit: int = 15):
    entries = cutscene.timeline()

    for time, event, args, cut_obj in entries[:limit]:
        who = cut_obj.name if cut_obj else f"id {event.object_id}"
        what = str(args) if args else "(no args)"
        print(f"  {time:7.2f}s  ev {event.event_id:<3} {who:<28}  {what}")

    if len(entries) > limit:
        print(f"  ... {len(entries) - limit} more")


def check_consistency(cutscene: cutxml.Cutscene) -> list[str]:
    problems = []

    ids = [obj.object_id for obj in cutscene.objects]
    if len(ids) != len(set(ids)):
        problems.append("duplicate object ids")

    for event in cutscene.events + cutscene.load_events:
        if event.args_ref is not None and event.args_ref >= len(cutscene.event_args):
            problems.append(f"event args ref {event.args_ref} out of range")
        if event.object_id >= 0 and cutscene.object_by_id(event.object_id) is None:
            problems.append(f"event references unknown object id {event.object_id}")

    return sorted(set(problems))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 1

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"not found: {filepath}")
        return 1

    cutscene = cutxml.parse(filepath)

    print_summary(cutscene)
    print()

    print("--- objects ---")
    for obj in cutscene.objects:
        extra = ("   " + ", ".join(f"{k}={v}" for k, v in obj.extra.items())) if obj.extra else ""
        print(f"  {obj}{extra}")
    print()

    print("--- timeline ---")
    print_timeline(cutscene)
    print()

    entries = cutscene.timeline()
    resolved = sum(1 for _, _, args, _ in entries if args is not None)
    print(f"resolved event args: {resolved}/{len(entries)}")

    problems = check_consistency(cutscene)
    if problems:
        print()
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("no inconsistencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
