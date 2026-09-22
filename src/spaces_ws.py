#!/usr/bin/env python3
"""List, create and remove global Space items on a Standard Bots robot from the CLI.

The public REST API can only READ Space items (`GET /api/v1/space/globals`,
`.../planes`). The web UI writes them over an undocumented Feathers service on
a socket.io connection; this drives the same service.

    python src/spaces_ws.py list
    python src/spaces_ws.py add-pallet --name cli_48x40 --length 48 --width 40 \
        --corner-x -1.45 --corner-y 0.30
    python src/spaces_ws.py remove <space-id>

Auth: pass `--pin` (SB_ROBOT_PIN) to mint a token, or `--jwt` (SB_FEATHERS_JWT)
copied from the UI console. The REST bearer token is not a JWT and is rejected.

Unsupported and reverse-engineered; see docs/websocket-spaces.md.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import uuid

try:
    import socketio  # python-socketio[client]
except ImportError:
    sys.exit("Needs python-socketio: pip install 'python-socketio[client]'")


IN_TO_MM = 25.4
M_TO_MM = 1000.0


def mint_jwt_from_pin(url: str, pin: str, username: str = "default",
                      timeout: float = 35.0) -> str:
    """Mint a session JWT from the control-panel PIN, as the login page does."""
    sio = socketio.Client()
    sio.connect(url, socketio_path="/api", transports=["websocket"], wait_timeout=20)
    try:
        box = {}
        ev = threading.Event()

        def cb(*ack):
            box["ack"] = ack
            ev.set()

        sio.emit("create", ("authentication",
                            {"strategy": "pin", "username": username, "pin": str(pin)}),
                 callback=cb)
        if not ev.wait(timeout):
            raise RuntimeError("pin login timed out")
        ack = box["ack"]
        err = ack[0] if ack else None
        if err is not None:
            raise RuntimeError(f"pin login rejected: {err}")
        data = ack[1] if len(ack) > 1 else {}
        token = (data or {}).get("accessToken") or (data or {}).get("token")
        if not token:
            raise RuntimeError(f"no token in login response: {data}")
        return token
    finally:
        sio.disconnect()


class SpacesClient:
    """Synchronous wrapper over the robot's Feathers socket.io API.

    Wire format is `emit(method, service, ...args, ack)`. Takes a `jwt` or a
    `pin` (which mints one).
    """

    def __init__(self, url: str, jwt: str = None, pin: str = None) -> None:
        self._url = url
        if not jwt and pin:
            jwt = mint_jwt_from_pin(url, pin)
        if not jwt:
            raise ValueError("SpacesClient needs a jwt or a pin.")
        self._jwt = jwt
        self._sio = socketio.Client()

    # -- connection ---------------------------------------------------------

    def __enter__(self) -> "SpacesClient":
        self._sio.connect(self._url, socketio_path="/api",
                          transports=["websocket"], wait_timeout=20)
        self._authenticate()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._sio.disconnect()
        except Exception:
            pass

    def _call(self, method: str, *args, timeout: float = 30.0):
        """One Feathers service call. Returns (error, data)."""
        box: dict = {"done": False}
        ev = threading.Event()

        def cb(*ack):
            box["ack"] = ack
            box["done"] = True
            ev.set()

        self._sio.emit(method, args, callback=cb)
        if not ev.wait(timeout):
            return ({"name": "Timeout", "message": f"{method} timed out"}, None)
        ack = box["ack"]
        err = ack[0] if len(ack) > 0 else None
        data = ack[1] if len(ack) > 1 else None
        return (err, data)

    def _authenticate(self, attempts: int = 4) -> None:
        """Authenticate, then confirm with a read -- the ack alone is unreliable.

        JWT verification took 10-30 s in testing and the ack is sometimes
        dropped, so a create() fired straight after races ahead and 401s.
        """
        last = None
        for attempt in range(attempts):
            self._call("create", "authentication",
                       {"strategy": "jwt", "accessToken": self._jwt}, timeout=35)
            err, _ = self._call("find", "globalSpace", {}, timeout=20)
            if err is None:
                return
            last = err
            time.sleep(1.0)
        raise RuntimeError(
            f"authentication did not take after {attempts} tries: {last}. "
            f"The feathers-jwt is probably expired -- re-copy it from the robot "
            f"UI console (localStorage.getItem('feathers-jwt')).")

    # -- space items --------------------------------------------------------

    def list(self) -> list[dict]:
        """Rows as {record_id, item}. `remove` keys on record_id, not item id."""
        err, data = self._call("find", "globalSpace", {})
        if err is not None:
            raise RuntimeError(f"find failed: {err}")
        return [{"record_id": row["id"], "item": row["spaceItem"]}
                for row in data["data"]]

    def create(self, space_item: dict) -> dict:
        err, data = self._call("create", "globalSpace", {"spaceItem": space_item})
        if err is not None:
            raise RuntimeError(f"create failed: {err}")
        return data

    def remove(self, space_id: str) -> dict:
        err, data = self._call("remove", "globalSpace", space_id)
        if err is not None:
            raise RuntimeError(f"remove failed: {err}")
        return data

    def routines(self) -> list[dict]:
        """Full routine documents -- steps, stepConfigurations, space, the lot."""
        err, data = self._call("find", "routines", {}, timeout=40)
        if err is not None:
            raise RuntimeError(f"find routines failed: {err}")
        return data.get("data", data) if isinstance(data, dict) else data

    @property
    def user_id(self) -> str:
        """The authenticated user, from the token's `sub` -- what a routine
        stores as createdByID. The column is NOT NULL and the server does not
        fill it, so a create without it is rejected."""
        import base64
        import json as _json
        payload = self._jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return _json.loads(base64.urlsafe_b64decode(payload))["sub"]

    def create_routine(self, doc: dict) -> dict:
        doc = {**doc}
        doc.setdefault("createdByID", self.user_id)
        err, data = self._call("create", "routines", doc, timeout=40)
        if err is not None:
            raise RuntimeError(f"create routine failed: {err}")
        return data

    def remove_routine(self, routine_id: str) -> dict:
        err, data = self._call("remove", "routines", routine_id, timeout=40)
        if err is not None:
            raise RuntimeError(f"remove routine failed: {err}")
        return data

    def patch(self, record_id: str, changes: dict) -> dict:
        """Feathers patch on a globalSpace record (keyed by the record id)."""
        err, data = self._call("patch", "globalSpace", record_id, changes)
        if err is not None:
            raise RuntimeError(f"patch failed: {err}")
        return data


# -- space-item builders ---------------------------------------------------

def pallet_base(name: str, length_mm: float, width_mm: float, height_mm: float,
                corner_x_mm: float, corner_y_mm: float,
                floor_to_pallet_mm: float = 0.0, yaw_deg: float = 0.0) -> dict:
    """A palletBase. Length runs +X, width +Y; placed by one corner."""
    return {
        "id": str(uuid.uuid4()),
        "kind": "palletBase",
        "name": name,
        "global": True,
        "lengthMM": round(length_mm),
        "widthMM": round(width_mm),
        "heightMM": round(height_mm),
        "cornerXMM": round(corner_x_mm),
        "cornerYMM": round(corner_y_mm),
        "positions": [],
        "description": "created from CLI over the Feathers websocket",
        "cornerToPosition": "left",
        "cornerYawDegrees": yaw_deg,
        "floorToPalletDistanceMM": round(floor_to_pallet_mm),
    }


import base64  # noqa: E402
import struct  # noqa: E402



def single_position(name: str, x_m: float, y_m: float, z_m: float,
                    quat_ijkw: tuple, joint_angles: list,
                    tcp_option: str = "wrist") -> dict:
    """A taught singlePosition: a pose AND the joint angles that reached it.

    The joint angles are what make a taught point deterministic -- a move step
    with `shouldMatchJointAngles` goes to this exact arm configuration instead
    of letting the controller re-solve IK and pick a different elbow.
    """
    i, j, k, w = quat_ijkw
    return {
        "id": str(uuid.uuid4()),
        "kind": "singlePosition",
        "name": name,
        "global": True,
        "description": "taught from the CLI",
        "positions": [{
            "pose": {"x": x_m, "y": y_m, "z": z_m, "i": i, "j": j, "k": k, "w": w},
            "tcpOption": tcp_option,
            "jointAngles": list(joint_angles),
        }],
    }


def read_arm_position(url: str, token: str) -> tuple:
    """Current tooltip pose and joint rotations, via REST."""
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        url.rstrip("/") + "/api/v1/movement/position/arm",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = _json.load(resp)
    tip = data["tooltip_position"]
    pos, quat = tip["position"], tip["orientation"]["quaternion"]
    return ((pos["x"], pos["y"], pos["z"]),
            (quat["x"], quat["y"], quat["z"], quat["w"]),
            data["joint_rotations"])

# -- meshes (environmentObject) --------------------------------------------
#
# `environmentObject` carries a `fileURL`, and the visualizer's three.js loaders
# accept `data:` URLs -- so a mesh can be embedded, with no file server or
# upload endpoint. It is the only way to draw real geometry.

def _box_tris(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (3, 6, 2), (3, 7, 6),
             (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


WALL_M = 0.0127   # 0.5 inch carton wall


def _open_top_box_tris(inner_l: float, inner_w: float, inner_h: float,
                       wall: float):
    """Floor + 4 walls, built outward from an inner cavity. Outer corner at origin."""
    t = wall
    ol, ow, oh = inner_l + 2 * t, inner_w + 2 * t, inner_h + t
    return (_box_tris(0, 0, 0, ol, ow, t)              # floor
            + _box_tris(0, 0, t, t, ow, oh)            # -X wall
            + _box_tris(ol - t, 0, t, ol, ow, oh)      # +X wall
            + _box_tris(t, 0, t, ol - t, t, oh)        # -Y wall (between X walls)
            + _box_tris(t, ow - t, t, ol - t, ow, oh))  # +Y wall


def open_top_box_stl(inner_l: float, inner_w: float, inner_h: float,
                     wall_m: float = WALL_M) -> bytes:
    """An open-top box (inner cavity given) as binary STL in metres."""
    tris = _open_top_box_tris(inner_l, inner_w, inner_h, wall_m)
    out = bytearray(b"open-top box".ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<3f", 0.0, 0.0, 0.0)
        for vert in (a, b, c):
            out += struct.pack("<3f", *vert)
        out += struct.pack("<H", 0)
    return bytes(out)


def stl_data_url(stl: bytes) -> str:
    return "data:model/stl;base64," + base64.b64encode(stl).decode()


# STL carries no material; GLB does (base colour + alpha), so the coloured,
# see-through boxes below are GLBs, built by hand -- no dependencies.

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _unit(v):
    import math
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def open_top_box_glb(inner_l: float, inner_w: float, inner_h: float,
                     rgba=(0.55, 0.40, 0.26, 0.4), wall_m: float = WALL_M) -> bytes:
    """Open-top box as a binary GLB: flat-shaded, double-sided, alpha blended."""
    import json as _json

    tris = _open_top_box_tris(inner_l, inner_w, inner_h, wall_m)

    positions, normals = [], []
    for a, b, c in tris:
        n = _unit(_cross(_sub(b, a), _sub(c, a)))
        positions += [a, b, c]
        normals += [n, n, n]

    pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    nrm_bytes = b"".join(struct.pack("<3f", *p) for p in normals)
    blob = pos_bytes + nrm_bytes
    n = len(positions)
    xs, ys, zs = ([p[i] for p in positions] for i in range(3))

    gltf = {
        "asset": {"version": "2.0", "generator": "sb-rest-api spaces_ws"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "material": 0, "mode": 4}]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorFactor": list(rgba),
            "metallicFactor": 0.0, "roughnessFactor": 0.85},
            "alphaMode": "BLEND", "doubleSided": True}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(nrm_bytes),
             "target": 34962}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC3"}],
    }

    json_bytes = _json.dumps(gltf, separators=(",", ":")).encode()
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    blob += b"\x00" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(blob)

    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)          # glTF header
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)    # JSON chunk
    out += json_bytes
    out += struct.pack("<II", len(blob), 0x004E4942)          # BIN chunk
    out += blob
    return bytes(out)


def solid_box_glb(length_m: float, width_m: float, height_m: float,
                  rgba=(0.62, 0.64, 0.67, 1.0), metallic: float = 1.0,
                  roughness: float = 0.35) -> bytes:
    """A solid box (6 faces) as a GLB -- e.g. a metal block. Corner at origin."""
    import json as _json

    tris = _box_tris(0, 0, 0, length_m, width_m, height_m)
    positions, normals = [], []
    for a, b, c in tris:
        n = _unit(_cross(_sub(b, a), _sub(c, a)))
        positions += [a, b, c]
        normals += [n, n, n]
    pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    nrm_bytes = b"".join(struct.pack("<3f", *p) for p in normals)
    blob = pos_bytes + nrm_bytes
    n = len(positions)
    xs, ys, zs = ([p[i] for p in positions] for i in range(3))
    gltf = {
        "asset": {"version": "2.0", "generator": "sb-rest-api spaces_ws"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "material": 0, "mode": 4}]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorFactor": list(rgba), "metallicFactor": metallic,
            "roughnessFactor": roughness}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(nrm_bytes),
             "target": 34962}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC3"}],
    }
    json_bytes = _json.dumps(gltf, separators=(",", ":")).encode()
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    blob += b"\x00" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(blob)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)
    out += json_bytes
    out += struct.pack("<II", len(blob), 0x004E4942)
    out += blob
    return bytes(out)


def glb_data_url(glb: bytes) -> str:
    return "data:model/gltf-binary;base64," + base64.b64encode(glb).decode()


def environment_object(name: str, data_url: str, file_name: str,
                       x_m: float, y_m: float, z_m: float,
                       scale: float = 1.0) -> dict:
    """An environmentObject Space item carrying an embedded mesh."""
    return {
        "id": str(uuid.uuid4()),
        "kind": "environmentObject",
        "name": name,
        "global": True,
        "description": "open-top box, CLI-created (STL embedded as a data URL)",
        "fileURL": data_url,
        "fileName": file_name,
        "scale": scale,
        # {x,y,z} + identity quaternion, as routine Space positions use.
        "pose": {"x": x_m, "y": y_m, "z": z_m,
                 "i": 0.0, "j": 0.0, "k": 0.0, "w": 1.0},
    }


# -- CLI -------------------------------------------------------------------

def _jwt_from(args) -> str:
    """A JWT if given, else None -- the client mints one from the PIN."""
    return args.jwt or os.environ.get("SB_FEATHERS_JWT")


def _url_from(args) -> str:
    url = args.url or os.environ.get("ROBOT_URL")
    if not url:
        sys.exit("Need the robot URL: pass --url or set ROBOT_URL.")
    return url


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=None, help="Robot URL (or ROBOT_URL).")
    ap.add_argument("--jwt", default=None,
                    help="feathers-jwt (or SB_FEATHERS_JWT), from the UI console: "
                         "localStorage.getItem('feathers-jwt').")
    ap.add_argument("--pin", default=None,
                    help="Control-panel PIN (or SB_ROBOT_PIN) to mint a token "
                         "instead; ignored when --jwt is given.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List global space items.")

    ap_add = sub.add_parser("add-pallet", help="Create a palletBase.")
    ap_add.add_argument("--name", required=True)
    ap_add.add_argument("--length", type=float, required=True,
                        help="Length along +X, in INCHES.")
    ap_add.add_argument("--width", type=float, required=True,
                        help="Width along +Y, in INCHES.")
    ap_add.add_argument("--height", type=float, default=4.75,
                        help="Deck height in inches (default 4.75).")
    ap_add.add_argument("--corner-x", type=float, required=True,
                        help="Corner X in METRES, robot base frame.")
    ap_add.add_argument("--corner-y", type=float, required=True,
                        help="Corner Y in METRES, robot base frame.")
    ap_add.add_argument("--floor-to-pallet", type=float, default=0.0,
                        help="Pallet deck offset from floor, in METRES.")
    ap_add.add_argument("--yaw", type=float, default=0.0, help="Yaw in degrees.")

    ap_tc = sub.add_parser(
        "teach",
        help="Save the arm's CURRENT pose and joint angles as a taught "
             "singlePosition, as the UI's teach button does.")
    ap_tc.add_argument("--name", required=True)
    ap_tc.add_argument("--token", default=None,
                       help="REST bearer token (or ROBOT_TOKEN); needed to read "
                            "the arm's position.")
    ap_tc.add_argument("--tcp", default="wrist", choices=["wrist", "tool"])

    ap_rm = sub.add_parser("remove", help="Remove a space item by id.")
    ap_rm.add_argument("space_id")

    ap_gr = sub.add_parser(
        "build-routine",
        help="Generate a pick/apex/place routine from taught singlePositions "
             "and create it on the robot.")
    ap_gr.add_argument("--name", required=True, help="Name for the new routine.")
    ap_gr.add_argument("--pick", required=True,
                       help="Name of the taught singlePosition to pick from.")
    ap_gr.add_argument("--place", required=True,
                       help="Name of the taught singlePosition to place at.")
    ap_gr.add_argument("--apex", default=None,
                       help="Clearance position passed through between the two. "
                            "Teach it above the carton rim.")
    ap_gr.add_argument("--times", type=int, default=None,
                       help="Loop count (default: loop forever).")
    ap_gr.add_argument("--dry-run", action="store_true",
                       help="Print the document instead of creating it.")

    ap_rb = sub.add_parser(
        "backup-routines",
        help="Save every routine's FULL document to a JSON file. Do this "
             "before touching stepConfigurations.")
    ap_rb.add_argument("--out", default=None,
                       help="Path (default: backups/routines_<timestamp>.json).")

    ap_rr = sub.add_parser(
        "restore-routines",
        help="Re-create routines from a backup-routines file. They come back "
             "under new ids, so this never overwrites what is on the robot.")
    ap_rr.add_argument("file")
    ap_rr.add_argument("--only", default=None,
                       help="Restore just the routine with this name.")
    ap_rr.add_argument("--suffix", default="",
                       help="Append this to each restored routine's name.")

    ap_bk = sub.add_parser("backup", help="Save all space items to a JSON file.")
    ap_bk.add_argument("--out", default=None,
                       help="Path (default: backups/spaces_<timestamp>.json).")

    ap_rs = sub.add_parser("restore",
                           help="Re-create space items from a backup file. "
                                "This is how 'removed but not lost' comes back.")
    ap_rs.add_argument("file")
    ap_rs.add_argument("--skip-existing", action="store_true",
                       help="Skip items whose name is already present.")

    ap_box = sub.add_parser(
        "add-box",
        help="Create an environmentObject: an open-top box drawn from an "
             "embedded GLB mesh (the only way to draw real geometry).")
    ap_box.add_argument("--name", required=True)
    ap_box.add_argument("--length", type=float, required=True,
                        help="Inner cavity length along +X, in INCHES.")
    ap_box.add_argument("--width", type=float, required=True,
                        help="Inner cavity width along +Y, in INCHES.")
    ap_box.add_argument("--height", type=float, required=True,
                        help="Inner cavity height, in INCHES.")
    ap_box.add_argument("--x", type=float, required=True,
                        help="Outer corner X in METRES, robot base frame.")
    ap_box.add_argument("--y", type=float, required=True,
                        help="Outer corner Y in METRES, robot base frame.")
    ap_box.add_argument("--z", type=float, default=0.0,
                        help="Outer corner Z in METRES (default 0).")
    ap_box.add_argument("--wall", type=float, default=0.5,
                        help="Wall thickness in INCHES, added OUTWARD from the "
                             "cavity (default 0.5).")
    ap_box.add_argument("--opacity", type=float, default=0.4,
                        help="Box opacity 0-1 (default 0.4); 1.0 is solid.")
    ap_box.add_argument("--replace", action="store_true",
                        help="Remove an existing environmentObject of the same "
                             "name first (idempotent re-upload).")

    args = ap.parse_args()
    url, jwt = _url_from(args), _jwt_from(args)
    pin = args.pin or os.environ.get("SB_ROBOT_PIN")

    with SpacesClient(url, jwt=jwt, pin=pin) as client:
        if args.cmd == "list":
            rows = client.list()
            print(f"{len(rows)} global space item(s):")
            for row in rows:
                it = row["item"]
                dims = (f"{it.get('lengthMM')}x{it.get('widthMM')}x"
                        f"{it.get('heightMM')}mm" if it["kind"] == "palletBase"
                        else "")
                print(f"  {row['record_id']}   # <- id for `remove`")
                print(f"    {it['name']!r}  kind={it['kind']}  {dims}")

        elif args.cmd == "add-pallet":
            item = pallet_base(
                name=args.name,
                length_mm=args.length * IN_TO_MM,
                width_mm=args.width * IN_TO_MM,
                height_mm=args.height * IN_TO_MM,
                corner_x_mm=args.corner_x * M_TO_MM,
                corner_y_mm=args.corner_y * M_TO_MM,
                floor_to_pallet_mm=args.floor_to_pallet * M_TO_MM,
                yaw_deg=args.yaw,
            )
            client.create(item)
            print(f"created palletBase {item['name']!r} (id {item['id']})")
            print("Re-open the robot visualizer to see it. Remove with:")
            print(f"  python src/spaces_ws.py remove {item['id']}")

        elif args.cmd == "teach":
            token = args.token or os.environ.get("ROBOT_TOKEN")
            if not token:
                sys.exit("teach needs the REST token: --token or ROBOT_TOKEN.")
            (x, y, z), quat, joints = read_arm_position(url, token)
            item = single_position(args.name, x, y, z, quat, joints,
                                   tcp_option=args.tcp)
            client.create(item)
            print(f"taught {args.name!r} at ({x:.3f}, {y:.3f}, {z:.3f}) m")
            print(f"  joints: {[round(j, 4) for j in joints]}")

        elif args.cmd == "remove":
            client.remove(args.space_id)
            print(f"removed {args.space_id}")

        elif args.cmd == "backup":
            import datetime
            import json as _json
            items = [r["item"] for r in client.list()]
            out = args.out or (
                f"backups/spaces_{datetime.datetime.now():%Y%m%d_%H%M%S}.json")
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            _json.dump(items, open(out, "w"), indent=2)
            print(f"backed up {len(items)} item(s) -> {out}")

        elif args.cmd == "build-routine":
            import json as _json
            from routine_builder import from_taught, pick_and_place

            taught = {r["item"]["name"]: r["item"] for r in client.list()
                      if r["item"]["kind"] == "singlePosition"}
            missing = [n for n in (args.pick, args.place, args.apex)
                       if n and n not in taught]
            if missing:
                sys.exit(f"no taught position named {', '.join(missing)}. "
                         f"Have: {', '.join(sorted(taught)) or '(none)'}. "
                         f"Teach one with `spaces_ws.py teach`.")
            used = [args.pick, args.place] + ([args.apex] if args.apex else [])
            doc = pick_and_place(
                args.name,
                pick=from_taught(taught[args.pick], "Pick"),
                place=from_taught(taught[args.place], "Place"),
                apex=from_taught(taught[args.apex], "Apex") if args.apex else None,
                times=args.times,
                space=[taught[n] for n in used],
            )
            if args.dry_run:
                print(_json.dumps(doc, indent=2))
            else:
                data = client.create_routine(doc)
                print(f"created routine {args.name!r} -> {data.get('id')}")
                print("Open it in the robot UI to review before running it.")

        elif args.cmd == "backup-routines":
            import datetime
            import json as _json
            rows = client.routines()
            out = args.out or (
                f"backups/routines_{datetime.datetime.now():%Y%m%d_%H%M%S}.json")
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            _json.dump(rows, open(out, "w"), indent=2)
            for r in rows:
                print(f"  {r['name']:<20} steps={len(r.get('steps') or {})} "
                      f"stepConfigurations={len(r.get('stepConfigurations') or {})} "
                      f"spaces={len(r.get('space') or [])}")
            print(f"\nbacked up {len(rows)} routine(s) -> {out}")

        elif args.cmd == "restore-routines":
            import json as _json
            docs = _json.load(open(args.file))
            if args.only:
                docs = [d for d in docs if d["name"] == args.only]
                if not docs:
                    sys.exit(f"no routine named {args.only!r} in {args.file}")
            for doc in docs:
                doc = {k: v for k, v in doc.items()
                       if k not in ("id", "createdAt", "updatedAt",
                                    "configurationUpdatedAt")}
                doc["name"] = doc["name"] + args.suffix
                data = client.create_routine(doc)
                print(f"restored {doc['name']!r} -> {data.get('id')}")
            print(f"\nrestored {len(docs)} routine(s) from {args.file}")

        elif args.cmd == "restore":
            import json as _json
            items = _json.load(open(args.file))
            existing = {r["item"]["name"] for r in client.list()}
            done = 0
            for item in items:
                if args.skip_existing and item["name"] in existing:
                    print(f"skip existing {item['name']!r}")
                    continue
                # A fresh id avoids colliding with anything already present.
                item = {**item, "id": str(uuid.uuid4())}
                client.create(item)
                print(f"restored {item['name']!r} ({item['kind']})")
                done += 1
            print(f"\nrestored {done} item(s) from {args.file}")

        elif args.cmd == "add-box":
            if args.replace:
                for row in client.list():
                    if (row["item"]["kind"] == "environmentObject"
                            and row["item"]["name"] == args.name):
                        client.remove(row["record_id"])
                        print(f"removed existing {args.name!r}")
            wall_m = args.wall * IN_TO_MM / M_TO_MM
            glb = open_top_box_glb(
                args.length * IN_TO_MM / M_TO_MM,
                args.width * IN_TO_MM / M_TO_MM,
                args.height * IN_TO_MM / M_TO_MM,
                rgba=(0.55, 0.40, 0.26, max(0.0, min(1.0, args.opacity))),
                wall_m=wall_m,
            )
            env = environment_object(args.name, glb_data_url(glb),
                                     f"{args.name}.glb",
                                     x_m=args.x, y_m=args.y, z_m=args.z)
            client.create(env)
            print(f"created open-top box {args.name!r}: inner "
                  f"{args.length:g}x{args.width:g}x{args.height:g} in, "
                  f"{args.wall:g}in walls ({len(glb)} B GLB) "
                  f"@ ({args.x:.2f}, {args.y:.2f}, {args.z:.2f}) m")
            print("Refresh the robot visualizer to see it. Remove with:")
            print(f"  python src/spaces_ws.py remove <id from `list`>")


if __name__ == "__main__":
    main()
