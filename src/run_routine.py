#!/usr/bin/env python3
"""List saved routines and optionally play one by id.

Two steps:
    1. List every routine with its id (no arguments):
           python src/run_routine.py
    2. Play one by its id -- copy the id STRING from step 1, not the name:
           python src/run_routine.py --routine-id <id-from-step-1> --live

--routine-id takes the opaque id string (e.g. routine_0b0...), NOT the
human-readable routine name shown in the robot UI. Pass runtime variables with
a separate --var per variable (e.g. --var speed=fast --var count=3); a bare
"key=value" without --var is not accepted.

Tutorial use case C: run a saved routine (built in the robot UI's Routine Editor)
from the REST API, passing in any runtime variables it expects.
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List saved routines, and play one (with optional variables) by id."
    )
    add_common_args(parser)
    parser.add_argument(
        "--routine-id",
        dest="routine_id",
        default=None,
        help="Id of the routine to play -- the id STRING from the listing "
        "(e.g. routine_0b0...), NOT the routine name. Omit to just list "
        "routines and their ids.",
    )
    parser.add_argument(
        "--var",
        dest="var",
        action="append",
        default=None,
        help='Runtime variable as "key=value", with a separate --var for each '
        '(repeatable), e.g. --var speed=fast --var count=3.',
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Running a saved routine does NOT need take-control / unbrake: the
        # routine itself owns brake management while it runs.

        # Always show what routines exist, with their ids, so you know what to
        # pass. The id and the name are DIFFERENT -- --routine-id needs the id.
        listing = sdk.routine_editor.routines.list(limit=100, offset=0).ok()
        print("Saved routines (pass the id to --routine-id, NOT the name):")
        for item in listing.items:
            print(f"  id={item.id}   name={item.name!r}")

        if not args.routine_id:
            print("\nPass --routine-id <id> (the id= value above, not the name) to play one.")
            return

        # Build the variables dict from any --var "key=value" entries.
        variables = {}
        for entry in args.var or []:
            key, _, value = entry.partition("=")
            variables[key.strip()] = value.strip()

        # ALWAYS pass body=PlayRoutineRequest(...): older SDKs misbehaved without
        # an explicit body, even when there are no variables to send.
        print(f"\nPlaying routine {args.routine_id} with variables {variables}")
        sdk.routine_editor.routines.play(
            body=models.PlayRoutineRequest(variables=variables),
            routine_id=args.routine_id,
        ).ok()

        # Read back the live run state.
        st = sdk.routine_editor.routines.get_state(routine_id=args.routine_id).ok()
        print("Routine state:")
        print(f"  is_paused:       {st.is_paused}")
        print(f"  current_step_id: {st.current_step_id}")
        print(f"  cycle_count:     {st.cycle_count}")

        # To control a running routine you can also call:
        #   sdk.routine_editor.routines.pause(routine_id=args.routine_id)
        #   sdk.routine_editor.routines.stop()   # stop takes no routine id
        # Left commented so this example only starts the routine.


if __name__ == "__main__":
    main()
