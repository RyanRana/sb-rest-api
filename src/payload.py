#!/usr/bin/env python3
"""Read and set the robot's payload mass (kilograms).

Run:
    python src/payload.py                 # just read the current payload
    python src/payload.py --mass 1.5      # tell the robot it carries 1.5 kg
    python src/payload.py --mass 0.0      # clear the payload after a place

Tutorial use case H: set/read payload mass. Read/set only -- no take-control or
unbrake is required, since nothing here commands motion.
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read the robot's payload mass, then set it (kilograms)."
    )
    add_common_args(parser)
    parser.add_argument(
        "--mass",
        dest="mass",
        type=float,
        default=0.0,
        help="Payload mass in kilograms to set on the robot (default: 0.0).",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Tell the robot the mass it carries so motion planning stays accurate --
        # set this after a pick, and clear it (mass=0.0) after a place.

        # Show the payload the robot currently thinks it carries.
        current = sdk.payload.get_payload().ok().mass
        print(f"Current payload: {current} kg")

        # PayloadStateRequest.mass MUST be a float (argparse type=float guarantees it).
        sdk.payload.set_payload(models.PayloadStateRequest(mass=args.mass)).ok()
        print(f"Set payload to: {args.mass} kg")

        # Read it back to confirm the change took effect.
        updated = sdk.payload.get_payload().ok().mass
        print(f"New payload: {updated} kg")


if __name__ == "__main__":
    main()
