"""Documentation-only migration reconstruction and W4 figures. No database connection."""
from pathlib import Path
import ast, importlib.util, inspect, json, re, sys
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
UML = ROOT / 'project-documentation/presentation/site/assets/uml'
BASE = 'https://github.com/Collaboration95/dc2/blob/76282d3/'
DIALECT = postgresql.dialect()
def sqltype(c): return str(c.type.compile(dialect=DIALECT))
def physical_default(c):
    if c.server_default is not None:
        return str(c.server_default.arg)
    # PostgreSQL SERIAL has a sequence default even though SQLAlchemy's
    # Column.server_default is None. A Python default can suppress SERIAL in ORM DDL.
    ddl = str(sa.schema.CreateTable(c.table).compile(dialect=DIALECT))
    if re.search(rf'\b{re.escape(c.name)} SERIAL\b', ddl):
        return f"nextval('{c.table.name}_{c.name}_seq'::regclass)"
    return None
def link(path, line): return f'{BASE}{path}#L{line}'
class Recorder:
    def __init__(self): self.md=sa.MetaData(); self.origins={}; self.table_origins={}
    def origin(self):
        frame=next(f for f in inspect.stack() if '/migrations/versions/' in f.filename)
        return [str(Path(frame.filename).relative_to(ROOT)), frame.lineno]
    def create_table(self, name, *parts, **kw):
        t=sa.Table(name,self.md,*parts); p=self.origin()
        self.table_origins[name]=[p]
        for c in t.c: self.origins[(name,c.name)] = p
    def add_column(self,name,c):
        self.md.tables[name].append_column(c); p=self.origin(); self.origins[(name,c.name)]=p
        if p not in self.table_origins[name]: self.table_origins[name].append(p)
    def create_index(self,name,table,columns,**kw):
        sa.Index(name,*[self.md.tables[table].c[x] for x in columns],**kw)
    def create_check_constraint(self,name,table,condition):
        self.md.tables[table].append_constraint(sa.CheckConstraint(condition,name=name))
        self.table_origins[table].append(self.origin())
    def create_foreign_key(self,name,source,target,local,remote,**kw):
        self.md.tables[source].append_constraint(sa.ForeignKeyConstraint(local,[f'{target}.{c}' for c in remote],name=name,**kw))
    def execute(self, statement):
        s=str(statement).strip()
        if s.startswith('CREATE INDEX'):
            m=re.fullmatch(r'CREATE INDEX (\w+) ON (\w+) \(([^)]+)\)',s)
            self.create_index(m[1],m[2],[x.strip() for x in m[3].split(',')]); return
        m=re.fullmatch(r'CREATE TABLE (\w+) \((.*)\)',s,re.S)
        assert m, s
        columns=[]; constraints=[]
        for row in m[2].strip().splitlines():
            row=row.strip().rstrip(',')
            if row.startswith('PRIMARY KEY'):
                constraints.append(sa.PrimaryKeyConstraint(*re.search(r'\((.*)\)',row)[1].split(', ')))
            elif row.startswith('UNIQUE'):
                constraints.append(sa.UniqueConstraint(*re.search(r'\((.*)\)',row)[1].split(', ')))
            elif row.startswith('CHECK'):
                constraints.append(sa.CheckConstraint(row[7:-1]))
            elif row.startswith('FOREIGN KEY'):
                f=re.fullmatch(r'FOREIGN KEY\((\w+)\) REFERENCES (\w+) \((\w+)\)',row)
                constraints.append(sa.ForeignKeyConstraint([f[1]],[f'{f[2]}.{f[3]}']))
            else:
                c=re.fullmatch(r'(\w+) (UUID|TEXT|JSONB|INTEGER|TIMESTAMP WITH TIME ZONE|VARCHAR\(\d+\))( NOT NULL)?',row)
                assert c, row
                typ={'UUID':sa.Uuid,'TEXT':sa.Text,'JSONB':postgresql.JSONB,'INTEGER':sa.Integer}.get(c[2])
                if c[2]=='TIMESTAMP WITH TIME ZONE': typ=sa.DateTime(timezone=True)
                elif c[2].startswith('VARCHAR'): typ=sa.String(int(re.search(r'\d+',c[2])[0]))
                columns.append(sa.Column(c[1],typ,nullable=not bool(c[3])))
        self.create_table(m[1],*columns,*constraints)
        path,_=self.origin()
        line=next(i for i,v in enumerate((ROOT/path).read_text().splitlines(),1) if f'CREATE TABLE {m[1]} (' in v)
        self.table_origins[m[1]]=[[path,line]]

