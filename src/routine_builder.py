#!/usr/bin/env python3
"""Build a routine document that the robot's `routines` service accepts.

REST cannot author routines -- `GET /routine-editor/routines/{id}` returns only
id and name. The Feathers socket can (see spaces_ws.py), so a solver can emit a
routine and let the controller's ROS2 motion planner own every path, instead of
streaming `move_tooltip` poses that bypass it.

    from routine_builder import build, loop, move_arm, waypoint, from_taught

    doc = build("Packed order 41", [
        loop([move_arm([
            waypoint("Pick",  pick_pose,  pick_joints),
            waypoint("Apex",  apex_pose,  apex_joints),
            waypoint("Place", place_pose, place_joints),
        ])])
    ])
    client.create_routine(doc)

A routine stores `steps` as a tree of ids and `stepConfigurations` as a map from
id to arguments; `build` produces both from one nested structure.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

Pose = dict          # {x, y, z, i, j, k, w}
JointAngles = list


@dataclass
class Node:
    """One step: its kind, its args, and the steps nested under it."""

    step_kind: str
    args: dict
    description: str = ""
    children: list["Node"] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


def pose(x: float, y: float, z: float,
         quat_ijkw: tuple = (0.0, 1.0, 0.0, 0.0)) -> Pose:
    """A space pose. Position in metres; orientation as i, j, k, w."""
    i, j, k, w = quat_ijkw
    return {"x": x, "y": y, "z": z, "i": i, "j": j, "k": k, "w": w}


def waypoint(description: str, target_pose: Pose, joint_angles: JointAngles,
             *, motion: str = "joint", stop_here: bool = True,
             blend_radius: float = 0.0, match_joint_angles: bool = True,
             tcp: str = "wrist", pallet_base_id: str | None = None) -> Node:
    """A Waypoint step.

    `match_joint_angles` is the one that matters: with it the arm goes to this
    exact configuration, instead of the controller re-solving IK and picking a
    different elbow. Leave it on for anything taught.

    `motion` is "joint" or "line". Joint plans reliably; line traces a straight
    cartesian path and is what you want for a short approach or retreat.

    `pallet_base_id` binds the step to a palletBase space item, which is how
    native palletizing indexes through a pattern.
    """
    if motion not in ("joint", "line"):
        raise ValueError(f"motion must be 'joint' or 'line', got {motion!r}")
    if len(joint_angles) != 6:
        raise ValueError(f"need 6 joint angles, got {len(joint_angles)}")

    # The robot stores a whole radius as an int; match it so a round-trip
    # compares equal.
    if float(blend_radius).is_integer():
        blend_radius = int(blend_radius)

    pallet_config = {"moveType": "box"}
    if pallet_base_id:
        pallet_config["selectedPalletBaseID"] = pallet_base_id

    return Node("Waypoint", {
        "target": {"pose": dict(target_pose), "tcpOption": tcp,
                   "jointAngles": list(joint_angles)},
        "stopHere": stop_here,
        "stopHereRaw": stop_here,
        "tcpOption": "auto",
        "motionKind": motion,
        "motionKindRaw": motion,
        "targetKind": "singlePosition",
        "blendConfig": {"kind": "blendRadius", "radius": blend_radius},
        "argumentKind": "Waypoint",
        "distanceUnit": "meter",
        "palletConfig": pallet_config,
        "positionListID": None,
        "relativeConfig": {"frame": "base", "targetKind": "singlePosition"},
        "speedLimitOption": "PARENT_DEFAULTS",
        "stopEarlyConditions": "",
        "useParentBlendConfig": False,
        "shouldMatchJointAngles": match_joint_angles,
        "moveDynamicBaseToReachPosition": True,
        "shouldMatchDynamicBasePosition": False,
    }, description)


def from_taught(space_item: dict, description: str = "", **kwargs) -> Node:
    """A Waypoint from a taught singlePosition, as `spaces_ws.py teach` writes."""
    if space_item.get("kind") != "singlePosition":
        raise ValueError(f"need a singlePosition, got {space_item.get('kind')!r}")
    positions = space_item.get("positions") or []
    if not positions:
        raise ValueError(f"{space_item.get('name')!r} has no taught position")
    first = positions[0]
    return waypoint(description or space_item.get("name", ""),
                    first["pose"], first["jointAngles"],
                    tcp=first.get("tcpOption", "wrist"), **kwargs)


def move_arm(children: list[Node], *, speed_percent: int = 100) -> Node:
    """A MoveArmToV2 step -- the container the waypoints hang off."""
    return Node("MoveArmToV2", {
        "motionSpeed": {"customLimits": None,
                        "motionSpeedPercent": speed_percent},
        "argumentKind": "MoveArmToV2",
        "speedLimitOption": "NO_MOTION_LIMITS",
        "moveDynamicBaseToReachPosition": False,
    }, children=list(children))


def loop(children: list[Node], *, times: int | None = None,
         condition=None) -> Node:
    """A Loop step. `times=None` loops forever, as the UI's default does."""
    return Node("Loop", {"times": times, "condition": condition,
                         "argumentKind": "Loop"}, children=list(children))


def build(name: str, roots: list[Node], *, space: list | None = None,
          description: str = "", motion_planner: str = "ROS2") -> dict:
    """Flatten nodes into the {steps, stepConfigurations} pair and wrap it."""
    configurations: dict = {}

    def walk(node: Node) -> dict:
        entry = {"id": node.id, "stepKind": node.step_kind}
        config = {"args": node.args}
        if node.description:
            config["description"] = node.description
        configurations[node.id] = config
        if node.children:
            entry["steps"] = [walk(child) for child in node.children]
        return entry

    steps = [walk(node) for node in roots]
    return {
        "name": name,
        "description": description,
        "motionPlanner": motion_planner,
        "steps": steps,
        "stepConfigurations": configurations,
        "space": list(space or []),
        "environmentVariables": [],
    }


def pick_and_place(name: str, pick: Node, place: Node,
                   apex: Node | None = None, *, times: int | None = None,
                   space: list | None = None) -> dict:
    """The usual shape: loop over pick, clear, place, clear.

    `apex` is the clearance waypoint the arm passes through between the two --
    taught above the carton rim, it is what keeps the tool from entering
    sideways.
    """
    sequence = [pick, place] if apex is None else [pick, apex, place, apex]
    return build(name, [loop([move_arm(sequence)], times=times)], space=space)
