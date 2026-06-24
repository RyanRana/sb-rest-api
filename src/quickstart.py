#!/usr/bin/env python3
"""Your first run: connect to the robot and check its health.

Run:
    python src/quickstart.py            # against the simulator (safe default)
    python src/quickstart.py --live     # against the real robot

Maps to tutorial sections 3-4: connecting to the robot and the response pattern.
This example is read-only -- it never moves the arm, so no take-control or unbrake.
"""
import argparse

from _client import add_common_args, build_sdk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Connect to the robot and run a health check."
    )
    add_common_args(parser)
    args = parser.parse_args()

    sdk = build_sdk(args)

    # The SDK is configured but not connected yet. Every call must run inside
    # this context manager, which opens (and cleanly closes) the connection.
    with sdk.connection():
        # Every SDK call returns a Response object. There are two ways to use it.

        # (a) Raw inspection. The Response exposes .status (the HTTP status code)
        #     and .data (the parsed payload). Check the status yourself, then read
        #     .data on success or report what went wrong. This is the explicit form
        #     -- handy when you want to branch on failures instead of raising.
        resp = sdk.status.health.get_health()
        if resp.status == 200:
            print(f"Raw response OK (status {resp.status}); health is {resp.data.health}.")
        else:
            print(f"Raw response NOT OK (status {resp.status}): {resp.data}")
            return

        # (b) The concise unwrap. Calling .ok() asserts the status is 200 and
        #     returns the payload directly (raising if it is not). This is the
        #     form you will use most -- one line, no manual status check.
        health = sdk.status.health.get_health().ok()
        print(f"Unwrapped health: {health.health}")

        # Friendly summary so a first run shows everything worked.
        print()
        print("Connection works! You are talking to the robot's REST API.")
        print(f"  Reported health: {health.health}")
        print(f"  Build:           {health.build}")
        print("Next: try src/read_state.py to inspect the arm's position.")


if __name__ == "__main__":
    main()