def reconstruct(service):
    modules=[]
    for file in sorted((ROOT/service/'migrations/versions').glob('*.py')):
        spec=importlib.util.spec_from_file_location(file.stem,file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); modules.append(mod)
    rec=Recorder(); ordered=[]; parent=None
    while modules:
        ready=[m for m in modules if m.down_revision==parent]; assert len(ready)==1
        mod=ready[0]; mod.op=rec; mod.upgrade(); parent=mod.revision; ordered.append(parent); modules.remove(mod)
    return rec,ordered

def constraints(t):
    results=[]
    for c in t.constraints:
        name=f' [{c.name}]' if c.name else ''
        cols=', '.join(c.columns.keys())
        if isinstance(c,sa.PrimaryKeyConstraint): text=f'PK ({cols})'
        elif isinstance(c,sa.UniqueConstraint): text=f'UK ({cols})'
        elif isinstance(c,sa.CheckConstraint): text=f'CHECK {c.sqltext}'
        elif isinstance(c,sa.ForeignKeyConstraint):
            text=f"FK ({cols}) → {', '.join(e.target_fullname for e in c.elements)}; ON DELETE {c.ondelete or 'NO ACTION'}; ON UPDATE {c.onupdate or 'NO ACTION'}"
            if c.deferrable: text+=f'; DEFERRABLE INITIALLY {c.initially}'
        else: raise ValueError(c)
        results.append(text+name)
    return sorted(results)

def keys(t,c):
    k=['PK'] if c.primary_key else []
    if c.foreign_keys: k.append('FK')
    groups=sorted([x for x in t.constraints if isinstance(x,sa.UniqueConstraint)],key=lambda x:','.join(x.columns.keys()))
    for i,u in enumerate(groups,1):
        if c.name in u.columns.keys(): k.append('UK' if len(u.columns)==1 else f'UK{i}')
    return ','.join(k)

MEDIA,MCHAIN=reconstruct('media'); PROC,PCHAIN=reconstruct('processing')
assert MCHAIN[-1]=='media_0008' and PCHAIN[-1]=='processing_0007'
assert len(MEDIA.md.tables)==len(PROC.md.tables)==11
import media.models,media.upload_models,media.projection_models,media.messaging_models
import processing.models,processing.messaging_models,processing.launcher_models
from media.database import Base as MBase
from processing.database import Base as PBase
DIFFS=[]
for service,r,orm in [('media',MEDIA,MBase.metadata),('processing',PROC,PBase.metadata)]:
    assert set(r.md.tables)==set(orm.tables)
    for name,t in r.md.tables.items():
        o=orm.tables[name]; assert set(t.c.keys())==set(o.c.keys()),name
        for c in t.c:
            other=o.c[c.name]
            for label,a,b in [('type',sqltype(c),sqltype(other)),('nullable',c.nullable,other.nullable),('keys',keys(t,c),keys(o,other))]:
                assert a==b,(service,name,c.name,label,a,b)
            if physical_default(c)!=physical_default(other):
                DIFFS.append(f'{service}.{name}.{c.name}: migration physical default {physical_default(c)}; ORM-created SQL default {physical_default(other)} (ORM Python default {other.default.arg if other.default else None})')
        assert constraints(t)==constraints(o),(name,constraints(t),constraints(o))
        def idx(table): return {(i.name,tuple(c.name for c in i.columns),str(i.dialect_options['postgresql'].get('where'))) for i in table.indexes}
        if idx(t)!=idx(o): DIFFS.append(f'{service}.{name}: migration indexes {sorted(idx(t))}; ORM indexes {sorted(idx(o))}')

