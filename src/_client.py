"""
Shared setup for every Standard Bots REST API example in this folder.

Each example does the same three things, so they live here once:

    from _client import add_common_args, build_sdk

    parser = argparse.ArgumentParser(description="...")
    add_common_args(parser)              # adds --url / --token / --live
    args = parser.parse_args()

    sdk = build_sdk(args)                # builds the SDK from args, env, or .env
    with sdk.connection():
        ...

Credentials are resolved in this order:

    command-line flag  >  environment variable  >  a .env file in the repo root

The robot URL and API token both come from "Configure Developer API" in the
robot UI (see the README). This helper has no dependency beyond `standardbots`
itself -- the tiny .env reader below is built in on purpose.

SAFETY
------
build_sdk() defaults to the *simulated* robot. The real arm only moves when you
pass --live (or set ROBOT_KIND=live). This matters: the bare StandardBotsRobot()
constructor defaults to LIVE, which is exactly why every example funnels through
build_sdk() instead of constructing the SDK directly.
"""
from __future__ import annotations

import argparse
import os
import sys

from standardbots import StandardBotsRobot


def _repo_root() -> str:
    """Absolute path to the repo root (the parent of this src/ directory)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv() -> None:
    """Populate os.environ from a .env file in the repo root, if one exists.

    Deliberately dependency-free (no python-dotenv required). Variables already
    present in the real environment always win over values from .env.
    """
    env_path = os.path.join(_repo_root(), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add the --url / --token / --live flags shared by every example."""
    parser.add_argument(
        "--url",
        dest="url",
        default=None,
        help="Robot URL, e.g. https://cb1234.sb.app or http://<robot-ip>:3000. "
        "Defaults to the ROBOT_URL env var / .env file.",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=None,
        help="API token from Configure Developer API. "
        "Defaults to the ROBOT_TOKEN env var / .env file.",
    )
    parser.add_argument(
        "--live",
        dest="live",
        action="store_true",
        help="Drive the REAL robot. Omit this to run against the built-in "
        "simulator (the safe default).",
    )


def build_sdk(args: argparse.Namespace | None = None) -> StandardBotsRobot:
    """Build a StandardBotsRobot from CLI args, environment variables, or .env.

    Defaults to the simulator. Exits with a helpful message when the URL or
    token is missing, so examples fail clearly instead of with a stack trace.
    """
    _load_dotenv()

    url = getattr(args, "url", None) or os.environ.get("ROBOT_URL")
    token = getattr(args, "token", None) or os.environ.get("ROBOT_TOKEN")

    if not url or not token:
        sys.exit(
            "\nMissing robot URL or API token.\n"
            "  - pass --url and --token on the command line, or\n"
            "  - set ROBOT_URL and ROBOT_TOKEN (e.g. copy .env.example to .env).\n"
            "Both come from 'Configure Developer API' in the robot UI.\n"
        )

    # Live requires an explicit opt-in: the --live flag or ROBOT_KIND=live.
    live = bool(getattr(args, "live", False)) or (
        os.environ.get("ROBOT_KIND", "simulated").strip().lower() == "live"
    )

    robot_kind = (
        StandardBotsRobot.RobotKind.Live
        if live
        else StandardBotsRobot.RobotKind.Simulated
    )

    if live:
        print(
            "\n*** LIVE MODE: commands will move the REAL robot. "
            "Keep the cell guarded and be ready to e-stop. ***\n"
        )
    else:
        print("Connecting to the built-in simulator (pass --live for real hardware).")

    return StandardBotsRobot(url=url, token=token, robot_kind=robot_kind)
