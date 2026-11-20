"""Offline OB1 conformance handlers, not production dispatch or endpoint support.

Only admit_claim has an injected record-storage callback. resume never calls its
effect callback. Consumers must implement their own authorized source reads.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/ops-dispatch.v1.schema.json").read_text())
KEY_FIELDS = ("repository", "spec", "ticket", "subject", "approval", "action",
              "destination", "assignment", "prior_verdict", "head", "sequence")
KEYWORDS = {"$schema", "$defs", "$ref", "title", "description", "type", "required",
            "properties", "additionalProperties", "items", "enum", "const", "oneOf",
            "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"}


def _node(reference):
    if not reference.startswith("#/$defs/") or reference[8:] not in SCHEMA["$defs"]:
        raise ValueError("unresolved schema reference")
    return SCHEMA["$defs"][reference[8:]]


def lint_schema():
    """Reject unimplemented schema keywords, including in unused definitions."""
    def walk(node):
        if set(node) - KEYWORDS:
            raise ValueError("unsupported schema keyword")
        if "$ref" in node:
            _node(node["$ref"])
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False or set(node["required"]) != set(node["properties"]):
                raise ValueError("records require exact keys")
        for group in ("$defs", "properties"):
            for child in node.get(group, {}).values():
                walk(child)
        for child in node.get("oneOf", []):
            walk(child)
        if "items" in node:
            walk(node["items"])
    walk(SCHEMA)


def _equal(left, right):
    return type(left) is type(right) and left == right


def _validate(node, value):
    if "$ref" in node:
        _validate(_node(node["$ref"]), value)
    if "oneOf" in node:
        matches = 0
        for choice in node["oneOf"]:
            try:
                _validate(choice, value)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError("record must match exactly one variant")
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    if "type" in node and type(value) is not types[node["type"]]:
        raise ValueError("wrong field type")
    if "const" in node and not _equal(value, node["const"]):
        raise ValueError("wrong constant")
    if "enum" in node and not any(_equal(value, item) for item in node["enum"]):
        raise ValueError("unknown enum")
    if type(value) is dict and "properties" in node:
        if set(value) != set(node["required"]):
            raise ValueError("missing or extra keys")
        for key, child in value.items():
            _validate(node["properties"][key], child)
    if type(value) is list:
        if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", len(value)):
            raise ValueError("array bounds")
        for child in value:
            if "items" in node:
                _validate(node["items"], child)
    if type(value) is str:
        if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", len(value)):
            raise ValueError("string bounds")
        if "pattern" in node and re.fullmatch(node["pattern"], value, re.ASCII) is None:
            raise ValueError("invalid string form")
    if type(value) is int and not node.get("minimum", value) <= value <= node.get("maximum", value):
        raise ValueError("integer bounds")


def operation_key(intent):
    identity = {key: intent[key] for key in KEY_FIELDS}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(b"openwiz.ops-operation.v1\n" + canonical.encode()).hexdigest()


def claim_ref(claim):
    prefix = f"refs/heads/openwiz-ops/v1/s-{claim['spec']}"
    if claim["scope"] == "generation":
        return f"{prefix}/generations/g-{claim['generation']}"
    return f"{prefix}/operations/g-{claim['generation']}/k-{claim['operation_key']}"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate wire key")
        result[key] = value
    return result


def _non_integer(_):
    raise ValueError("non-integer JSON number")


def read_record(raw):
    value = json.loads(raw, object_pairs_hook=_pairs, parse_float=_non_integer,
                       parse_constant=_non_integer)
    _validate(SCHEMA, value)
    kind = value["kind"]
    for entry in value.get("paths", []) + value.get("supporting", []):
        if any(part in ("", ".", "..") for part in entry["path"].split("/")):
            raise ValueError("noncanonical repository path")
    paths = [entry["path"] for entry in value.get("paths", []) + value.get("supporting", [])]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate path")
    if kind == "envelope" and set(value["protected"]) != {
        "contracts", "interfaces", "dependencies", "workflows", "live", "spending", "self_authorization"
    }:
        raise ValueError("missing protected gate")
    if kind == "intent" and value["operation_key"] != operation_key(value):
        raise ValueError("operation identity mismatch")
    if kind == "claim":
        if value["generation"] != value["previous_generation"] + 1 or value["ref"] != claim_ref(value):
            raise ValueError("claim generation or ref mismatch")
        if value["scope"] == "generation" and (value["operation_key"] != "0" * 64 or value["intent_id"] is not None):
            raise ValueError("generation claim must use sentinel identity")
        if value["scope"] == "operation" and value["intent_id"] is None:
            raise ValueError("operation claim needs durable intent")
    if kind == "completion" and (value["state"] == "superseded") != (value["superseded_by"] is not None):
        raise ValueError("supersession binding")
    return value


def read_comment(body, container):
    blocks = re.findall(r"^```json\n(.*?)\n```$", body, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1 or body.count("```") != 2:
        raise ValueError("ambiguous or malformed record fence")
    record = read_record(blocks[0])
    if "subject" not in record or (record["repository"], record["subject"]["kind"], record["subject"]["number"]) != container:
        raise ValueError("record container mismatch")
    return record


def _checked(value):
    return read_record(json.dumps(value))


def _binding(record, snapshot):
    return all(record[key] == snapshot[key] for key in ("repository", "spec", "ticket", "approval"))


def admit_claim(claim, snapshot, record_commit, create_if_absent):
    """One storage attempt, never update/delete, dispatch, or mutation retry."""
    _checked(claim)
    _checked(snapshot)
    if claim["kind"] != "claim" or snapshot["kind"] != "snapshot" or re.fullmatch("[0-9a-f]{40}", record_commit) is None:
        raise ValueError("wrong claim inputs")
    if not snapshot["complete"] or not _binding(claim, snapshot):
        return "refused"
    if snapshot["paused"] or snapshot["revoked"]:
        return "refused"
    if claim["scope"] == "generation":
        if claim["previous_generation"] != snapshot["generation"]:
            return "stale"
    else:
        if claim["generation"] != snapshot["generation"] or claim["owner"] != snapshot["owner"]:
            return "stale"
        if snapshot["uncertain_keys"]:
            return "reconcile"
        intents = [item for item in snapshot["intents"] if item["id"] == claim["intent_id"]]
        if len(intents) != 1:
            return "refused"
        intent = _checked(intents[0])
        if not _binding(intent, snapshot) or intent["operation_key"] != claim["operation_key"] or intent["head"] != snapshot["head"]:
            return "refused"
    try:
        outcome = create_if_absent(claim["ref"], record_commit)
    except Exception:
        return "uncertain"
    if type(outcome) is not str:
        return "uncertain"
    return {"created": "admitted", "exists": "duplicate"}.get(outcome, "uncertain")


def resume(intent, claim, history, snapshot, effect_boundary):
    """Finite refusal stub. effect_boundary is never called, even if supplied."""
    for item in [intent, claim, snapshot, *history]:
        _checked(item)
    if (intent["kind"] != "intent" or claim["kind"] != "claim" or claim["scope"] != "operation"
            or snapshot["kind"] != "snapshot"
            or any(item["kind"] not in {"intent", "admission", "transport", "ack", "completion"} for item in history)):
        raise ValueError("wrong resume records")
    ids = [item["id"] for item in history if "id" in item]
    if len(set(ids)) != len(ids):
        raise ValueError("ambiguous duplicate record identity")
    result = dict(schema="openwiz.ops-dispatch.v1", kind="result", operation_key=intent["operation_key"],
                  intent_id=intent["id"], state="disabled", reason="unfenced_effect", next="end", effects=[])
    def end(state, reason):
        return dict(result, state=state, reason=reason)
    relevant = [item for item in history if item.get("operation_key") == intent["operation_key"]]
    def belongs_to_intent(item):
        return item.get("intent_id", intent["id"]) == intent["id"] and _binding(item, intent)
    # Accepted transport without endpoint completion is uncertain too. A later
    # refusal, acknowledgement, new generation or lease expiry cannot erase it.
    if snapshot["uncertain_keys"] or any(
        belongs_to_intent(item) and (
            (item["kind"] == "transport" and item["state"] in ("accepted", "uncertain"))
            or (item["kind"] == "completion" and item["state"] in ("uncertain", "completed", "reconciled_not_executed")))
        for item in relevant
    ):
        return end("reconcile", "uncertain_outcome")
    if any(not belongs_to_intent(item) for item in relevant):
        return end("refused", "stale_binding")
    if not snapshot["complete"]:
        return end("refused", "incomplete_read")
    if not _binding(intent, snapshot) or not _binding(claim, snapshot) or intent["head"] != snapshot["head"]:
        return end("refused", "stale_binding")
    if claim["intent_id"] != intent["id"] or claim["operation_key"] != intent["operation_key"]:
        return end("refused", "stale_binding")
    if claim["generation"] != snapshot["generation"] or claim["owner"] != snapshot["owner"]:
        return end("refused", "stale_claim")
    if snapshot["paused"] or snapshot["revoked"] or snapshot["gates"]:
        return end("refused", "paused_or_revoked")
    if any(item["kind"] == "completion" and item["state"] == "superseded" for item in relevant):
        return end("superseded", "superseded")
    if intent["sequence"] != snapshot["next_sequence"]:
        return end("deferred", "out_of_order")
    return copy.deepcopy(result)


def grant_current(grant, snapshot):
    """Material equality only; not agent approval of the diff or edit authority."""
    _checked(grant)
    _checked(snapshot)
    return (grant["kind"] == "grant" and snapshot["complete"] and grant["status"] == "granted"
            and grant["rule"]["name"] == "narrow-grant"
            and _binding(grant, snapshot) and grant["material"] == snapshot["material"]
            and grant["rule"] == snapshot["rule"]
            and grant["rule"]["revision"] == grant["material"]["rule_digest"])


def on1_current(record, snapshot):
    """Current evidence-record check only; never release or approval authority."""
    _checked(record)
    _checked(snapshot)
    return (record["kind"] == "on1" and snapshot["complete"] and _binding(record, snapshot)
            and record["rule"]["name"] == "on1" and record["rule"] == snapshot["rule"]
            and record["cutoff"]["inclusive"] and record["cutoff"]["complete"]
            and record["cutoff"]["end"] == snapshot["cutoff"]
            and record["cutoff"]["changes"] == snapshot["cutoff_changes"]
            and record["producer"] == snapshot["producer"]
            and record["consumers"] == snapshot["consumers"]
            and record["hold"]["history_digest"] == snapshot["history_digest"]
            and snapshot["holds"] == [record["hold"]["comment"]] and not snapshot["gates"]
            and record["verification"]["history_complete"] and not record["other_gates"]
            and not record["competing_claims"])


def audit_cursor(report):
    """Proposed cursor, to save only after the complete report is read back."""
    _checked(report)
    if report["kind"] != "audit":
        raise ValueError("not an audit")
    start, end = report["start"], report["end"]
    if (end["created_at"], end["comment"]) < (start["created_at"], start["comment"]):
        raise ValueError("audit cursor moves backwards")
    return copy.deepcopy(end if report["complete"] else start)


lint_schema()