purpose={
'users':'Account identity, credentials and role', 'assets':'Owned immutable asset intake and submission state',
'upload_reservations':'Direct-upload idempotency, immutable version pin and orphan rescan authority',
'asset_source_versions':'Version pins for edit-derived copied sources; ORM class is SourceVersion',
'processing_projections':'Media-owned result snapshot; read without querying processing_db',
'request_keys':'Owner/operation/request identity and immutable request hash',
'retry_intents':'Retained legacy peer retry bookkeeping; native V1 retry uses command outbox',
'staged_objects':'Crash-safe orphan ledger for uncertain source writes',
'message_inbox':'Received message identity plus canonical body hash; dedupe in domain transaction',
'message_outbox':'Canonical envelope and durable relay claim/replay schedule',
'jobs':'Processing authority for one asset, source, operations, current attempt and output descriptors',
'attempts':'Numbered execution attempt, token lease, deadline and recovery schedule',
'submission_guards':'Durable owner/asset submission/cancellation boundary, including cancel-before-submit',
'retry_requests':'Stable retry identity maps to the already-created attempt',
'job_messaging':'Monotonic result/work state version per Job',
'attempt_tasks':'One finite task-name binding per Attempt and unique task name',
'launcher_control':'Optional unattended launcher singleton enable/session gate',
'launch_reservations':'Optional unattended launcher durable ECS request replay and capacity reservations'}
short={'TIMESTAMP WITH TIME ZONE':'timestamptz','INTEGER':'integer','BOOLEAN':'boolean','UUID':'uuid','TEXT':'text','JSONB':'jsonb'}
def type_short(c): return short.get(sqltype(c),sqltype(c).lower())

def entity(r,table,cols=None,stub=False):
    t=r.md.tables[table]; cols=cols or list(t.c.keys()); color='$INFRA' if stub else ('$MEDIA' if r is MEDIA else '$PROC')
    out=[f'entity "{table}'+('\\n<<reference: key only>>' if stub else '')+f'" as {table} {color} {{']
    for name in cols:
        c=t.c[name]; key=keys(t,c)
        out.append(f'  {{field}} {"*" if not c.nullable else " "} {name}{" ?" if c.nullable else ""} : {type_short(c)}'+(f' <<{key}>>' if key else ''))
    if not stub:
        groups=sorted([x for x in t.constraints if isinstance(x,sa.UniqueConstraint) and len(x.columns)>1],key=lambda x:','.join(x.columns.keys()))
        if groups:
            out+=['  --']+[f'  UK{sorted([x for x in t.constraints if isinstance(x,sa.UniqueConstraint)],key=lambda x:",".join(x.columns.keys())).index(u)+1} = ({", ".join(u.columns.keys())})' for u in groups]
    return '\n'.join(out+['}'])

FIGURES=[]
def diagram(slug,title,r,selected,stubs=None,extra='',layout='left to right direction',main=False,links=True):
    stubs=stubs or {}; active=set(selected)|set(stubs)
    text=['!include _style.iuml','@startuml','!include _style.iuml',f'title {title} · 76282d3','hide circle','skinparam linetype polyline',layout,
          'skinparam defaultFontSize 19','skinparam ClassAttributeFontSize 18','skinparam ClassFontSize 20','skinparam ArrowFontSize 16','skinparam LegendFontSize 14',
          'skinparam nodesep '+('20' if main else '42'),'skinparam ranksep '+('45' if main else '70')]
    text += [entity(r,t,cols) for t,cols in selected.items()]
    text += [entity(r,t,cols,True) for t,cols in stubs.items()]
    if links:
        for child in active:
            t=r.md.tables[child]
            for fk in sorted(t.foreign_key_constraints,key=lambda x:','.join(x.columns.keys())):
                parent=next(iter(fk.elements)).target_fullname.split('.')[0]
                if parent not in active or (child not in selected and parent not in selected): continue
                cols=list(fk.columns.keys())
                if any(c not in (selected.get(child) or stubs.get(child) or list(t.c.keys())) for c in cols): continue
                nullable=any(c.nullable for c in fk.columns)
                unique=any(set(cols)==set(u.columns.keys()) for u in t.constraints if isinstance(u,(sa.PrimaryKeyConstraint,sa.UniqueConstraint)))
                left='|o' if nullable else '||'; right='o|' if unique else 'o{'
                label=('current (deferred)' if fk.deferrable else ', '.join(cols))
                text.append(f'{parent} {left}--{right} {child} : "{label}"')
    text.append(extra)
    text += ['legend bottom left','  * = NOT NULL    ? = nullable    PK = primary key    FK = declared local foreign key',
             '  UK = unique column    UKn = one composite unique group    timestamptz = timestamp with time zone',
             '  Blue = Media; amber = Processing; grey = reference key on another sheet' if stubs else '  Blue = Media; amber = Processing. Only declared SQL foreign keys are connected.',
             '  Key columns selected; full columns and checks are in backup/report' if main else '  All columns of coloured tables are shown; CHECKs, defaults and indexes are in the report dictionary.',
             'endlegend','@enduml']
    path=UML/f'W4-{slug}.puml'; path.write_text('\n'.join(text)+'\n')
    origins=[]
    for t in selected:
        origins += r.table_origins[t]
    FIGURES.append({'slug':slug,'title':title,'tables':list(selected),'sources':list(dict.fromkeys(tuple(p) for p in origins)),'main':main})

