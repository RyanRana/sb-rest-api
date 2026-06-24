#!/usr/bin/env python3
"""Open or force-grip an OnRobot 2FG7 gripper over the REST API.

Run:
    python src/gripper.py --width 50.0
    python src/gripper.py --width 30.0 --force 40.0

Tutorial use case D: control the gripper.
"""
import argparse

from standardbots import models

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open or force-grip the OnRobot 2FG7 gripper."
    )
    add_common_args(parser)
    parser.add_argument(
        "--width",
        type=float,
        default=50.0,
        help="Target grip width in millimeters (default: 50.0).",
    )
    parser.add_argument(
        "--force",
        type=float,
        default=None,
        help="If set, perform a force grip at this many newtons instead of a "
        "plain position move.",
    )
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # Confirm what is actually attached before commanding it. Driving the
        # gripper does not move the arm, so there is no unbrake here. If a command
        # is rejected because the robot is under Routine Editor control, hand
        # control to the API first -- see the take-control pattern in
        # move_to_pose.py / the README.
        cfg = sdk.equipment.get_gripper_configuration().ok()
        print(f"Gripper configured: {cfg.kind}")
        if cfg.kind == models.GripperKindEnum.NoneConnected:
            print("No gripper is connected -- nothing to command. Exiting.")
            return

        if args.force is None:
            # Position move: open/close to a width, no force control.
            print(f"Moving gripper to {args.width} mm...")
            sdk.equipment.onrobot_2fg7_move(
                value=args.width,
                unit_kind=models.LinearUnitKind.Millimeters,
            ).ok()
        else:
            # Force grip: close inward and hold at the requested force.
            print(f"Force-gripping at {args.width} mm with {args.force} N...")
            sdk.equipment.onrobot_2fg7_grip(
                value=args.width,
                direction=models.LinearGripDirectionEnum.Internal,
                force=args.force,
                force_unit=models.ForceUnitKind.Newtons,
            ).ok()

        print("Gripper command sent.")

        # -- OPTIONAL: generic, gripper-agnostic call -----------------------
        # The convenience helpers above wrap this lower-level API. control_gripper
        # takes a per-gripper command request, so the same entry point works for
        # any supported gripper -- you just fill in the matching sub-request.
        # Note: target_grip_width.value must be a float (50.0, not 50), or the
        # SDK raises TypeError at runtime.
        #
        # sdk.equipment.control_gripper(
        #     models.GripperCommandRequest(
        #         kind=models.GripperKindEnum.Onrobot2Fg7,
        #         onrobot_2fg7=models.OnRobot2FG7GripperCommandRequest(
        #             grip_direction=models.LinearGripDirectionEnum.Internal,
        #             control_kind=models.OnRobot2FG7ControlKindEnum.Move,
        #             target_grip_width=models.LinearUnit(
        #                 unit_kind=models.LinearUnitKind.Millimeters,
        #                 value=50.0,
        #             ),
        #         ),
        #     )
        # ).ok()
        #
        # If a force grip raises here, it almost always means no gripper is
        # configured or powered on the robot -- not a bug in this script.


if __name__ == "__main__":
    main()
