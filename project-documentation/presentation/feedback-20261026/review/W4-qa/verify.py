"""Independent W4 audit: compile upgrades to PostgreSQL SQL, then inspect that SQL.

Does not import the author's generator, connect to a database, or modify source files.
Run from the dc2-rescue root. Outputs are confined to this directory.
"""

from collections import defaultdict
from io import StringIO
import importlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
QA = Path(__file__).resolve().parent
DOC = ROOT / "project-documentation/presentation/feedback-20261026"
FIG = ROOT / "project-documentation/presentation/site/assets/uml"
HEAD = "76282d3b5a141f6548056f2506f9d5aff0742692"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == HEAD


def norm(value):
    return re.sub(r"\s+", " ", str(value)).strip()


def split_sql(value, delimiter=","):
    result, buf, depth, quote = [], [], 0, False
    i = 0
    while i < len(value):
        char = value[i]
        if char == "'":
            if quote and i + 1 < len(value) and value[i + 1] == "'":
                buf.extend([char, char]); i += 2; continue
            quote = not quote
        if not quote:
            depth += (char == "(") - (char == ")")
            if char == delimiter and depth == 0:
                result.append(norm("".join(buf))); buf = []; i += 1; continue
        buf.append(char); i += 1
    if norm("".join(buf)):
        result.append(norm("".join(buf)))
    return result


def parse_ddl(sql):
    tables = {}

    def column(table, line):
        match = re.fullmatch(r"(\w+) (.*?)(?: DEFAULT (.*?))?( NOT NULL)?", line)
        assert match, line
        name, kind, default, nn = match.groups()
        # SERIAL is a PostgreSQL integer plus a sequence-backed server default.
        if kind == "SERIAL":
            kind, default = "INTEGER", f"nextval('{table}_id_seq'::regclass)"
        tables[table]["columns"][name] = {
            "type": kind, "null": "NN" if nn else "?", "default": default or "—"
        }

    def constraint(table, line):
        cname = ""
        named = re.match(r"CONSTRAINT (\w+) (.*)", line)
        if named:
            cname, line = named.groups()
        suffix = f" [{cname}]" if cname else ""
        if line.startswith("PRIMARY KEY"):
            cols = re.fullmatch(r"PRIMARY KEY \((.*?)\)", line)[1]
            result = f"PK ({cols}){suffix}"
        elif line.startswith("UNIQUE"):
            cols = re.fullmatch(r"UNIQUE \((.*?)\)", line)[1]
            result = f"UK ({cols}){suffix}"
        elif line.startswith("CHECK"):
            result = "CHECK " + line[7:-1] + suffix
        elif line.startswith("FOREIGN KEY"):
            m = re.fullmatch(r"FOREIGN KEY\s*\((.*?)\) REFERENCES (\w+) \((.*?)\)(.*)", line)
            cols, target, remote, flags = m.groups()
            delete = re.search(r"ON DELETE (CASCADE|NO ACTION|RESTRICT|SET NULL)", flags)
            update = re.search(r"ON UPDATE (CASCADE|NO ACTION|RESTRICT|SET NULL)", flags)
            result = f"FK ({cols}) → {target}.{remote}; ON DELETE {delete[1] if delete else 'NO ACTION'}; ON UPDATE {update[1] if update else 'NO ACTION'}"
            if "DEFERRABLE" in flags:
                result += "; DEFERRABLE INITIALLY DEFERRED"
            result += suffix
        else:
            raise AssertionError(line)
        tables[table]["constraints"].append(result)

    for statement in split_sql(sql, ";"):
        create = re.fullmatch(r"CREATE TABLE (\w+) \((.*)\)", statement)
        add = re.fullmatch(r"ALTER TABLE (\w+) ADD COLUMN (.*)", statement)
        alter = re.fullmatch(r"ALTER TABLE (\w+) ADD (.*)", statement)
        index = re.fullmatch(r"CREATE INDEX (\w+) ON (\w+) \((.*?)\)(?: WHERE (.*))?", statement)
        if create:
            table, body = create.groups()
            tables[table] = {"columns": {}, "constraints": [], "indexes": []}
            for item in split_sql(body):
                if item.startswith(("PRIMARY KEY", "CONSTRAINT", "UNIQUE", "CHECK", "FOREIGN KEY")):
                    constraint(table, item)
                else:
                    column(table, item)
        elif add:
            column(*add.groups())
        elif alter:
            constraint(*alter.groups())
        elif index:
            name, table, cols, where = index.groups()
            tables[table]["indexes"].append(f"{name} ({cols})" + (" WHERE " + where if where else ""))
        else:
            raise AssertionError(statement)
    return tables


