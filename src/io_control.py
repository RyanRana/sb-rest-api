#!/usr/bin/env python3
"""Read the robot's I/O state, and optionally write one or more output pins.

Run:
    python src/io_control.py                          # read-only: list all pins
    python src/io_control.py --set pin=value          # write one pin, then re-read
    python src/io_control.py --set a=high --set b=low  # write several pins

Tutorial use case E: read & write I/O. Writing flips PHYSICAL outputs on the
robot, so this script keeps the simulator default -- pass --live only when you
intend to drive real hardware.
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read robot I/O state and optionally write output pins."
    )
    add_common_args(parser)
    parser.add_argument(
        "--set",
        dest="set",
        action="append",
        default=None,
        metavar="pin=value",
        help="Output pin to write as pin=value (repeatable). Use the EXACT pin "
        "key and value string shown by a read-only run first.",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Read first to discover the EXACT pin keys and value strings this robot
        # uses -- never guess them. state is a Dict[str, str] of pin -> value.
        io = sdk.io.status.get_io_state().ok()
        print("Current I/O state:")
        for pin, value in io.state.items():
            print(f"  {pin} = {value}")

        if not args.set:
            return

        # Build a dict of just the pins to change. Writing I/O does not move the
        # arm, so there is no unbrake here. If a write is rejected because the
        # robot is under Routine Editor control, hand control to the API first --
        # see the take-control pattern in move_to_pose.py / the README.
        updates = {}
        for entry in args.set:
            pin, _, value = entry.partition("=")
            updates[pin.strip()] = value.strip()

        print(f"Writing I/O updates: {updates}")
        sdk.io.control.update_io_state(
            models.IOStateUpdateRequest(state=updates)
        ).ok()

        # Re-read to confirm the new values landed.
        io = sdk.io.status.get_io_state().ok()
        print("I/O state after write:")
        for pin, value in io.state.items():
            print(f"  {pin} = {value}")


if __name__ == "__main__":
    main()
