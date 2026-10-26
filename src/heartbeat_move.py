#!/usr/bin/env python3
"""A move that only keeps going while you keep pinging it (a dead-man move).

Run:
    python src/heartbeat_move.py --up 0.05
    python src/heartbeat_move.py --up 0.05 --stop-after 1.0   # stop pinging early: the arm stops

set_arm_position_controlled() starts a move with a heartbeat interval. The robot
runs it only while send_heartbeat() keeps arriving; when pings stop (your script
crashed, the network dropped, or you decided to stop) the robot stops the arm
on its own. That makes it the safe way to feel for contact or creep toward
something: stop pinging the moment a reading looks wrong.

Over the cloud URL a 300 ms interval cancelled moves often in testing, because
pings arrive late. Use a longer interval there (450 ms held up) and ping well
inside it. On the LAN (http://<robot-ip>:3000) 300 ms is fine.
"""
import argparse
import time

from standardbots import models

from _client import add_common_args, build_sdk

TERMINAL = ("success", "failure", "canceled")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move the tooltip straight up only while heartbeats keep arriving."
    )
    add_common_args(parser)
    parser.add_argument("--up", type=float, default=0.05,
                        help="Meters to move straight up along base Z (default: 0.05).")
    parser.add_argument("--interval-ms", type=int, default=450,
                        help="Heartbeat interval in ms; the robot stops if a ping is later "
                        "than this (default: 450, safe over the cloud URL).")
    parser.add_argument("--speed", type=float, default=0.02,
                        help="Max tooltip speed in m/s (default: 0.02, slow on purpose).")
    parser.add_argument("--stop-after", type=float, default=None,
                        help="Stop pinging after this many seconds to watch the robot stop the move.")
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        sdk.status.control.set_configuration_control_state(
            models.RobotControlMode(kind=models.RobotControlModeEnum.Api)
        ).ok()
        sdk.movement.brakes.unbrake().ok()

        start = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        target = models.PositionAndOrientation(
            position=models.Position(
                unit_kind=models.LinearUnitKind.Meters,
                x=start.x, y=start.y, z=start.z + args.up,
            ),
            orientation=models.Orientation(
                kind=models.OrientationKindEnum.Quaternion,
                quaternion=models.Quaternion(x=start.i, y=start.j, z=start.k, w=start.w),
            ),
        )

        move = sdk.movement.position_controlled.set_arm_position_controlled(
            models.ArmPositionUpdateControlledRequest(
                heartbeat_interval=args.interval_ms,
                kind=models.ArmPositionUpdateRequestKindEnum.TooltipPosition,
                tooltip_position=target,
                movement_kind=models.MovementKindEnum.Line,
                speed_profile=models.SpeedProfile(max_tooltip_speed=args.speed),
            )
        ).ok()
        print(f"Move {move.id} started; pinging every {args.interval_ms // 3} ms.")

        # Ping at a third of the interval, so one slow round trip never cancels it.
        began = time.time()
        while True:
            if args.stop_after is not None and time.time() - began >= args.stop_after:
                print(f"Stopped pinging after {args.stop_after} s; the robot stops the move itself.")
                break
            beat = sdk.movement.position_controlled.send_heartbeat(move.id).ok()
            kind = beat.event.kind.value if beat.event and beat.event.kind else None
            if not beat.is_active or kind in TERMINAL:
                print(f"Move ended: {kind or 'inactive'}.")
                break
            time.sleep(args.interval_ms / 3000)

        time.sleep(args.interval_ms / 1000 + 0.5)
        end = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        print(f"Tooltip rose {1000 * (end.z - start.z):.1f} mm of the {1000 * args.up:.0f} mm asked.")


if __name__ == "__main__":
    main()
