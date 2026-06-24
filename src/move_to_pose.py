#!/usr/bin/env python3
"""Move the tooltip straight up by a small amount, keeping its orientation.

Run:
    python src/move_to_pose.py --up 0.05

Tutorial use case B: move the arm (Cartesian tooltip move).
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move the tooltip straight up by a small amount."
    )
    add_common_args(parser)
    parser.add_argument(
        "--up",
        dest="up",
        type=float,
        default=0.05,
        help="Meters to move straight up along base Z (default: 0.05).",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Moving the arm requires API control + released brakes.
        sdk.status.control.set_configuration_control_state(
            models.RobotControlMode(kind=models.RobotControlModeEnum.Api)
        ).ok()
        sdk.movement.brakes.unbrake().ok()

        # Read the current TCP pose. Orientation comes back as i, j, k, w.
        before = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        print(
            f"Before: x={before.x} y={before.y} z={before.z} "
            f"i={before.i} j={before.j} k={before.k} w={before.w}"
        )

        # Move to the same x, y at z + up, holding the current orientation.
        # The pose reads orientation as i/j/k/w; map i->x, j->y, k->z, w->w.
        sdk.movement.position.move_tooltip(
            position=models.Position(
                unit_kind=models.LinearUnitKind.Meters,
                x=before.x,
                y=before.y,
                z=before.z + args.up,
            ),
            orientation=models.Orientation(
                kind=models.OrientationKindEnum.Quaternion,
                quaternion=models.Quaternion(
                    x=before.i,
                    y=before.j,
                    z=before.k,
                    w=before.w,
                ),
            ),
            movement_kind=models.MovementKindEnum.Line,
            speed_profile=models.SpeedProfile(max_tooltip_speed=0.25),  # cap speed; start slow
        ).ok()

        # Confirm where we ended up.
        after = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        print(
            f"After:  x={after.x} y={after.y} z={after.z} "
            f"i={after.i} j={after.j} k={after.k} w={after.w}"
        )

        # OPTIONAL: joint-space move to an absolute target. Joint angles are in
        # radians; always check the robot's joint limits before sending absolute
        # targets, since this moves every joint at once.
        # sdk.movement.position.set_arm_position(
        #     models.ArmPositionUpdateRequest(
        #         kind=models.ArmPositionUpdateRequestKindEnum.JointRotation,
        #         joint_rotation=models.ArmJointRotations(
        #             joints=(0.0, -1.2, 1.2, 0.0, 1.57, 0.0)
        #         ),
        #         movement_kind=models.MovementKindEnum.Joint,
        #     )
        # ).ok()


if __name__ == "__main__":
    main()
