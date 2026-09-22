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


def waypoint(description: str, target_pose: Pose,
             joint_angles: JointAngles | None = None,
             *, motion: str = "joint", stop_here: bool = True,
             blend_radius: float = 0.0, match_joint_angles: bool | None = None,
             tcp: str = "wrist", pallet_base_id: str | None = None,
             position_list_id: str | None = None) -> Node:
    """A Waypoint step.

    Pass `joint_angles` for a TAUGHT point and the arm goes to that exact
    configuration. Leave them out for a COMPUTED pose and the controller's
    planner solves IK itself -- there is no IK endpoint to do it beforehand,
    and solving it inside the planner is what keeps the result collision-aware.
    `match_joint_angles` defaults to whether joint angles were supplied.

    `motion` is "joint" or "line". Joint plans reliably; line traces a straight
    cartesian path and is what you want for a short approach or retreat.

    `position_list_id` points the step at a palletBoxes item, so it indexes
    through a pattern instead of going to one pose; `pallet_base_id` names the
    palletBase that pattern sits on.
    """
    if motion not in ("joint", "line"):
        raise ValueError(f"motion must be 'joint' or 'line', got {motion!r}")
    if joint_angles is not None and len(joint_angles) != 6:
        raise ValueError(f"need 6 joint angles, got {len(joint_angles)}")
    if match_joint_angles is None:
        match_joint_angles = joint_angles is not None
    if match_joint_angles and joint_angles is None:
        raise ValueError("match_joint_angles needs joint_angles to match")

    # The robot stores a whole radius as an int; match it so a round-trip
    # compares equal.
    if float(blend_radius).is_integer():
        blend_radius = int(blend_radius)

    pallet_config = {"moveType": "box"}
    if pallet_base_id:
        pallet_config["selectedPalletBaseID"] = pallet_base_id

    target = {"pose": dict(target_pose), "tcpOption": tcp,
              "jointAngles": list(joint_angles) if joint_angles else None}
    return Node("Waypoint", {
        "target": target,
        "stopHere": stop_here,
        "stopHereRaw": stop_here,
        "tcpOption": "auto",
        "motionKind": motion,
        "motionKindRaw": motion,
        "targetKind": "positionList" if position_list_id else "singlePosition",
        "blendConfig": {"kind": "blendRadius", "radius": blend_radius},
        "argumentKind": "Waypoint",
        "distanceUnit": "meter",
        "palletConfig": pallet_config,
        "positionListID": position_list_id,
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


def box_type(name: str, length_mm: float, width_mm: float, height_mm: float,
             *, weight_kg: float = 1.0, pickup_pose: Pose | None = None,
             pickup_joints: JointAngles | None = None) -> dict:
    """One SKU in a pallet pattern. `depth` runs along +X, `width` along +Y."""
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "depth": round(length_mm),
        "width": round(width_mm),
        "height": round(height_mm),
        "weight": weight_kg,
    }
    if pickup_pose is not None:
        entry["pickupPosition"] = {
            "pose": dict(pickup_pose), "tcpOption": "wrist",
            "jointAngles": list(pickup_joints) if pickup_joints else None}
    return entry


def layer_pattern(name: str, box_type_id: str, slots: list[dict],
                  *, approach_direction_deg: int = 315,
                  automatic_sequencing: bool = False) -> dict:
    """One layer: where each box sits on the pallet.

    A slot is {x, y} in millimetres from the pallet corner, optionally with
    `rotation` (degrees) and `approach_direction` (degrees; the heading the
    tool comes in from, which is what stops it entering through a wall).
    Order follows the list.
    """
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "boxTypeID": box_type_id,
        "boxList": [{
            "id": str(uuid.uuid4()),
            "x": round(slot["x"]),
            "y": round(slot["y"]),
            "order": index,
            "rotation": slot.get("rotation", 0),
            "approachDirection": slot.get("approach_direction", 0),
        } for index, slot in enumerate(slots, start=1)],
        "automaticSequencing": automatic_sequencing,
        "globalApproachDirection": approach_direction_deg,
    }


def pallet_boxes(name: str, pallet_base_id: str, box_types: list[dict],
                 patterns: list[dict], *, approach_z_mm: float = 0.0,
                 approach_xy_mm: float = 100.0, global_space: bool = True) -> dict:
    """A palletBoxes space item -- the pattern a Waypoint indexes through.

    `approach_z_mm` and `approach_xy_mm` are the clearance the arm keeps on the
    way in and out of each slot. They are why this path does not need a
    hand-built hover waypoint per box.
    """
    return {
        "id": str(uuid.uuid4()),
        "kind": "palletBoxes",
        "name": name,
        "global": global_space,
        "description": "generated from the CLI",
        "boxTypes": list(box_types),
        "positions": [],
        "layerPatterns": list(patterns),
        "layerOrder": [pattern["id"] for pattern in patterns],
        "palletBaseIDs": [pallet_base_id],
        "approachDistanceZMM": round(approach_z_mm),
        "approachDistanceXYMM": round(approach_xy_mm),
    }


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


def grid_slots(pallet_l_mm: float, pallet_w_mm: float,
               box_l_mm: float, box_w_mm: float,
               *, gap_mm: float = 0.0) -> list[dict]:
    """Fill a pallet with a simple grid of slots, row-major from the corner.

    A placeholder for a real packing solver: swap this for whatever decides
    which SKU goes where, and feed the result to `layer_pattern`.
    """
    slots = []
    y = 0.0
    while y + box_w_mm <= pallet_w_mm:
        x = 0.0
        while x + box_l_mm <= pallet_l_mm:
            slots.append({"x": x, "y": y})
            x += box_l_mm + gap_mm
        y += box_w_mm + gap_mm
    return slots


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
