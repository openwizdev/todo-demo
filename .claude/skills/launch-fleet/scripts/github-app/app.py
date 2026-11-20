"""Shared guards for the App tools. No credentials are logged."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

# mint-token.py's downscoped read-only token for the live read check.
PERMISSIONS = dict.fromkeys(
    ("metadata", "contents", "issues", "pull_requests", "checks", "actions"), "read")
# The service App's established profile (crates/adapters/github/src/app.rs):
# what the App is registered and installed with (#1105).
SERVICE = dict(PERMISSIONS, contents="write", issues="write", pull_requests="write")
# J48 (#606): the explicit setting for the factory's public multi-account App.
# Unset (or "user") is each user's own private App, bound to its owner's account.
MODE = "OPENWIZ_GITHUB_APP_MODE"
# contracts/github-identity.v1.md's pinned installations, carried with the tool
# so the installed runtime needs no contracts/ folder (review R1): each account
# and the repository names it selects. test.py holds this to the pin exactly.
FACTORY = {"jparker2006": ("ClosedWiz",), "openwizdev": ("OpenWiz", "WizPlugins", "WizSkills")}


def factory_installations():
    """The only installations factory mode accepts: {account: {owner/name, ...}}, lower case."""
    return {account: {f"{account}/{name}".lower() for name in names} for account, names in FACTORY.items()}


def require(condition):
    if not condition:
        raise ValueError("App safety check failed")


def object_once(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def parse_json(data):
    value = json.loads(data, object_pairs_hook=object_once)
    require(isinstance(value, dict))
    return value


def permissions(value):
    require(value == PERMISSIONS)


def service_permissions(value):
    require(value == SERVICE)


REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
ORIGIN = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                    r"([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?")


def repository(explicit):
    """OWNER/NAME: --repo, or else the GitHub origin of the clone holding this tool."""
    if explicit is None:
        proc = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent),
                               "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
        require(proc.returncode == 0)
        match = ORIGIN.fullmatch(proc.stdout.strip())
        require(match is not None)
        explicit = match.group(1)
    require(REPOSITORY.fullmatch(explicit) is not None and explicit.split("/")[1] not in (".", ".."))
    return explicit


def mode():
    """The App setting from the environment: "user" (unset) or exactly "factory"."""
    value = os.environ.get(MODE, "user")
    require(value in ("user", "factory"))
    return value


def user_app_name(account):
    """A user's own App's name: GitHub names are unique and at most 34 characters,
    and the factory's "OpenWiz" is taken, so Create needs no edit."""
    name = "OpenWiz " + account
    if len(name) <= 34:
        return name
    return "OpenWiz " + account[:17] + " " + hashlib.sha256(account.lower().encode()).hexdigest()[:8]


def bound(setting, app_owner, account, repositories):
    """C-G1/J48: may this App mint for ACCOUNT's installation and these repositories?
    A user App only on its owner's account, for repositories that account owns;
    the factory App only on the identity contract's named installations."""
    account = account.lower() if isinstance(account, str) else None
    if account is None or not repositories:
        return False
    if setting == "factory":
        named = factory_installations()
        return all(r.lower() in named.get(account, ()) for r in repositories)
    return (isinstance(app_owner, str) and app_owner.lower() == account
            and all(r.lower().split("/")[0] == account for r in repositories))


def manifest(repo=None, factory=False, account=None):
    """The checked template, private by default (J48). With ACCOUNT, a user App's
    own name; FACTORY is the explicit setting for the factory's public App. With
    REPO, its homepage and disabled webhook name that repository."""
    value = parse_json(Path(__file__).with_name("manifest.json").read_bytes())
    service_permissions(value.get("default_permissions"))
    require(value.get("default_events") == [])
    require("url" not in value and value.get("hook_attributes") == {"active": False})
    require(value.get("public") is False and value.get("name") == "OpenWiz")
    if factory:
        value = dict(value, public=True)
    elif account is not None:
        value = dict(value, name=user_app_name(account))
    if repo is not None:
        # GitHub's manifest schema requires url whenever hook_attributes is present.
        url = "https://github.com/" + repository(repo)
        value = dict(value, url=url, hook_attributes={"url": url, "active": False})
    return value


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--state-dir", type=Path, help="absolute PC OpenWiz state directory")
    parser.add_argument("--api-base", default="https://api.github.com",
                        help="GitHub API; HTTP loopback accepted for synthetic tests only")
    return parser


