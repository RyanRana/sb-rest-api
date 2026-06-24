#!/usr/bin/env python3
"""Inspect a robot fault / e-stop and optionally attempt recovery.

Run:
    python src/recover.py            # read-only: just report the fault state
    python src/recover.py --recover  # also attempt to clear a recoverable fault

Tutorial use case F: recover from a fault / e-stop. Reading the recovery status
is read-only -- no take-control or unbrake is required.
"""
import argparse

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report the robot fault state and optionally attempt recovery."
    )
    add_common_args(parser)
    parser.add_argument(
        "--recover",
        dest="recover",
        action="store_true",
        help="Actually attempt recovery. Omit to only report the fault state "
        "(read-only).",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Reading recovery status never moves the robot, so no control/unbrake.
        state = sdk.recovery.recover.get_status().ok()
        print(f"Status: {state.status}")
        print(f"Failed: {state.failed}")

        # When there is an active failure, the failure object explains what it
        # is and -- crucially -- what kind of recovery it needs.
        if state.failure:
            print("Failure details:")
            print(f"  kind:          {state.failure.kind}")
            print(f"  reason:        {state.failure.reason}")
            print(f"  recovery_type: {state.failure.recovery_type}")

        if state.failed and args.recover:
            # Not every fault clears from software -- recovery_type tells you
            # what is actually needed. A physical e-stop, for example, must be
            # released by hand before recover() can succeed.
            print("\nAttempting recovery...")
            sdk.recovery.recover.recover().ok()

            after = sdk.recovery.recover.get_status().ok()
            print(f"Status after recovery: {after.status}")
            print(f"Failed after recovery: {after.failed}")
        elif state.failed:
            print("\nFault present. Re-run with --recover to attempt to clear it.")


if __name__ == "__main__":
    main()
