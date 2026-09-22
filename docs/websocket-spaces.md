# Reading and writing Space items over the websocket

**Status: undocumented / unsupported.** This is reverse-engineered from the
robot UI's own bundle. The public REST API and the `standardbots` SDK cannot
write Space items; the web UI does it over an internal Feathers service on a
socket.io connection. `src/spaces_ws.py` drives that same service so it can be
done from the CLI. Nothing here is a Standard Bots-supported interface and it
can change without notice on any robot software update. Prefer the REST API and
the SDK for anything they cover.

## The short version

```bash
pip install 'python-socketio[client]'
export ROBOT_URL=https://cb1234.sb.app
export SB_ROBOT_PIN=123456          # or SB_FEATHERS_JWT, see Authentication

python src/spaces_ws.py list
python src/spaces_ws.py add-pallet --name cli_48x40 --length 48 --width 40 \
    --corner-x -1.45 --corner-y 0.30
python src/spaces_ws.py add-box --name carton --length 18 --width 12 --height 10 \
    --x -1.2 --y -1.5
python src/spaces_ws.py remove <space-id>
python src/spaces_ws.py backup --out spaces.json
python src/spaces_ws.py restore spaces.json --skip-existing
```

Re-open (or refresh) the robot visualizer to see a created item.

## Why REST is not enough

`GET /api/v1/space/globals` and `GET /api/v1/space/planes` exist and are the
only Space routes. Both are **GET only** -- there is no REST create, update or
delete for Space items, and the SDK exposes only `sdk.space.list_global_spaces()`
and `sdk.space.list_planes()`. So a pallet, plane or named position can be read
back but not written through the documented API.

The web UI creates them anyway. In its bundle:

```js
const bs = Ne("globalSpace");                       // a Feathers service
async function pP(e){ return (await bs().create({ spaceItem: e })).id }  // CREATE
async function mP(e){ await bs().remove(e) }                             // DELETE
```

`Ne(name)` resolves to `feathersApp.service(name)`, and the Feathers app is a
socket.io client:

```js
feathers().configure(socketio(io(host, { path: "/api", transports: ["websocket"] })))
```

So every service -- `globalSpace`, `routines`, `equipment`, `globalVariables`,
`apiAuth`, ... -- has full Feathers CRUD, but only over the websocket at
**`/api`**, not over REST.

## Transport

- socket.io, **websocket transport only**, `socketio_path="/api"`.
- Feathers wire format is `emit(method, service, ...args, ack)`:
  - list: `emit("find", "globalSpace", {}, cb)`
  - create: `emit("create", "globalSpace", { spaceItem }, cb)`
  - remove: `emit("remove", "globalSpace", id, cb)`
  - authenticate: `emit("create", "authentication", { strategy, accessToken }, cb)`
- The ack callback receives `(error, data)`; `error` is `null` on success.

## Authentication (the fiddly part)

The socket allows exactly two Feathers strategies, **`jwt`** and **`local`**
(`anonymous` and `apiToken` come back as "strategy not allowed in
authStrategies"). Findings, all confirmed against a live robot:

- **The dev REST bearer token is not a JWT.** Passing it to the `jwt` strategy
  returns `jwt malformed`. It works for REST, not for this socket.
- **The JWT the UI uses is in the browser**, at `localStorage['feathers-jwt']`.
  It decodes to `{ iss: "feathers", sub: "user_…", exp: … }` and is what the
  `jwt` strategy accepts.
- **`local` needs real per-user credentials** and is brute-force rate-limited
  (`429 Too many login attempts`) -- do not grind it.
- **The control-panel PIN path** (`controlPanelToken.create({ pin })`) mints a
  JWT too, but only with the correct PIN; wrong PINs return `Invalid PIN`, and
  `controlPanelAuthToken` in sessionStorage is only populated when you actually
  authenticate through that flow.
- **Auth is slow and needs confirming.** The server's JWT verification took
  ~10-30 s in testing and the ack was sometimes dropped, so a single
  `create authentication` is unreliable: a `create globalSpace` fired right
  after it races ahead and fails `Not authenticated`. `spaces_ws.py`
  authenticates and then *proves* it by reading `globalSpace`, retrying until
  the read stops 401-ing.
- **Tokens are short-lived** (~24 h here; can be far less). When it expires,
  re-copy `localStorage['feathers-jwt']` from the UI console.

### Getting a token

Two ways, both handled by the tool:

- **PIN (no browser).** `--pin` / `SB_ROBOT_PIN` mints a session token via
  `authenticate({strategy:"pin", username:"default", pin})` — the same call the
  login page makes. Preferred: it re-authenticates itself every run.
- **Borrow the UI's.** In the logged-in robot UI console, run
  `localStorage.getItem('feathers-jwt')` and pass it as `--jwt` /
  `SB_FEATHERS_JWT`.

## The palletBase schema

A `find globalSpace` on a robot with one pallet returns:

```json
{
  "id": "cfd52c64-901d-4eb0-b8c2-c8e1d683532a",
  "kind": "palletBase",
  "name": "P",
  "global": true,
  "lengthMM": 1200, "widthMM": 800, "heightMM": 100,
  "cornerXMM": 0, "cornerYMM": -600,
  "cornerToPosition": "left",
  "cornerYawDegrees": 0,
  "floorToPalletDistanceMM": -600,
  "positions": [],
  "description": ""
}
```

`length` runs along +X and `width` along +Y in the robot base frame; the pallet
is placed by one corner (`cornerToPosition`). `create` takes the same shape
wrapped as `{ spaceItem: { … } }` with a fresh `id` (a UUID). Other kinds seen
in the bundle: `customBase`, `DHBase`, `singlePosition`, and planes (a separate
`plane` service); those are not implemented here.

## Drawing real geometry

`palletBase` renders as a parametric footprint — fine for pallets, not for a
carton. The `environmentObject` kind carries a `fileURL`, and the visualizer's
three.js loaders accept `data:` URLs, so a mesh can be embedded directly in the
space item: no file server, no upload endpoint, no CORS.

`spaces_ws.py` builds those meshes by hand, with no dependencies:

- `open_top_box_glb()` — floor + 4 walls, coloured and alpha-blended
  (`alphaMode: BLEND`, `doubleSided` so the inner walls show through the open
  top). This is what `add-box` uploads.
- `solid_box_glb()` — a closed 6-face box, e.g. a metal blank.
- `open_top_box_stl()` — the same geometry as binary STL. STL carries no
  material, so colour and opacity fall back to the viewer's defaults; prefer GLB.

Wrap either with `glb_data_url()` / `stl_data_url()` and hand it to
`environment_object()`.

## How this was worked out

Everything above came from reading the UI bundle
(`/assets/index-*.js`), the SDK's generated `apis.py`, and probing the live
socket read-only, then confirming writes on an owner-authorised robot. No
credential was guessed, and the `local` strategy was abandoned as soon as it
rate-limited.
