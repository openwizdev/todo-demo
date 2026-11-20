"""Read a saved grill proposal and maintain its private decision request."""
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "openwiz.decisions.v1"
ROUND = "grill_round"
SUMMARY = "grill_confirmation"
RISKS = ("ordinary", "live", "release", "publish")
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]*"
QUESTION = r"[A-Z]{1,2}[1-9][0-9]*"
FILE = r"docs/grills/[A-Za-z0-9][A-Za-z0-9_.-]*\.md"
FENCE = re.compile(r"^\x60\x60\x60json\n(.*?)\n\x60\x60\x60$", re.M | re.S)
HEADER = b"openwiz decision answer v1"


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def decode(data):
    return json.loads(data, object_pairs_hook=unique_object)


def compact(value, *, sort_keys=False):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)


def fingerprint(record):
    proposal = {key: value for key, value in record.items()
                if key not in ("fingerprint", "status", "answered")}
    return hashlib.sha256(compact(proposal, sort_keys=True).encode()).hexdigest()


def run(args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=45, check=True)
    return result.stdout


def proposal_lines(lines):
    for line in lines:
        if line.startswith("**") and line.endswith(":**"):
            break
        yield line


def questions(lines):
    pending = None
    result = []
    for line in proposal_lines(lines):
        if pending is None:
            if not line:
                continue
            match = re.fullmatch(r"\*\*(" + QUESTION + r")(?:, re-asked)? - (.+?)\*\* (.*)", line)
            require(match, "unreadable saved question")
            key, decides, context = match.groups()
            pending = {"id": key, "decides": decides, "context": context}
        elif line.startswith("➡️ "):
            require(pending["context"] and line[3:], "incomplete saved question")
            result.append(pending | {"recommendation": line[3:]})
            pending = None
        else:
            require(not line.startswith("**"), "unreadable saved question context")
            pending["context"] += "\n" + line
    require(pending is None and 1 <= len(result) <= 3, "expected one to three saved questions")
    require(len({item["id"] for item in result}) == len(result), "duplicate saved question")
    return result


def summary(lines):
    result = []
    for line in proposal_lines(lines):
        if not line:
            continue
        prefix = f"{len(result) + 1}. "
        require(line.startswith(prefix) and line[len(prefix):], "unreadable saved summary")
        result.append(line[len(prefix):])
    require(1 <= len(result) <= 10, "expected one to ten saved decisions")
    return result


def latest(source):
    require(source.startswith("# Grill: ") and "\r" not in source, "unreadable saved grill")
    sections = re.split(r"^## ", source, flags=re.M)[1:]
    selected = None
    previous_round = 0
    for section in sections:
        heading, *lines = section.split("\n")
        if heading.startswith("Round "):
            match = re.fullmatch(r"Round ([1-9][0-9]*)", heading)
            require(match and int(match[1]) > previous_round, "unreadable saved round order")
            previous_round = int(match[1])
            selected = (ROUND, previous_round, lines)
        elif heading.startswith("Summary"):
            require(re.fullmatch(r"Summary(?:, corrected)?(?: \(shown to .+ for confirmation\))?",
                                 heading), "unreadable saved summary heading")
            selected = (SUMMARY, None, lines)
    require(selected, "no saved round or summary")
    kind, number, lines = selected
    require(lines, "unreadable saved proposal")
    risk = lines[0].removeprefix("Risk: ")
    risk = risk if lines[0] == f"Risk: {risk}" and risk in RISKS else "unknown"
    wording = lines[1:] if lines[0].startswith("Risk:") else lines
    require(not any(line.lstrip().startswith(("Risk:", "\x60\x60\x60", "~~~")) for line in wording),
            "ambiguous saved risk or wording")
    fields = ({"round": number, "questions": questions(wording), "answered": []}
              if kind == ROUND else {"summary": summary(wording)})
    return {"kind": kind, "risk": risk} | fields, wording