def state_path(explicit):
    if explicit is not None:
        path = explicit
    elif os.environ.get("OPENWIZ_STATE_DIR"):
        path = Path(os.environ["OPENWIZ_STATE_DIR"])
    else:
        xdg = Path(os.environ.get("XDG_STATE_HOME", ""))
        path = (xdg if xdg.is_absolute() else Path.home() / ".local/state") / "openwiz"
    require(path.is_absolute())
    # State must never be placed in a repository, including a worktree.
    for parent in (path, *path.parents):
        require(not parent.is_symlink())
        require(not (parent / ".git").exists())
        require(not ((parent / "HEAD").exists() and
                     ((parent / "objects").exists() or (parent / "config").exists())))
    return path


def checked(fd, directory=False):
    info = os.fstat(fd)
    require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)
    require(stat.S_ISDIR(info.st_mode) if directory else
            stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    return fd


def app_directory(path, create=False):
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        checked(fd, directory=True)
        for component in ("service", "app"):
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            try:
                checked(child, directory=True)
            except Exception:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def read_file(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        checked(fd)
        require(os.fstat(fd).st_size <= limit)
        with os.fdopen(os.dup(fd), "rb") as file:
            content = file.read(limit + 1)
        require(len(content) <= limit)
        return content
    finally:
        os.close(fd)


def absent(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError("App already configured")


def save_file(directory, name, content):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        os.unlink(name, dir_fd=directory)
        raise


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def api_base(value):
    if value != "https://api.github.com":
        parts = urllib.parse.urlsplit(value)
        require(parts.scheme == "http" and parts.hostname == "127.0.0.1")
        require(parts.port is not None and parts.netloc == f"127.0.0.1:{parts.port}")
        require(not parts.path and not parts.query and not parts.fragment)
    return value


def post(base, path, body=None, jwt=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "OpenWiz-App-setup",
               "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = "Bearer " + jwt
    request = urllib.request.Request(api_base(base) + path,
                                     data=json.dumps(body or {}).encode(),
                                     headers=headers, method="POST")
    # Never follow redirects or echo a response body, URL, JWT or exception.
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        require(response.status == 201)
        data = response.read(1024 * 1024 + 1)
        require(len(data) <= 1024 * 1024)
        return parse_json(data)


def get(base, path, jwt):
    """One App read with a JWT: (status, JSON or None). Never echoes a body."""
    request = urllib.request.Request(api_base(base) + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "OpenWiz-App-setup",
        "X-GitHub-Api-Version": "2022-11-28", "Authorization": "Bearer " + jwt}, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            status, data = response.status, response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        return error.code, None
    require(len(data) <= 1024 * 1024)
    return status, parse_json(data) if status == 200 else None


def openssl(args, data, **kwargs):
    result = subprocess.run(["openssl", *args], input=data, capture_output=True,
                            timeout=10, **kwargs)
    require(result.returncode == 0)
    return result.stdout


def encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def jwt(directory, app_id):
    require(type(app_id) is int and app_id > 0)
    fd = os.open("private-key.pem", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                 dir_fd=directory)
    try:
        checked(fd)
        require(0 < os.fstat(fd).st_size <= 16384)
        now = int(time.time())
        header = encode(b'{"alg":"RS256","typ":"JWT"}')
        payload = encode(json.dumps({"iat": now - 60, "exp": now + 540,
                                     "iss": str(app_id)}, separators=(",", ":")).encode())
        message = header + b"." + payload
        signature = openssl(["dgst", "-sha256", "-sign", f"/dev/fd/{fd}"],
                            message, pass_fds=(fd,))
        return (message + b"." + encode(signature)).decode("ascii")
    finally:
        os.close(fd)


def positive_id(value):
    require(re.fullmatch(r"[1-9][0-9]*", value) is not None)
    return value
