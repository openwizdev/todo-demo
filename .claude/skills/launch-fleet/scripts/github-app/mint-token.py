#!/usr/bin/env python3
"""Mint one read-only installation token on the PC, downscoped to the selected repositories.

--repository is required (C8, #2315): the token covers exactly those selected
repositories of one owner. Stdout is two lines: the token, then its expiry in
Unix seconds. Agent reads use this through tools/github-reads/read.py only.

The installation is read back first (C-G1/J48, #606): a user's own App mints
only on its owner's account; OPENWIZ_GITHUB_APP_MODE=factory is the explicit
setting for the factory's App and its named installations only.
"""
from datetime import datetime, timezone
import os
import re
import sys

import app


def main():
    parser = app.arguments(__doc__)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--repository", action="append", default=[],
                        help="OWNER/NAME (required, repeatable): downscope the read token to this selected repository")
    args = parser.parse_args()
    if not args.repository:
        print("App token refused: --repository is required.", file=sys.stderr)
        sys.exit(1)
    selected = sorted(app.repository(name).lower() for name in args.repository)
    app.require(len(set(selected)) == len(selected) and
                len({name.split("/")[0] for name in selected}) <= 1)
    body = {"permissions": app.PERMISSIONS,
            "repositories": [name.split("/")[1] for name in selected]}
    app.api_base(args.api_base)
    app.manifest()
    setting = app.mode()
    installation = app.positive_id(args.installation_id)
    directory = app.app_directory(app.state_path(args.state_dir))
    try:
        config = app.parse_json(app.read_file(directory, "app.json", 1024))
        app.require(set(config) == {"app_id"})
        jwt = app.jwt(directory, config["app_id"])
        # The App's owner and the installation's account, before any token exists.
        status, found = app.get(args.api_base, "/app", jwt)
        app.require(status == 200 and found.get("id") == config["app_id"])
        status, held = app.get(args.api_base, f"/app/installations/{installation}", jwt)
        app.require(status == 200 and held.get("id") == int(installation)
                    and held.get("app_id") == config["app_id"]
                    and held.get("repository_selection") == "selected")
        app.require(app.bound(setting, (found.get("owner") or {}).get("login"),
                              (held.get("account") or {}).get("login"), selected))
        result = app.post(args.api_base, f"/app/installations/{installation}/access_tokens",
                          body, jwt)
    finally:
        os.close(directory)
    app.permissions(result.get("permissions"))
    token = result.get("token")
    app.require(isinstance(token, str) and
                re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is not None)
    expiry = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
    remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
    # GitHub stamps expiry on its clock; tolerate five minutes of PC drift.
    app.require(0 < remaining <= 3600 + 300)
    # Exactly the requested selection, nothing wider or foreign.
    listed = result.get("repositories")
    app.require(result.get("repository_selection") == "selected" and isinstance(listed, list))
    app.require(all(isinstance(r, dict) and isinstance(r.get("full_name"), str) for r in listed))
    app.require(sorted(r["full_name"].lower() for r in listed) == selected)
    print(token)
    print(int(expiry.timestamp()))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("App token refused: check PC state permissions, App installation and GitHub availability.",
              file=sys.stderr)
        sys.exit(1)