from alembic.migration import MigrationContext
from alembic.operations import Operations

schema, chain = {}, {}
for db in ("media", "processing"):
    buf = StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buf})
    mods = {}
    for path in sorted((ROOT / db / "migrations/versions").glob("*.py")):
        assert path.read_bytes() == subprocess.check_output(["git", "show", f"76282d3:{path.relative_to(ROOT)}"])
        spec = importlib.util.spec_from_file_location("independent_" + db + path.stem, path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        mods[mod.down_revision] = mod
    revision = None
    chain[db] = []
    with Operations.context(ctx):
        while revision in mods:
            mod = mods[revision]; mod.upgrade(); revision = mod.revision; chain[db].append(revision)
    assert len(chain[db]) == len(mods)
    (QA / f"{db}-head.sql").write_text(buf.getvalue())
    for name, table in parse_ddl(buf.getvalue()).items():
        schema[db + "." + name] = table

dictionary = (DOC / "report-notes/W4-dictionary.md").read_text()
assert dictionary.strip() in (DOC / "report-notes/W4.md").read_text()
parts = re.split(r"#### `(media|processing)_db\.public\.(\w+)`\n", dictionary)
errors, checked = [], []


def compare(actual, expected, location):
    if actual != expected:
        errors.append({"location": location, "actual": actual, "expected": expected})


def default_norm(value):
    if value in ("'0'", "'reserved'"):
        return value[1:-1]
    return value


for i in range(1, len(parts), 3):
    db, name, block = parts[i:i+3]
    key = db + "." + name
    checked.append(key)
    table = schema[key]
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| (NN|\?) \| ([^|]+) \| `([^`]+)` \|", block, re.M)
    compare([r[0] for r in rows], list(table["columns"]), key + ".column_order")
    # Derive column markers from the actual SQL constraints, independently of the dictionary.
    marks = defaultdict(list)
    unique = sorted([c for c in table["constraints"] if c.startswith("UK")])
    for constraint in table["constraints"]:
        if constraint.startswith("CHECK"):
            continue
        m = re.match(r"(PK|UK|FK) \(([^)]+)\)", constraint)
        kind, cols = m.groups(); cols = cols.split(", ")
        if kind == "UK" and len(cols) > 1:
            kind = "UK" + str(unique.index(constraint) + 1)
        for col in cols:
            marks[col].append(kind)
    for col, kind, null, markers, default in rows:
        actual = table["columns"][col]
        compare(kind, actual["type"], key + "." + col + ".type")
        compare(null, actual["null"], key + "." + col + ".null")
        compare(default_norm(default), default_norm(actual["default"]), key + "." + col + ".default")
        compare(sorted(markers.strip().split(",")) if markers.strip() != "—" else [], sorted(marks[col]), key + "." + col + ".keys")
    constraint_text = block.split("Constraints:\n", 1)[1].split("Explicit indexes:", 1)[0]
    doc_constraints = re.findall(r"^- `([^`]+)`", constraint_text, re.M)
    compare(sorted(doc_constraints), sorted(table["constraints"]), key + ".constraints")
    index_text = block.split("Explicit indexes:\n", 1)[1].split("### ", 1)[0]
    doc_indexes = [x.replace("`", "") for x in re.findall(r"^- (.*)$", index_text, re.M) if x != "None."]
    compare(sorted(doc_indexes), sorted(table["indexes"]), key + ".indexes")
compare(sorted(checked), sorted(schema), "dictionary.tables")

figure_tables, edges = [], []
for path in sorted(FIG.glob("W4-*.puml")):
    db = "processing" if "processing" in path.stem else "media"
    source = path.read_text()
    entities = {}
    for m in re.finditer(r'entity "([^"]+)" as (\w+) \$(MEDIA|PROC|INFRA) \{\n(.*?)\n\}', source, re.S):
        label, table, color, body = m.groups()
        key = db + "." + table
        entities[table] = key
        fields = re.findall(r"\{field\}\s+(\*)?\s*(\w+)(\s+\?)?\s*:\s*([\w()]+)(?:\s*<<([^>]+)>>)?", body)
        names = []
        for star, col, nullable, typ, markers in fields:
            names.append(col)
            expected = schema[key]["columns"][col]
            sqltype = "TIMESTAMP WITH TIME ZONE" if typ == "timestamptz" else typ.upper()
            compare(sqltype, expected["type"], path.name + ":" + col + ".type")
            compare("NN" if star else "?", expected["null"], path.name + ":" + col + ".null")
            compare(bool(nullable), not bool(star), path.name + ":" + col + ".nullable_marker")
            for marker in filter(None, markers.split(",")):
                kind = re.sub(r"\d+$", "", marker)
                compare(any(c.startswith(kind + " (") and col in re.search(r"\(([^)]+)\)", c)[1].split(", ") for c in schema[key]["constraints"]), True, path.name + ":" + col + "." + marker)
            expected_marks = [re.match(r"(PK|FK|UK)", c)[1] for c in schema[key]["constraints"] if c.startswith(("PK (", "FK (", "UK (")) and col in re.search(r"\(([^)]+)\)", c)[1].split(", ")]
            compare(sorted(set(re.sub(r"\d+$", "", k) for k in markers.split(",") if k)), sorted(set(expected_marks)), path.name + ":" + col + ".all_markers")
        if color != "INFRA" and not path.stem.endswith("-main"):
            compare(names, list(schema[key]["columns"]), path.name + ".all_columns")
        groups = defaultdict(list)
        for star, col, nullable, typ, markers in fields:
            for marker in markers.split(","):
                if re.fullmatch(r"UK\d+", marker):
                    groups[marker].append(col)
        for group, cols in groups.items():
            compare(any(c.startswith("UK (" + ", ".join(cols) + ")") for c in schema[key]["constraints"]), True, path.name + "." + group + ".composite_members")
        figure_tables.append({"figure": path.name, "table": key, "columns": len(names), "full": color != "INFRA" and not path.stem.endswith("-main")})
    for line in source.splitlines():
        if "--" in line and re.match(r"\w+ [|o}{]+--[|o}{]+ \w+", line):
            parent, rel, child, label = re.fullmatch(r'(\w+) ([|o}{]+--[|o}{]+) (\w+) : "([^"]+)"', line).groups()
            edges.append({"figure": path.name, "parent": parent, "relationship": rel, "child": child, "label": label})
            fks = [c for c in schema[entities[child]]["constraints"] if c.startswith("FK (") and f"→ {parent}." in c]
            compare(bool(fks), True, path.name + ".declared_fk:" + line)
            assert len(fks) == 1, (path.name, line, fks)
            cols = re.search(r"\(([^)]+)\)", fks[0])[1].split(", ")
            parent_side = "|o" if any(schema[entities[child]]["columns"][c]["null"] == "?" for c in cols) else "||"
            unique_fk = any(c.startswith(("PK (", "UK (")) and re.search(r"\(([^)]+)\)", c)[1].split(", ") == cols for c in schema[entities[child]]["constraints"])
            compare(rel, parent_side + "--" + ("o|" if unique_fk else "o{"), path.name + ".cardinality:" + label)
compare(sorted(set(t["table"] for t in figure_tables if t["full"])), sorted(schema), "full_figure_coverage")

# Compile ORM tables separately; absent migration-only indexes are reported, not used as authority.
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, AddConstraint, CreateIndex
orm = {}
for db, modules in {"media": ["models", "upload_models", "projection_models", "messaging_models"], "processing": ["models", "messaging_models", "launcher_models"]}.items():
    for module in modules:
        importlib.import_module(db + "." + module)
    metadata = importlib.import_module(db + ".database").Base.metadata
    dialect = postgresql.dialect()
    for table in metadata.tables.values():
        ddl = str(CreateTable(table).compile(dialect=dialect)) + ";\n"
        for fk in table.foreign_key_constraints:
            if fk.use_alter:
                ddl += str(AddConstraint(fk).compile(dialect=dialect)) + ";\n"
        for idx in table.indexes:
            ddl += str(CreateIndex(idx).compile(dialect=dialect)) + ";\n"
        orm[db + "." + table.name] = parse_ddl(ddl)[table.name]
orm_differences = []
for key in schema:
    for aspect in ("columns", "constraints", "indexes"):
        a, b = schema[key][aspect], orm[key][aspect]
        if aspect == "columns":
            a = {c:{**v,"default":default_norm(v["default"])} for c,v in a.items()}
            b = {c:{**v,"default":default_norm(v["default"])} for c,v in b.items()}
        else:
            a, b = sorted(a), sorted(b)
        if a != b:
            orm_differences.append({"table": key, "aspect": aspect, "migration": a, "orm": b})

result = {"head": HEAD, "chains": chain, "tables": len(schema), "columns": sum(len(t["columns"]) for t in schema.values()), "constraints": sum(len(t["constraints"]) for t in schema.values()), "explicit_indexes": sum(len(t["indexes"]) for t in schema.values()), "dictionary_tables": checked, "figure_tables": figure_tables, "edges": edges, "errors": errors, "orm_differences": orm_differences}
(QA / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")
(QA / "schema-verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k:v for k,v in result.items() if k not in ("figure_tables", "edges", "dictionary_tables")}, indent=2))
