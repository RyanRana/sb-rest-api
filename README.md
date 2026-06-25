# Standard Bots REST API + Python SDK

Control a Standard Bots RO1 or RO2 from Python over HTTPS: read robot state, move the
arm, run saved routines, drive the gripper, read and write I/O, and recover from faults.
This starter repo is the request/response counterpart to the
[ROS2 Realtime API](https://github.com/standardbots/ros2-realtime-api): it is best for
discrete, high-level commands, not for tight closed-loop control. If you need streaming
state or velocity-level control, reach for the ROS2 Realtime API instead.

This repository has been written for and verified on **release/2026.01.23.124**

## Safety

- The Developer API is in **beta**. Interfaces can change between releases.
- Keep the robot cell **guarded** while developing, and stay ready to trigger an
  emergency stop. A REST call can move real hardware.
- Every example in this repo defaults to the **built-in simulator**. Real hardware is
  only touched when you explicitly pass `--live` (or set `ROBOT_KIND=live`).
- If the Developer API is not available on your robot, contact
  [support@standardbots.com](mailto:support@standardbots.com).

## Robot setup

Enable the Developer API from the robot UI and grab its credentials:

1. Open the robot UI and click the **robot name** (Settings), then open
   **Configure Developer API**.
2. **Enable the Developer API**.
3. Copy the **Authorization Token**. This token is specific to that one robot.

You also need the robot's URL. Use whichever form matches how you reach the controller:

- `https://cb1234.sb.app` — cloud (replace `cb1234` with your robot's serial)
- `http://<robot-ip>:3000` — same LAN as the robot
- `http://localhost:3000` — running directly on the controller

## Client setup

Requires **Python 3.7+**.

Clone the repo:

```bash
git clone https://github.com/standardbots/sb-rest-api.git
cd sb-rest-api
```

Create a virtual environment and install the SDK. Either run the steps manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

...or let the Makefile do it:

```bash
make setup
```

Then create your `.env` and fill in your robot's URL and token:

```bash
cp .env.example .env
# edit .env and set ROBOT_URL and ROBOT_TOKEN
```

Credentials resolve in this order: **command-line flag > environment variable > `.env`
file**. So instead of a `.env` file you can pass `--url` and `--token` on the command
line, or export `ROBOT_URL` and `ROBOT_TOKEN` in your shell.

## Running the examples

Every example funnels through `src/_client.py`, which builds the SDK and **defaults to
the simulator**. This is deliberate: the bare `StandardBotsRobot()` constructor defaults
to *live*, so the helper keeps you safe by default. To drive real hardware, pass `--live`
(or set `ROBOT_KIND=live`).

Start here:

```bash
make quickstart
```

General form for any script:

```bash
python src/<name>.py [--url <robot-url> --token <token>] [--live]
```

| Script | What it does | Example command |
| --- | --- | --- |
| `quickstart.py` | Connect and run a health check. Start here. | `python src/quickstart.py` |
| `read_state.py` | Read TCP pose, joint angles, and health (read-only). | `python src/read_state.py` |
| `move_to_pose.py` | Move the tool up a few cm. **Moves the arm.** | `python src/move_to_pose.py --up 0.05` |
| `run_routine.py` | List, play, and monitor a saved routine. | `python src/run_routine.py` (lists ids), then `--routine-id <id>` |
| `gripper.py` | Open/close or force-grip. **Moves the gripper.** | `python src/gripper.py --width 50 --force 20` |
| `io_control.py` | Read I/O, optionally set pins. | `python src/io_control.py --set "Output 1=high"` |
| `recover.py` | Inspect faults, optionally clear them. | `python src/recover.py --recover` |
| `spaces.py` | List saved Spaces (waypoints) (read-only). | `python src/spaces.py` |
| `payload.py` | Set or read the payload mass. | `python src/payload.py --mass 1.5` |
| `estop.py` | Trigger a software emergency stop. | `python src/estop.py --reason "testing"` |

Add `--live` to any of these to run against the real robot, for example:

```bash
python src/move_to_pose.py --up 0.05 --live
```

## The control surface

The SDK groups calls by function, and each group maps 1:1 onto the REST routes
documented at <https://docs.standardbots.com/docs/latest>
(for example, `sdk.movement.brakes` corresponds to `/api/v1/movement/brakes`).

| SDK group | What it does | Key calls |
| --- | --- | --- |
| `sdk.status` | Health and control mode. | `health.get_health()`, `control.get_configuration_state_control()` |
| `sdk.movement.brakes` | Release/engage brakes, software e-stop. | `unbrake()`, `brake()`, `get_brakes_state()`, `engage_emergency_stop()` |
| `sdk.movement.position` | Move the arm and read its position. | `move_tooltip()`, `move()`, `set_arm_position()`, `get_arm_position()` |
| `sdk.poses.pose_retrieval` | Read TCP / joint / flange pose. | `get_tooltip_position()`, `get_joints_position()`, `get_flange_position()` |
| `sdk.routine_editor.routines` | Run saved routines. | `list()`, `load()`, `play()`, `pause()`, `stop()`, `get_state()` |
| `sdk.routine_editor.variables` | Read and write routine variables. | `load()`, `update()` |
| `sdk.equipment` | Control the gripper / end-effector. | `get_gripper_configuration()`, `onrobot_2fg7_move()`, `control_gripper()` |
| `sdk.io` | Read and write digital/analog I/O. | `status.get_io_state()`, `control.update_io_state()` |
| `sdk.recovery` | Inspect and clear faults. | `recover.get_status()`, `recover.recover()` |
| `sdk.payload` | Set and read the payload mass. | `set_payload()`, `get_payload()` |
| `sdk.space` | List saved Spaces (named waypoints). | `list_global_spaces()` |

## The motion pattern

Moving the arm follows a consistent pattern:

1. **Take control** of the robot.
2. **Unbrake** (release the brakes).
3. **Move** the arm.
4. Optionally **re-brake** when finished.

Running a saved routine does **not** require brake management — the routine handles its
own control and braking.

## Troubleshooting

- **401 Unauthorized** — bad or missing token. The Authorization Token is per-robot; copy
  it again from **Configure Developer API** and confirm it matches the robot at `ROBOT_URL`.
- **Timeouts / connection refused** — confirm the Developer API is enabled, the host is
  reachable, and you are using the right URL form (`https://cb1234.sb.app`,
  `http://<robot-ip>:3000`, or `http://localhost:3000`).
- **"It moved the REAL robot"** — you passed `--live` or set `ROBOT_KIND=live`. Drop the
  flag (and unset the env var) to run against the simulator.
- **The arm will not move** — the brakes are engaged, there is an active fault, or the
  robot is under routine-editor control. Unbrake, clear faults, and switch control to
  **Api**.
- **Gripper force errors** — the gripper is not configured or not powered. Check the
  gripper configuration and wiring in the robot UI.
- **I/O writes take the pin's full name, not a number** — read the current I/O state
  first, then `--set "<pin>=<value>"` using the exact key and value shown (e.g.
  `--set "Output 1=high"`, not `--set 1=1`). Quote each pair, since pin names have spaces.
- **A routine won't play / "not found"** — `--routine-id` needs the id string from
  `python src/run_routine.py` (e.g. `routine_0b0...`), not the routine name in the UI.
- **Numbers must be floats** — pass `z=0.0`, not `z=0`. Integer values where a float is
  expected will be rejected.

## Versioning

Pin the SDK in `requirements.txt`:

```
standardbots==2.20260617.2
```

The API surface changes between releases. Re-test your integration whenever you upgrade
the SDK.

## Known limitations

- **Routines are read/run only.** You can list, load, play, pause, and stop routines via
  the public API, but you cannot create, upload, or delete them.
- **No direct velocity or closed-loop control over REST.** For that, use the
  [ROS2 Realtime API](https://github.com/standardbots/ros2-realtime-api).
- **Request/response latency** makes REST unsuitable for tight control loops. Use it for
  discrete, high-level commands.

## References

- API reference — <https://docs.standardbots.com/docs/latest>
- Configuring the SDK — <https://docs.standardbots.com/docs/-/rest/intro/configuring-sdk>
- PyPI package — <https://pypi.org/project/standardbots/>
- ROS2 Realtime API — <https://github.com/standardbots/ros2-realtime-api>