def saved_answers(wording, questions):
    settled = set()
    for line in wording:
        if line.startswith("Settled: "):
            labels = line.split(". Open:", 1)[0].removeprefix("Settled: ")
            settled.update(re.findall(r"\b(" + QUESTION + r")\b", labels.split(" (", 1)[0]))
    return [item["id"] for item in questions if item["id"] in settled]


def parse_comment(body):
    found = []
    for match in FENCE.finditer(body):
        try:
            record = decode(match[1])
        except (ValueError, Refusal):
            require(SCHEMA not in match[1], "malformed decision request")
            continue
        if isinstance(record, dict) and record.get("schema") == SCHEMA:
            found.append((match, record))
    require(len(found) <= 1, "ambiguous decision comment")
    return found[0] if found else (None, None)


def validate(record, file):
    common = {"schema", "id", "kind", "status", "fingerprint", "risk", "grill_file"}
    require(record.get("grill_file") == file
            and isinstance(record.get("id"), str) and re.fullmatch(IDENTIFIER, record["id"])
            and record.get("risk") in (*RISKS, "unknown")
            and record.get("status") in ("open", "resolved", "superseded"),
            "invalid decision identity")
    if record["kind"] == ROUND:
        require(record.keys() == common | {"round", "questions", "answered"}
                and type(record["round"]) is int and record["round"] > 0
                and isinstance(record["questions"], list) and 1 <= len(record["questions"]) <= 3,
                "invalid round record")
        ids = []
        for item in record["questions"]:
            require(isinstance(item, dict)
                    and item.keys() == {"id", "decides", "context", "recommendation"}
                    and all(isinstance(value, str) and value for value in item.values())
                    and re.fullmatch(QUESTION, item["id"]) and item["id"] not in ids,
                    "invalid question record")
            ids.append(item["id"])
        answered = record["answered"]
        require(isinstance(answered, list) and answered == [key for key in ids if key in answered]
                and (record["status"] == "superseded"
                     or (record["status"] == "resolved") == (answered == ids)),
                "invalid saved progress")
    else:
        require(record["kind"] == SUMMARY and record.keys() == common | {"summary"}
                and isinstance(record["summary"], list) and 1 <= len(record["summary"]) <= 10
                and all(isinstance(line, str) and line and "\r" not in line and "\n" not in line
                        for line in record["summary"]), "invalid summary record")
    require(record["fingerprint"] == fingerprint(record), "invalid decision fingerprint")


