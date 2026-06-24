#!/usr/bin/env python3
"""Read live robot state: TCP pose, joint angles, and health.

Run:
    python src/read_state.py            # against the simulator
    python src/read_state.py --live     # against the real robot

Tutorial use case A: read live robot state. Read-only -- no take-control or
unbrake is required, since nothing here commands motion.
"""
import argparse

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(description="Read TCP pose, joints, and health.")
    add_common_args(parser)
    args = parser.parse_args()

    sdk = build_sdk(args)
    with sdk.connection():
        # --- TCP (tooltip) pose ---------------------------------------------
        # The pose retrieval API returns orientation as i, j, k, w. That is the
        # SAME quaternion you would WRITE as x, y, z, w -- the read side just
        # labels the vector part i/j/k. To send this pose back to the robot you
        # map i->x, j->y, k->z, w->w into models.Quaternion(...).
        pose = sdk.poses.pose_retrieval.get_tooltip_position().ok().pose
        print("TCP pose (meters):")
        print(f"  x={pose.x}  y={pose.y}  z={pose.z}")
        print("TCP orientation (read as i,j,k,w; write as x,y,z,w):")
        print(f"  i={pose.i}  j={pose.j}  k={pose.k}  w={pose.w}")

        # --- Joint angles ----------------------------------------------------
        joints = sdk.poses.pose_retrieval.get_joints_position().ok().pose
        print("Joint angles (radians):")
        print(
            f"  j0={joints.j0}  j1={joints.j1}  j2={joints.j2}  "
            f"j3={joints.j3}  j4={joints.j4}  j5={joints.j5}"
        )

        # --- Health ----------------------------------------------------------
        health = sdk.status.health.get_health().ok().health
        print(f"Health: {health}")

        # --- One-call combined view -----------------------------------------
        # get_arm_position() returns joints and tooltip together in a single
        # call -- handy when you want both without two round trips.
        combined = sdk.movement.position.get_arm_position().ok()
        print("Combined arm position (one call):")
        print(f"  joint_rotations: {combined.joint_rotations}")
        tip = combined.tooltip_position.position
        print(f"  tooltip x={tip.x}  y={tip.y}  z={tip.z}")


if __name__ == "__main__":
    main()