# Separate main-talk business schemas; omit nonkey fields deliberately and visibly.
diagram('media-main','Physical data view · media_db · media_0008',MEDIA,{
'users':['id','email'],
'assets':['id','owner_id','source_key','operations'],
'upload_reservations':['id','owner_id','request_id','asset_id','version_id','finalized_at'],
'asset_source_versions':['asset_id','key','version_id'],
'processing_projections':['asset_id','job_id','state_version','status','outputs']},
extra='upload_reservations -[hidden]down- assets',main=True)
diagram('processing-main','Physical data view · processing_db · processing_0007',PROC,{
'jobs':['id','asset_id','status','current_attempt_id','outputs'],
'attempts':['id','job_id','attempt_number','state','lease_token','lease_expires_at'],
'retry_requests':None,'submission_guards':None},
extra='',main=True)
# Backup/report sheets, each with every column of its coloured tables.
diagram('media-assets','Physical data view · Media identity and assets',MEDIA,{'users':None,'assets':None})
diagram('media-upload','Physical data view · Media upload pins',MEDIA,{'upload_reservations':None},{'users':['id']})
diagram('media-pins','Physical data view · Media derived source pins',MEDIA,{'asset_source_versions':None},{'assets':['id']})
diagram('media-projection','Physical data view · Media result projection',MEDIA,{'processing_projections':None},{'assets':['id']})
diagram('media-intents','Physical data view · Media request identity',MEDIA,{'request_keys':None},{'users':['id'],'assets':['id']})
diagram('media-retry','Physical data view · Media retained legacy retry ledger',MEDIA,{'retry_intents':None},{'assets':['id']},extra='note bottom of retry_intents\nNative V1 retry stages a command outbox row.\nend note')
diagram('media-cleanup','Physical data view · Media deletion progress',MEDIA,{'cleanup_intents':None},{'assets':['id']})
diagram('media-delivery','Physical data view · Media durable delivery and orphan ledger',MEDIA,{'message_inbox':None,'message_outbox':None,'staged_objects':None},links=False,extra='message_inbox -[hidden]down- message_outbox\nmessage_outbox -[hidden]down- staged_objects')
diagram('processing-attempts','Physical data view · Processing jobs and fenced attempts',PROC,{'jobs':None,'attempts':None},extra='')
diagram('processing-intents','Physical data view · Processing retry and cancellation',PROC,{'retry_requests':None,'submission_guards':None},{'jobs':['id'],'attempts':['id']},extra='note bottom of submission_guards\njob_id is nullable and NOT unique.\nretry_requests FKs use ON DELETE CASCADE.\nend note')
diagram('processing-cleanup','Physical data view · Processing retained output cleanup',PROC,{'cleanup_intents':None},{'jobs':['id'],'attempts':['id']})
diagram('processing-delivery','Physical data view · Processing durable delivery',PROC,{'message_inbox':None,'message_outbox':None},extra='message_inbox -[hidden]down- message_outbox',links=False)
diagram('processing-bindings','Physical data view · Processing versions and task binding',PROC,{'job_messaging':None,'attempt_tasks':None},{'jobs':['id'],'attempts':['id']})
diagram('processing-launcher','Physical data view · Optional unattended launcher',PROC,{'launcher_control':None,'launch_reservations':None},links=False,
extra='launcher_control -[hidden]down- launch_reservations\nnote bottom of launcher_control\nid: integer; migration DDL uses SERIAL.\nSequence default; ORM supplies 1 instead.\nCHECK id = 1 does not insert a row.\nNo FK; optional UnattendedLaunch feature.\nend note')

