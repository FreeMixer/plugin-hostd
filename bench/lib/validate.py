"""Check omx-bench/1 documents: the JSON Schema of bench/schema, read here with the keywords it uses, and the rules
across rows the schema cannot say. One line per problem: file, scenario row, rule, what is wrong. Exit 1 on any."""

import json
import re
import sys


def type_ok(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise ValueError("schema uses an unknown type: " + name)


KNOWN = {"$schema", "$id", "title", "type", "const", "enum", "required", "properties", "additionalProperties", "items",
         "minItems", "minimum", "minLength", "pattern", "allOf", "if", "then"}


def check(value, schema, path, errors):
    """append (path, rule, message) for each way value breaks schema; path is a list of keys"""
    unknown = set(schema) - KNOWN
    if unknown:
        raise ValueError("schema uses keywords this validator does not read: " + ", ".join(sorted(unknown)))
    rule = "/".join(str(p) for p in path) or "(document)"
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(type_ok(value, n) for n in names):
            errors.append((path, rule + ":type", "is %s, not %s" % (json.dumps(value), " or ".join(names))))
            return
    if "const" in schema and value != schema["const"]:
        errors.append((path, rule + ":const", "is %s, not %s" % (json.dumps(value), json.dumps(schema["const"]))))
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, rule + ":enum", "is %s, not one of %s" % (json.dumps(value), json.dumps(schema["enum"]))))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            errors.append((path, rule + ":minimum", "is %s, below %s" % (value, schema["minimum"])))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append((path, rule + ":minLength", "is shorter than %d" % schema["minLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append((path, rule + ":pattern", "%s does not match %s" % (json.dumps(value), schema["pattern"])))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append((path, rule + ":minItems", "has %d items, fewer than %d" % (len(value), schema["minItems"])))
        if "items" in schema:
            for n, item in enumerate(value):
                check(item, schema["items"], path + [n], errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append((path, rule + ":required", "lacks %s" % key))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                check(item, props[key], path + [key], errors)
            elif extra is False:
                errors.append((path, rule + ":additionalProperties", "has %s, which the schema does not declare" % key))
            elif isinstance(extra, dict):
                check(item, extra, path + [key], errors)
    for sub in schema.get("allOf", []):
        check(value, sub, path, errors)
    if "if" in schema:
        probe = []
        check(value, schema["if"], path, probe)
        if not probe and "then" in schema:
            check(value, schema["then"], path, errors)


def row_name(doc, path):
    if len(path) >= 2 and path[0] == "scenarios" and isinstance(path[1], int):
        try:
            s = doc["scenarios"][path[1]]
            return "scenario %s %s %s/%s%s" % (s.get("id"), s.get("host"), s.get("rate"), s.get("frames"),
                                               " " + s["mode"] if "mode" in s else "")
        except (KeyError, IndexError, TypeError, AttributeError):
            return "scenario #%d" % path[1]
    return "document"


def cross_rules(doc, errors):
    """what one row cannot say about itself"""
    seen = {}
    for n, s in enumerate(doc.get("scenarios", [])):
        if not isinstance(s, dict):
            continue
        key = (s.get("id"), s.get("host"), s.get("mode"), s.get("rate"), s.get("frames"))
        if key in seen:
            errors.append((["scenarios", n], "rule:unique-row", "repeats row #%d (same id, host, mode, rate, frames)"
                           % seen[key]))
        seen[key] = n
        avg, mx = s.get("dsp_load_avg"), s.get("dsp_load_max")
        if isinstance(avg, (int, float)) and isinstance(mx, (int, float)) and mx < avg:
            errors.append((["scenarios", n], "rule:max-not-below-avg", "dsp_load_max %s is below dsp_load_avg %s"
                           % (mx, avg)))
        if s.get("recover_ms") is not None and s.get("status") != "ok":
            errors.append((["scenarios", n], "rule:recover-only-ok", "has recover_ms on a row that is not ok"))
        if s.get("status") == "ok" and s.get("plugins") and s.get("add_ms") is None:
            errors.append((["scenarios", n], "rule:add-measured", "is ok with plugins and no add_ms"))
        if "rss_mb_total" in s and "processes" not in s:
            errors.append((["scenarios", n], "rule:totals-name-processes", "has totals and no processes count"))
    m = re.match(r"^([a-z0-9]+)-", str(doc.get("id", "")))
    cls = doc.get("machine", {}).get("class") if isinstance(doc.get("machine"), dict) else None
    if m and cls and m.group(1) != cls:
        errors.append(([], "rule:id-class", "id %s does not start with the machine class %s" % (doc["id"], cls)))
    q = doc.get("qualification")
    if isinstance(q, dict) and all(isinstance(q.get(k), int) for k in ("plugins", "suitable", "unsuitable")):
        if q["suitable"] + q["unsuitable"] != q["plugins"]:
            errors.append((["qualification"], "rule:qualification-sum", "suitable + unsuitable is not plugins"))


def main():
    schema = json.load(open(sys.argv[1]))
    bad = 0
    for name in sys.argv[2:]:
        try:
            with open(name) as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            print("%s: document: rule:json: %s" % (name, e))
            bad += 1
            continue
        errors = []
        check(doc, schema, [], errors)
        if isinstance(doc, dict):
            cross_rules(doc, errors)
        for path, rule, msg in errors:
            print("%s: %s: %s: %s" % (name, row_name(doc, path), rule, msg))
        if errors:
            bad += 1
        else:
            print("%s: valid omx-bench/1, %d scenario rows" % (name, len(doc["scenarios"])))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