class Grill:
    def __init__(self, repo, pr, file):
        self.repo, self.pr, self.file = repo, pr, file
        self.base = f"repos/{repo}"
        self.comments = f"{self.base}/issues/{pr}/comments"
        self.issue_url = f"https://api.github.com/{self.base}/issues/{pr}"
        require(re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repo)
                and pr > 0 and re.fullmatch(FILE, file), "invalid private target")
        remote = run(["git", "remote", "get-url", "origin"]).decode().rstrip("\n")
        require(any(remote.removesuffix(".git").lower() == (prefix + repo).lower()
                    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/")),
                "private checkout origin does not match")
        self.privacy()
        self.head = self.read_head()
        blob = self.api(f"{self.base}/contents/{file}?ref={self.head}")
        require(blob.get("path") == file and blob.get("encoding") == "base64",
                "saved grill is unreadable")
        self.source = base64.b64decode(blob["content"].replace("\n", ""), validate=True).decode()

    @staticmethod
    def api(endpoint, *flags, method=None, body=None):
        effect = [] if method is None else ["-X", method, "--input", "-"]
        data = None if body is None else compact({"body": body}).encode()
        return decode(run(["gh", "api", *effect, *flags, endpoint], data))

    def privacy(self):
        try:
            repo = self.api(self.base)
        except (subprocess.SubprocessError, ValueError, Refusal, OSError):
            raise Refusal("repository privacy could not be verified") from None
        require(repo.get("private") is True and repo.get("visibility") == "private"
                and repo.get("full_name", "").lower() == self.repo.lower(),
                "repository privacy could not be verified")

    def read_head(self):
        pr = self.api(f"{self.base}/pulls/{self.pr}")
        require(type(pr.get("number")) is int and pr["number"] == self.pr
                and pr["head"]["repo"]["full_name"].lower() == self.repo.lower()
                and re.fullmatch(r"[a-f0-9]{40}", pr["head"]["sha"]), "unreadable private PR head")
        self.is_open = pr.get("state") == "open"
        return pr["head"]["sha"]

    def check_head(self, *, open_pr=True):
        require(self.read_head() == self.head and (self.is_open or not open_pr),
                "private PR closed or moved; read current state")

    def list_request(self, request_id):
        matches = []
        pages = self.api(self.comments, "--paginate", "--slurp")
        require(isinstance(pages, list) and all(isinstance(page, list) for page in pages),
                "incomplete comments read")
        for page in pages:
            for comment in page:
                _, record = parse_comment(comment["body"])
                if record and record.get("id") == request_id:
                    require(comment["issue_url"] == self.issue_url, "wrong comment subject")
                    matches.append(comment["id"])
        require(len(matches) <= 1, "ambiguous request identity")
        return matches[0] if matches else None

    def comment(self, comment_id):
        require(type(comment_id) is int and comment_id > 0, "invalid comment id")
        endpoint = f"{self.base}/issues/comments/{comment_id}"
        comment = self.api(endpoint)
        require(comment["id"] == comment_id and comment["issue_url"] == self.issue_url,
                "wrong comment subject")
        body = comment["body"]
        match, record = parse_comment(body)
        require(record, "no decision request at exact comment")
        validate(record, self.file)
        return endpoint, body, match, record

    def proposal(self, request_id):
        fields, wording = latest(self.source)
        record = {"schema": SCHEMA, "id": request_id, "status": "open",
                  "grill_file": self.file} | fields
        record["fingerprint"] = fingerprint(record)
        validate(record, self.file)
        return record, wording

    def status(self):
        line = self.source.split("\n")[2]
        matches = re.findall(r"Status: \*\*(open|parked|confirmed)\*\*", line)
        require(line.count("Status:") == 1 and len(matches) == 1, "unreadable grill status")
        return matches[0]

    def publish(self, request_id):
        require(re.fullmatch(IDENTIFIER, request_id), "invalid request id")
        record, _ = self.proposal(request_id)
        self.check_head()
        comment_id = self.list_request(request_id)
        if comment_id is None:
            require(self.status() == "open", "grill is not open")
            self.privacy()
            self.check_head()
            self.remember_attempt(request_id)
            try:
                self.api(self.comments, method="POST", body=f"\x60\x60\x60json\n{compact(record)}\n\x60\x60\x60")
            except (subprocess.SubprocessError, ValueError, Refusal, OSError):
                pass  # The effect is uncertain until the same PR reads it back.
            comment_id = self.list_request(request_id)
        require(comment_id is not None, "write unresolved; reconcile the same request id")
        _, _, _, saved = self.comment(comment_id)
        require(saved["fingerprint"] == record["fingerprint"] and saved["status"] != "superseded",
                "existing request differs; inspect before continuing")
        self.check_head()
        print(f"verified request {comment_id} ({saved['status']})")

    def remember_attempt(self, request_id):
        # Common Git dir covers linked worktrees. Record the intent before POST.
        git_dir = Path(run(["git", "rev-parse", "--git-common-dir"]).decode().rstrip("\n"))
        marker = git_dir / "grill-requests" / hashlib.sha256(
            f"{self.repo.lower()}:{request_id}".encode()).hexdigest()
        marker.parent.mkdir(mode=0o700, exist_ok=True)
        try:
            with marker.open("xb"):
                pass
            fd = os.open(marker.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except FileExistsError:
            raise Refusal("prior write unresolved; reconcile the same request id") from None

    def verify_current(self, record, comment_id):
        current, wording = self.proposal(record["id"])
        require(record["fingerprint"] == current["fingerprint"], "request is stale")
        require(self.list_request(record["id"]) == comment_id, "request identity is unresolved")
        return wording

    def match_answer(self, message, output):
        header, sep, rest = message.partition(b"\n")
        context, boundary, payload = rest.partition(b"\n\n")
        require(header == HEADER and sep and boundary and b"\n" not in context,
                "invalid contextual answer framing")
        raw = decode(context)
        require(isinstance(raw, dict), "invalid contextual answer shape")
        comment_id = raw.get("comment_id")
        _, _, _, record = self.comment(comment_id)
        expected = {
            "subject": {"repository": self.repo, "kind": "pull_request", "number": self.pr},
            "comment_id": comment_id, "request_id": record["id"], "request_kind": record["kind"],
            "fingerprint": record["fingerprint"], "grill_file": self.file,
        }
        locator = "summary"
        if record["kind"] == ROUND:
            locator = raw.get("question_id")
            require(locator in [q["id"] for q in record["questions"]]
                    and locator not in record["answered"], "question is absent or already answered")
            expected.update(round=record["round"], question_id=locator)
        require(compact(raw).encode() == context and compact(raw) == compact(expected),
                "context does not match the saved private request")
        require(self.status() == "open" and record["status"] == "open" and record["risk"] != "unknown",
                "request is closed or saved risk is unknown")
        wording = self.verify_current(record, comment_id)
        if record["kind"] == ROUND:
            require(locator not in saved_answers(wording, record["questions"]),
                    "question already has a saved answer")
        self.check_head()
        payload.decode()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        print(f"matched {locator}")

    def advance(self, comment_id, requested):
        target = self.comment(comment_id)
        record = target[3]
        require(record["status"] in ("open", "resolved"), "request is superseded")
        wording = self.verify_current(record, comment_id)
        require(any(line.startswith(">") for line in wording), "exact reply is not saved")
        if record["kind"] == ROUND:
            ids = [item["id"] for item in record["questions"]]
            answered = saved_answers(wording, record["questions"])
            require(requested == answered and set(record["answered"]) <= set(answered),
                    "answer ids do not match saved progress")
            updated = record | {"answered": answered,
                                "status": "resolved" if answered == ids else "open"}
        else:
            require(requested == ["confirmed"] and self.status() == "confirmed",
                    "latest summary confirmation is not saved")
            updated = record | {"status": "resolved"}
        self.patch(comment_id, target, updated, open_pr=True)

    def supersede(self, comment_id):
        target = self.comment(comment_id)
        record = target[3]
        require(record["status"] in ("open", "superseded"), "resolved request stays resolved")
        self.patch(comment_id, target, record | {"status": "superseded"}, open_pr=False)

    def patch(self, comment_id, original, updated, *, open_pr):
        endpoint, body, match, record = original
        self.privacy()
        self.check_head(open_pr=open_pr)
        require(self.list_request(record["id"]) == comment_id
                and self.comment(comment_id)[1] == body, "comment changed; read current state")
        if updated != record:
            replacement = body[:match.start(1)] + compact(updated) + body[match.end(1):]
            try:
                self.api(endpoint, method="PATCH", body=replacement)
            except (subprocess.SubprocessError, ValueError, Refusal, OSError):
                pass
            require(self.comment(comment_id)[1] == replacement,
                    "update unresolved; read the exact comment")
        self.check_head(open_pr=open_pr)
        print(f"verified {updated['status']} {comment_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_repo")
    parser.add_argument("pr", type=int)
    parser.add_argument("grill_file")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("publish").add_argument("request_id")
    match = commands.add_parser("match")
    match.add_argument("message", type=Path)
    match.add_argument("output", type=Path)
    advance = commands.add_parser("advance")
    advance.add_argument("comment_id", type=int)
    advance.add_argument("answered", nargs="*")
    commands.add_parser("supersede").add_argument("comment_id", type=int)
    args = parser.parse_args()
    try:
        grill = Grill(args.private_repo, args.pr, args.grill_file)
        if args.action == "publish":
            grill.publish(args.request_id)
        elif args.action == "match":
            grill.match_answer(args.message.read_bytes(), args.output)
        elif args.action == "advance":
            grill.advance(args.comment_id, args.answered)
        else:
            grill.supersede(args.comment_id)
    except Refusal as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, binascii.Error,
            subprocess.SubprocessError, OSError):
        print("refused: required data or effect could not be verified", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