# Generated dictionary: derive fields, types, defaults and constraints solely from upgrades.
lines=['## Appendix draft — full physical data dictionary','',
'Generated by `W4-generate.py` from the ordered migration `upgrade()` operations at `76282d3`; no database connection or application mutation. The initial Media raw CREATE TABLE statements are parsed, then additive Alembic operations are applied to in-memory SQLAlchemy metadata. This is static reconstruction, not an executed Aurora migration or live catalog inspection. SQL types use PostgreSQL dialect compilation. Defaults below include explicit server defaults and the sequence default implied by PostgreSQL SERIAL; UUID/time/list defaults supplied by Python are not SQL defaults. `NN` means NOT NULL; `?` means nullable. Every member marked `UKn` participates in the same composite group, not an individually unique column. PK/UK backing indexes are implicit; explicit indexes are listed separately. No application FK crosses databases.','']
for service,r,chain in [('media_db',MEDIA,MCHAIN),('processing_db',PROC,PCHAIN)]:
    lines += [f'### {service}.public — head `{chain[-1]}`','',f'Chain: `{" → ".join(chain)}`. File-number gaps are intentional.','']
    for name,t in r.md.tables.items():
        p=purpose.get(name,'Deletion progress and retained rescan authority')
        if name=='cleanup_intents': p='Deletion progress and retained rescan authority'
        lines += [f'#### `{service}.public.{name}`','',p+'.','',
            'Migration sources: '+', '.join(f'[{path}:{ln}]({link(path,ln)})' for path,ln in r.table_origins[name])+'.','',
            '| Column | SQL type | Null | Key / group | Server default |','|---|---|---|---|---|']
        for c in t.c:
            d=physical_default(c) or '—'
            lines.append(f'| `{c.name}` | `{sqltype(c)}` | {"?" if c.nullable else "NN"} | {keys(t,c) or "—"} | `{d}` |')
        lines+=['','Constraints:','']+[f'- `{v}`' for v in constraints(t)]
        lines+=['','Explicit indexes:','']
        for i in sorted(t.indexes,key=lambda x:x.name):
            where=i.dialect_options['postgresql'].get('where')
            lines.append(f'- `{i.name}` ({", ".join(i.columns.keys())})'+(f' WHERE `{where}`' if where is not None else ''))
        if not t.indexes: lines.append('- None.')
        lines+=['']
lines+=['### Reconstruction / ORM cross-check','',
'All 22 tables match the ORM in column names, storage types, nullability and primary/foreign/unique/check constraints. PostgreSQL migration DDL makes launcher_control.id SERIAL (an INTEGER plus a sequence default); the ORM Python default of 1 suppresses SERIAL when creating tables from models. The dictionary records the migration DDL. Two migration-defined recovery indexes are also absent from ORM metadata. These three representation differences do not establish live schema drift. This documentation does not alter the model. See [migration](https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0007_launch_reservations.py#L18-L28), [ORM default](https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_models.py#L21-L29) and [PostgreSQL SERIAL semantics](https://www.postgresql.org/docs/16/datatype-numeric.html#DATATYPE-SERIAL).','']
lines += [f'- `{x}`' for x in DIFFS]
lines+=['', 'Alembic framework bookkeeping (`alembic_version`) is excluded from the 22 application tables: its DDL is not declared by application upgrades. No live catalog was inspected.','']
for r in [MEDIA, PROC]:
    prefix='media-' if r is MEDIA else 'processing-'
    covered={t for f in FIGURES if not f['main'] and f['slug'].startswith(prefix) for t in f['tables']}
    assert covered==set(r.md.tables),(prefix,covered^set(r.md.tables))
dictionary='\n'.join(lines)
(OUT/'W4-dictionary.md').write_text(dictionary)
# Keep the copy handed to the report coordinator in sync with the standalone appendix.
report=OUT/'W4.md'
if report.exists() and '## Appendix draft — full physical data dictionary' in report.read_text():
    report.write_text(report.read_text().split('## Appendix draft — full physical data dictionary',1)[0]+dictionary)
(OUT/'W4-figures.json').write_text(json.dumps(FIGURES,indent=2)+'\n')
print(json.dumps({'heads':[MCHAIN[-1],PCHAIN[-1]],'tables':22,'columns':sum(len(t.c) for r in [MEDIA,PROC] for t in r.md.tables.values()),'figures':len(FIGURES),'model_representation_differences':DIFFS},indent=2))
