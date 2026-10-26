#!/usr/bin/env python3
"""Grip a part with whatever width gripper is attached, and know whether you're holding it.

Run:
    python src/grip_part.py --width 40.0
    python src/grip_part.py --width 40.0 --squeeze 6.0 --force 30.0

Works with the grippers the API can move to a width: OnRobot 2FG7, 2FG14 and
3FG15, and Schunk EGx.

- OnRobot grippers have a native force grip, so it is used, and the gripper's own
  grip_detected says whether it closed on something.
- A Schunk EGx can only Move to a width. The trick is to command a
  width a few mm INSIDE the part: the jaws stall on it and the command comes back
  refused (a Schunk answers HTTP 500). That refusal is the grip. If the command
  succeeds instead, the jaws reached a width smaller than the part: nothing was
  between them. How hard it clamps grows with --squeeze; it is not a measured force.

Either way it closes in two steps: fast to just outside the part, then the grip.
Closing straight from open hits the part at speed, and the wrist can read that
jolt as a collision and fault the arm.

Widths are in the gripper's own terms (a Schunk EGx width is its jaw stroke, not
the gap between your fingertips), so measure your part in the same terms once.

Tutorial use case D, for any gripper.
"""
import argparse
import sys
import time

from standardbots import models

from _client import add_common_args, build_sdk

K = models.GripperKindEnum
NATIVE_FORCE = (K.Onrobot2Fg7, K.Onrobot2Fg14, K.Onrobot3Fg15)
WIDTH_ONLY = (K.SchunkEgx,)


def mm(value):
    return models.LinearUnit(unit_kind=models.LinearUnitKind.Millimeters, value=float(value))


def command(kind, width_mm, force_n=None):
    """A Move to width_mm, or a native force grip when force_n is given."""
    req = models.GripperCommandRequest(kind=kind)
    force = models.ForceUnit(unit_kind=models.ForceUnitKind.Newtons, value=float(force_n or 0.0))
    inward = models.LinearGripDirectionEnum.Internal
    if kind == K.Onrobot2Fg7:
        req.onrobot_2fg7 = models.OnRobot2FG7GripperCommandRequest(
            control_kind=(models.OnRobot2FG7ControlKindEnum.ForceGrip if force_n
                          else models.OnRobot2FG7ControlKindEnum.Move),
            target_grip_width=mm(width_mm), target_force=force, grip_direction=inward)
    elif kind == K.Onrobot2Fg14:
        req.onrobot_2fg14 = models.OnRobot2FG14GripperCommandRequest(
            control_kind=(models.OnRobot2FG14ControlKindEnum.ForceGrip if force_n
                          else models.OnRobot2FG14ControlKindEnum.Move),
            target_grip_width=mm(width_mm), target_force=force, grip_direction=inward)
    elif kind == K.Onrobot3Fg15:
        req.onrobot_3fg15 = models.OnRobot3FG15GripperCommandRequest(
            control_kind=(models.OnRobot3FG15ControlKindEnum.ForceGrip if force_n
                          else models.OnRobot3FG15ControlKindEnum.Move),
            target_grip_diameter=mm(width_mm), target_force=force, grip_direction=inward)
    elif kind == K.SchunkEgx:
        req.schunk_egx = models.SchunkEGxGripperCommandRequest(
            control_kind=models.SchunkEGxControlKindEnum.Move, target_grip_width=mm(width_mm))
    return req


def send(sdk, req):
    """True when the gripper got there, False when it was stopped (a stall answers non-200)."""
    try:
        return sdk.equipment.control_gripper(req).status == 200
    except Exception:  # some SDK versions raise on the refusal instead of returning it
        return False


def grip_detected(sdk, kind):
    """What the gripper itself reports, where it reports anything."""
    cfg = sdk.equipment.get_gripper_configuration().ok()
    own = {K.Onrobot2Fg7: cfg.onrobot_2fg7, K.Onrobot2Fg14: cfg.onrobot_2fg14,
           K.Onrobot3Fg15: cfg.onrobot_3fg15}.get(kind)
    if own is None:
        return None
    return bool(getattr(own, "force_grip_detected", None) or own.grip_detected)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grip a part with any width gripper and report whether it is held."
    )
    add_common_args(parser)
    parser.add_argument("--width", type=float, required=True,
                        help="The part's width (diameter for a 3FG15) in mm, in the gripper's terms.")
    parser.add_argument("--approach", type=float, default=4.0,
                        help="Close fast to this many mm outside the part first (default: 4.0).")
    parser.add_argument("--squeeze", type=float, default=4.0,
                        help="Width-only grippers: aim this many mm inside the part (default: 4.0).")
    parser.add_argument("--force", type=float, default=20.0,
                        help="Grippers with a native force grip: grip force in N (default: 20.0).")
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        kind = sdk.equipment.get_gripper_configuration().ok().kind
        print(f"Gripper configured: {kind}")
        if kind not in NATIVE_FORCE + WIDTH_ONLY:
            sys.exit(f"{kind} isn't covered here: this example drives OnRobot 2FG7, 2FG14, 3FG15 and Schunk EGx.")

        # Step 1: fast to just outside the part, so the grip can't hit it at speed.
        if not send(sdk, command(kind, args.width + args.approach)):
            sys.exit("Stopped before reaching the part: something is already between the jaws.")
        time.sleep(0.1)

        # Step 2: the grip.
        if kind in NATIVE_FORCE:
            send(sdk, command(kind, args.width, force_n=args.force))
            time.sleep(0.3)  # let the force build before asking
            held = grip_detected(sdk, kind)
        else:
            reached = send(sdk, command(kind, max(0.0, args.width - args.squeeze)))
            held = not reached  # stalled on the part = holding; got there = closed on nothing

        if held:
            print("Holding the part.")
        else:
            sys.exit("Closed on nothing: the jaws got past where the part should be. Open and look again.")


if __name__ == "__main__":
    main()
