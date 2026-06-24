#!/usr/bin/env python3
"""Trigger a software emergency stop over the REST API.

Run:
    python src/estop.py
    python src/estop.py --reason "watchdog tripped"

Tutorial use case I: software emergency stop.
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Engage a software emergency stop on the robot."
    )
    add_common_args(parser)
    parser.add_argument(
        "--reason",
        type=str,
        default="triggered from estop.py example",
        help="Human-readable reason recorded with the e-stop "
        "(default: 'triggered from estop.py example').",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # This is a SOFTWARE e-stop -- the kind a watchdog or supervising
        # process trips when something looks wrong. It engages brakes and halts
        # motion immediately, so no take-control or unbrake is needed first.
        #
        # It is DISTINCT from the physical e-stop button: that one must still be
        # released by hand at the robot. Recover from this software stop with
        # recover.py (use case F) once the situation is resolved.
        sdk.movement.brakes.engage_emergency_stop(
            models.EngageEmergencyStopRequest(reason=args.reason)
        ).ok()

        print(f"Software emergency stop engaged. Reason: {args.reason}")
        print("Recover with: python src/recover.py")


if __name__ == "__main__":
    main()
