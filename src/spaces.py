#!/usr/bin/env python3
"""List the robot's saved global Spaces and how many positions each holds.

Run:
    python src/spaces.py            # against the simulator
    python src/spaces.py --live     # against the real robot

Tutorial use case G: saved Spaces / waypoints. Read-only -- no take-control or
unbrake is required, since nothing here commands motion.
"""
import argparse

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List saved global Spaces and their saved-position counts."
    )
    add_common_args(parser)
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Global Spaces are named, reusable coordinate sets saved on the robot
        # (waypoints, fixtures, pick/place locations) that any routine can use.
        spaces = sdk.space.list_global_spaces().ok()

        if not spaces.items:
            print("No global Spaces found.")
            return

        print(f"Found {len(spaces.items)} global Space(s):")
        for s in spaces.items:
            # A Space carries its saved coordinates in s.positions, a list of
            # opaque PositionMap entries. We only report the count and ids here;
            # do NOT assume the inner field names of a PositionMap entry.
            position_count = len(s.positions) if s.positions else 0
            print(
                f"  id={s.id}  name={s.name!r}  "
                f"is_global={s.is_global}  positions={position_count}"
            )

        # USING A SPACE: the saved coordinates in s.positions describe waypoints
        # you can drive to. Feed one into a Cartesian move (move_tooltip, see
        # move_to_pose.py) or a joint move (set_arm_position) to visit it, or run
        # a routine that already references the Space by name.
        #
        # ROUTINE-SCOPED SPACES: Spaces defined inside a specific routine (rather
        # than globally) are listed per routine. Set exclude_global_spaces=True to
        # see only the routine's own Spaces:
        #   sdk.routine_editor.routines.list_spaces(
        #       routine_id="<routine-id>", exclude_global_spaces=True
        #   ).ok()


if __name__ == "__main__":
    main()
