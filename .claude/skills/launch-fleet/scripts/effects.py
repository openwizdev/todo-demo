"""Shared finite OB3 record admission and effect refusal boundary.

OB-A1 certifies records, never an external effect fence. This module has no
network/process client, enable switch or executable effect path. Consumers
supply authorized complete source reads, verified immutable claim commits,
reference read-back and durable admission/result persistence. Snapshots are
private derived data, not endpoint attestations. See ops-effects/README.md.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((ROOT / "contracts/ops-dispatch.v1.schema.json").read_text())
KEY_FIELDS = ("repository", "spec", "ticket", "subject", "approval", "action",
              "destination", "assignment", "prior_verdict", "head", "sequence")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bad_number(_):
    raise ValueError("non-integer JSON number")


def _validate(node, value):
    # Only the contract's implemented schema subset is accepted. A new keyword
    # must never silently weaken a write guard when the contract advances.
    keywords = {"$schema", "$defs", "$ref", "title", "description", "type", "required",
                "properties", "additionalProperties", "items", "enum", "const", "oneOf",
                "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"}
    if set(node) - keywords:
        raise ValueError("unsupported schema keyword")
    if "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in SCHEMA["$defs"]:
            raise ValueError("unknown schema reference")
        _validate(SCHEMA["$defs"][ref[8:]], value)
    if "oneOf" in node:
        matches = 0
        for choice in node["oneOf"]:
            try:
                _validate(choice, value)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError("ambiguous or unknown record")
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    if "type" in node and type(value) is not types[node["type"]]:
        raise ValueError("wrong JSON type")
    if "const" in node and (type(value) is not type(node["const"]) or value != node["const"]):
        raise ValueError("wrong constant")
    if "enum" in node and not any(type(value) is type(v) and value == v for v in node["enum"]):
        raise ValueError("unknown enum")
    if node.get("type") == "object":
        if (node.get("additionalProperties") is not False
                or set(node["required"]) != set(node["properties"])
                or set(value) != set(node["required"])):
            raise ValueError("missing or extra object fields")
        for key, child in value.items():
            _validate(node["properties"][key], child)
    if type(value) is list:
        if not node.get("minItems", 0) <= len(value) <= node.get("maxItems", len(value)):
            raise ValueError("array bounds")
        for item in value:
            if "items" in node:
                _validate(node["items"], item)
    if type(value) is str:
        if not node.get("minLength", 0) <= len(value) <= node.get("maxLength", len(value)):
            raise ValueError("string bounds")
        if "pattern" in node and re.fullmatch(node["pattern"], value, re.ASCII) is None:
            raise ValueError("invalid string")
    if type(value) is int and not node.get("minimum", value) <= value <= node.get("maximum", value):
        raise ValueError("integer bounds")


def operation_key(intent):
    """Contract identity: no generation, timestamp or random retry salt."""
    identity = {key: intent[key] for key in KEY_FIELDS}
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(b"openwiz.ops-operation.v1\n" + raw.encode("utf-8")).hexdigest()


def claim_ref(claim):
    prefix = f"refs/heads/openwiz-ops/v1/s-{claim['spec']}"
    if claim["scope"] == "generation":
        return f"{prefix}/generations/g-{claim['generation']}"
    return f"{prefix}/operations/g-{claim['generation']}/k-{claim['operation_key']}"


def read_record(raw):
    """Strict local validation, never source authentication or effect authority."""
    value = json.loads(raw, object_pairs_hook=_pairs, parse_float=_bad_number, parse_constant=_bad_number)
    _validate(SCHEMA, value)
    paths = [entry["path"] for entry in value.get("paths", []) + value.get("supporting", [])]
    if len(paths) != len(set(paths)) or any(part in ("", ".", "..") for path in paths for part in path.split("/")):
        raise ValueError("noncanonical or duplicate path")
    if value["kind"] == "envelope" and set(value["protected"]) != {
        "contracts", "interfaces", "dependencies", "workflows", "live", "spending", "self_authorization"
    }:
        raise ValueError("missing protected gate")
    if value["kind"] == "intent" and operation_key(value) != value["operation_key"]:
        raise ValueError("operation identity mismatch")
    if value["kind"] == "claim":
        if value["generation"] != value["previous_generation"] + 1 or value["ref"] != claim_ref(value):
            raise ValueError("claim generation/ref mismatch")
        if value["scope"] == "generation":
            if value["operation_key"] != "0" * 64 or value["intent_id"] is not None:
                raise ValueError("generation identity mismatch")
        elif value["intent_id"] is None:
            raise ValueError("missing operation intent")
    if value["kind"] == "completion":
        if (value["state"] == "superseded") != (value["superseded_by"] is not None):
            raise ValueError("supersession identity mismatch")
    return value


def read_comment(body, container):
    """Bind one strict record fence to actual repository/subject metadata."""
    blocks = re.findall(r"^```json\n(.*?)\n```$", body, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1 or body.count("```") != 2:
        raise ValueError("ambiguous record fence")
    record = read_record(blocks[0])
    if "subject" not in record or (record["repository"], record["subject"]["kind"], record["subject"]["number"]) != container:
        raise ValueError("record container mismatch")
    return record


def _checked(value):
    try:
        return read_record(json.dumps(value, allow_nan=False))
    except (TypeError, OverflowError) as error:
        raise ValueError("invalid record") from error


def _binding(record, current):
    return all(record[key] == current[key] for key in ("repository", "spec", "ticket", "approval"))


def _same_ticket(record, intent):
    return all(record[key] == intent[key] for key in ("repository", "spec", "ticket"))


def admit_claim(claim, snapshot, record_commit, create_if_absent):
    """One atomic record-storage attempt; never effect authority or a retry.

    The consumer must first verify the exact ops-record.json commit content,
    source history and durable intent, then persist/read back the admission.
    An unknown reply needs a later read-back, not another create. No ref update,
    delete, callback retry or effect callback is available through this seam.
    """
    claim, snapshot = map(_checked, (claim, snapshot))
    if (claim["kind"] != "claim" or snapshot["kind"] != "snapshot"
            or type(record_commit) is not str or re.fullmatch("[0-9a-f]{40}", record_commit) is None):
        raise ValueError("wrong claim inputs")
    if not snapshot["complete"] or not _binding(claim, snapshot) or snapshot["paused"] or snapshot["revoked"]:
        return "refused"
    if claim["scope"] == "generation":
        if claim["previous_generation"] != snapshot["generation"]:
            return "stale"
    else:
        if (claim["generation"], claim["owner"]) != (snapshot["generation"], snapshot["owner"]):
            return "stale"
        if snapshot["uncertain_keys"]:
            return "reconcile"
        intents = [r for r in snapshot["intents"] if r["id"] == claim["intent_id"]]
        if len(intents) != 1:
            return "refused"
        intent = _checked(intents[0])
        if (not _binding(intent, snapshot) or intent["operation_key"] != claim["operation_key"]
                or intent["head"] != snapshot["head"] or intent["subject"] != claim["subject"]
                or intent["rule"] != claim["rule"]):
            return "refused"
    try:
        outcome = create_if_absent(claim["ref"], record_commit)
    except Exception:
        return "uncertain"
    return {"created": "admitted", "exists": "duplicate"}.get(outcome, "uncertain") if type(outcome) is str else "uncertain"


def resume(intent, claim, history, snapshot, effect_boundary):
    """Reconstruct one finite refusal. effect_boundary is NEVER called.

    Keep historical uncertainty ahead of currentness checks: a changed approval,
    head, generation, key, ACK or later refusal cannot prove non-execution.
    Even a purported completed/non-executed record needs endpoint verification;
    no authenticated outcome lookup exists in OB1, so return reconcile and end.
    """
    intent, claim, snapshot = map(_checked, (intent, claim, snapshot))
    history = [_checked(record) for record in history]
    if (intent["kind"] != "intent" or claim["kind"] != "claim" or claim["scope"] != "operation"
            or snapshot["kind"] != "snapshot"
            or any(r["kind"] not in {"intent", "admission", "transport", "ack", "completion"} for r in history)):
        raise ValueError("wrong boundary record kinds")
    ids = [(r["repository"], r["id"]) for r in history]
    if len(ids) != len(set(ids)):
        raise ValueError("ambiguous record identity")
    records = {}
    for record in [intent, claim, *history]:
        identity = (record["repository"], record["id"])
        if identity in records and records[identity] != record:
            raise ValueError("conflicting immutable record identity")
        records[identity] = record
    result = dict(schema="openwiz.ops-dispatch.v1", kind="result",
                  operation_key=intent["operation_key"], intent_id=intent["id"],
                  state="disabled", reason="unfenced_effect", next="end", effects=[])

    def end(state, reason):
        return dict(result, state=state, reason=reason)

    relevant = [r for r in history if r["operation_key"] == intent["operation_key"]]

    def belongs(record):
        return (_binding(record, intent) and record["subject"] == intent["subject"]
                and (record == intent if record["kind"] == "intent"
                     else record.get("intent_id", intent["id"]) == intent["id"]))

    unsettled = {"transport": {"accepted", "uncertain"},
                 "completion": {"uncertain", "completed", "reconciled_not_executed"},
                 "admission": {"uncertain", "reconcile"}}
    if snapshot["uncertain_keys"] or any(
        _same_ticket(r, intent) and r.get("state") in unsettled.get(r["kind"], set())
        and (belongs(r) if r["operation_key"] == intent["operation_key"] else True) for r in history
    ):
        return end("reconcile", "uncertain_outcome")
    if any(not belongs(r) for r in relevant):
        return end("refused", "stale_binding")
    if not snapshot["complete"]:
        return end("refused", "incomplete_read")
    durable = [r for r in snapshot["intents"] if r["id"] == intent["id"]]
    if (not _binding(intent, snapshot) or not _binding(claim, snapshot)
            or intent["head"] != snapshot["head"] or durable != [intent]
            or claim["subject"] != intent["subject"] or claim["rule"] != intent["rule"]
            or claim["intent_id"] != intent["id"] or claim["operation_key"] != intent["operation_key"]):
        return end("refused", "stale_binding")
    if (claim["generation"], claim["owner"]) != (snapshot["generation"], snapshot["owner"]):
        return end("refused", "stale_claim")
    if snapshot["paused"] or snapshot["revoked"] or snapshot["gates"] or snapshot["holds"]:
        return end("refused", "paused_or_revoked")
    if any(r["kind"] == "completion" and r["state"] == "superseded" for r in relevant):
        return end("superseded", "superseded")
    if intent["sequence"] != snapshot["next_sequence"]:
        return end("deferred", "out_of_order")
    return result
