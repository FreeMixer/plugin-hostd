# The declared protocol, protocol/plugin-hostd.json, against its schema: a consumer that reads the JSON may rely on
# the shape the schema says.
import json, sys

try:
    import jsonschema
except ImportError:
    sys.exit("check-generated needs python3-jsonschema (dnf install python3-jsonschema, apt install python3-jsonschema)")

document, schema = (json.load(open(p)) for p in sys.argv[1:3])
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)
print("ok   %s satisfies %s" % (sys.argv[1], sys.argv[2]))
