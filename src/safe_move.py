#!/usr/bin/env python3
"""Move the tooltip up, without hanging on a fault and without trusting "success".

Run:
    python src/safe_move.py --up 0.05
    python src/safe_move.py --up 0.05 --tolerance-mm 1.0

Tutorial use case B, made safe for unattended scripts. Two things a plain
move_tooltip(...).ok() does not cover:

1. The SDK's HTTP client has no timeout. A move that faults mid-motion (a
   collision, a protective stop) can leave the call waiting forever. So the move
   runs on a background thread while a SECOND client polls the fault status, and
   the script stops waiting as soon as the arm has been in Failure for a moment.
2. A move can come back 200 with kind "success" and still not have arrived, and a
   fault can surface a second or two after the call returns. So after the call,
   the script re-checks the status and measures where the tooltip really is.
"""
import argparse
import math
import sys
import threading
import time

from standardbots import models

from _client import add_common_args, build_sdk


def fault_of(sdk):
    """The active fault reason, or None. One call, safe to poll while a move is out."""
    state = sdk.recovery.recover.get_status().ok()
    if state.failed or (state.status and state.status.value == "Failure"):
        return (state.failure.reason if state.failure else None) or "Failure (no reason given)"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move the tooltip straight up, watching for faults and checking arrival."
    )
    add_common_args(parser)
    parser.add_argument("--up", type=float, default=0.05,
                        help="Meters to move straight up along base Z (default: 0.05).")
    parser.add_argument("--tolerance-mm", type=float, default=2.0,
                        help="How far from the target still counts as arrived (default: 2.0).")
    parser.add_argument("--max-seconds", type=float, default=60.0,
                        help="Give up waiting on the move after this long (default: 60).")
    args = parser.parse_args()

    sdk = build_sdk(args)
    # A separate client for status reads, so polling never waits behind the move
    # request on the same connection.
    watcher = build_sdk(args)
    with sdk.connection(), watcher.connection():
        sdk.status.control.set_configuration_control_state(
            models.RobotControlMode(kind=models.RobotControlModeEnum.Api)
        ).ok()
        sdk.movement.brakes.unbrake().ok()

        # Never send a move to a faulted arm: that is the call most likely to hang.
        fault = fault_of(watcher)
        if fault:
            sys.exit(f"Robot is faulted ({fault}). Clear it first: python src/recover.py --recover")

        start = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        target = (start.x, start.y, start.z + args.up)

        result = {}

        def send_move():
            try:
                result["response"] = sdk.movement.position.move_tooltip(
                    position=models.Position(
                        unit_kind=models.LinearUnitKind.Meters,
                        x=target[0], y=target[1], z=target[2],
                    ),
                    orientation=models.Orientation(
                        kind=models.OrientationKindEnum.Quaternion,
                        quaternion=models.Quaternion(x=start.i, y=start.j, z=start.k, w=start.w),
                    ),
                    movement_kind=models.MovementKindEnum.Line,
                    speed_profile=models.SpeedProfile(max_tooltip_speed=0.1),
                )
            except Exception as exc:  # handed to the main thread below
                result["error"] = exc

        # daemon=True: if the call never returns, the script can still exit.
        mover = threading.Thread(target=send_move, daemon=True)
        mover.start()

        began, red_since = time.time(), None
        while mover.is_alive():
            mover.join(0.25)
            if not mover.is_alive():
                break
            fault = fault_of(watcher)
            if fault:
                red_since = red_since or time.time()
                # Red for half a second with the call still out: it is not coming back.
                if time.time() - red_since >= 0.5:
                    sys.exit(f"Move faulted ({fault}). Recover with: python src/recover.py --recover")
            else:
                red_since = None
            if time.time() - began > args.max_seconds:
                sys.exit(f"The move did not answer within {args.max_seconds:.0f} s.")

        if "error" in result:
            raise result["error"]
        response = result["response"]
        kind = response.data.kind.value if response.status == 200 and response.data else None
        if kind != "success":
            sys.exit(f"Move refused (HTTP {response.status}): {response.data}")

        # A fault can arrive just after the call returns: give it a moment to show.
        settle_until = time.time() + 2.0
        while time.time() < settle_until:
            fault = fault_of(watcher)
            if fault:
                sys.exit(f"Move answered success, then faulted ({fault}).")
            time.sleep(0.25)

        end = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        off_mm = 1000 * math.dist((end.x, end.y, end.z), target)
        if off_mm > args.tolerance_mm:
            sys.exit(f"Move answered success but stopped {off_mm:.1f} mm from the target.")
        print(f"Arrived: {off_mm:.1f} mm from the target, no fault.")


if __name__ == "__main__":
    main()
