"""Build only W4 documentation fragments and review page; never edits the deck."""
from pathlib import Path
import html, json, re
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
FOLDER=OUT.parent
FIGS=json.loads((OUT/'W4-figures.json').read_text())
B='https://github.com/Collaboration95/dc2/blob/76282d3/'
def ref(path,n,end=None): return B+path+'#L'+str(n)+(f'-L{end}' if end else '')
def cite(path,n,label=None,end=None): return f'<a href="{ref(path,n,end)}">{html.escape(label or path+":"+str(n)+(f"-{end}" if end else ""))}</a>'
def jump(target,label):
    # The coordinator's existing deck accepts numeric hashes, not section IDs.
    # Resolve the retained ID at click time so integration may renumber sections.
    handler="event.preventDefault();event.stopPropagation();location.hash=String([...document.querySelectorAll('#stage > section.slide')].findIndex(s=>s.id==='w4-"+target+"')+1)"
    return f'<a class="pl" style="font-size:16px" href="#w4-{target}" onclick="{handler}">{label}</a>'
S=[]
def slide(id,title,body,notes,comment='NEW backup',main=False,tag='ARCHSS · Physical data view / PE · schemas'):
    no=('M' if main else 'B')+str(sum(('data-kind="main"' if main else 'data-kind="back"') in s for s in S)+1)
    route=jump('adr','Why PostgreSQL? · backup') if id=='stores' else jump('stores','Return to stores') if id=='adr' else ''
    S.append(f'''<!-- {comment} -->
<section class="slide" id="w4-{id}" data-kind="{'main' if main else 'back'}" data-num="W4-{no}">
<h1>{title}</h1>
<div style="font:600 15px Menlo,monospace;color:#64748b;margin:-10px 0 8px">{tag}</div>
<div class="body">{body}</div>
<div class="sec">{'Data' if main else 'Backup'}</div><div class="foot"><span>FlickPond · Main 76282d3</span>{route}<span>W4-{no}</span></div>
<aside class="notes">{notes}</aside>
</section>''')
def table(head,rows,size=22):
    return f'<table class="tbl" style="font-size:{size}px;line-height:1.2"><thead><tr>'+''.join(f'<th style="font-size:{size}px;padding:8px 10px">{x}</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td style="padding:8px 10px">{x}</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
def p(t): return f'<p style="font-size:23px;line-height:1.25;margin:12px 10px 0">{t}</p>'
store=table(['Store / owner','Persistent model','Consistency / retention'],[
['Aurora media cluster<br><b>Media</b>','media_db: users, assets, upload/source pins,<br>projections, inbox/outbox','Local SQL transactions; result projection is eventual.<br>Rows retained; backup: 1 day.'],
['Aurora processing cluster<br><b>Processing</b>','processing_db: jobs, attempts, guards,<br>retry/cleanup and delivery/launcher records','Local SQL transactions; DB-time fenced leases.<br>Rows retained; backup: 1 day.'],
['S3 SourceBucket<br><b>Media</b>','Versioned source bytes; adopted staging uploads<br>and copied edit sources','Exact VersionId pin; asynchronous version cleanup.<br>No active-object age expiry.'],
['S3 OutputBucket<br><b>Processing</b>','Primary + HLS objects under attempt UUID','Fenced SQL publication; async version cleanup.<br>No active-object age expiry.'],
['4 SQS queues + 4 DLQs<br><b>Media / Processing</b>','processing-commands · processing-work<br>processing-work-short* · media-results','At-least-once + SQL dedupe/replay.<br>Queues 7 days; DLQs 14; redrive after 5 receives.'],
['Supporting stores<br><b>Platform / operations</b>','Frontend S3; SSM configuration/activity hints;<br>CloudWatch logs; local operator journals','Versioned static assets; hints are not job authority.<br>Logs 7 days; supporting schemas in backup.']
],20)
slide('stores','Each service owns its durable state',store+p('<b>PostgreSQL commits state with inbox/outbox records;</b> JSONB embeds nested metadata.'),
'Point to the two SQL owners, then distinguish object bytes, transit messages and operational hints. This is the configured separate-cluster baseline with short encodes enabled, not a live-resource census. Shared-cluster configuration is also supported. SQL row retention means no general hard-purge job; it is not a backup period. '+cite('scripts/aws/v1/definitions.py',63,end=78)+' '+cite('scripts/aws/v1/definitions.py',501)+' '+cite('scripts/aws/v1/definitions.py',548,end=595)+' '+cite('scripts/aws/v1/definitions.py',596)+' '+cite('scripts/aws/v1/definitions.py',632)+' '+cite('delivery/sql.py',18)+' '+cite('delivery/sql.py',36)+' '+cite('media/projections.py',69)+' '+cite('processing/lifecycle.py',24)+' '+cite('media/services/direct_intake.py',234)+' '+cite('processing/recovery.py',113,end=187)+'. *Short lane and its DLQ are conditional on ShortEncodes. Supporting-store schema and source anchors are on the operational-store backup.',comment='REPLACES s26',main=True)

for f in FIGS[:2]:
    sources=' '.join(cite(path,n) for path,n in f['sources'])
    notes='Point at the PKs, then follow the crow’s-foot ends from each parent to its children. A dot means NOT NULL and ? means nullable. This main figure selects key columns; every column appears in backup and the report. '+sources
    if f['slug']=='media-main':
        title='Media owns assets, pins and read projections'
        notes+=' UploadReservation.asset_id is unique but has no FK to assets. Finalization keeps the pin on the reservation. The diagram label asset_source_versions maps to ORM SourceVersion, not an invented class. processing_job_id and source_asset_id are plain UUIDs without local or cross-database FKs. '+cite('media/services/direct_intake.py',43)+' '+cite('media/services/direct_intake.py',149)
    else:
        title='Processing owns each job and its fenced attempts'
        notes+=' current_attempt_id is DEFERRABLE INITIALLY DEFERRED and is not UNIQUE: the SQL reverse cardinality is zero-to-many. lock_pair additionally requires the attempt to belong to that job. SubmissionGuard.job_id is nullable and not unique. Claim/finish use a lease token and database time; deadline_at is shown in full backup. '+cite('processing/lifecycle.py',20)+' '+cite('processing/lifecycle.py',38)
    slide(f['slug'],title,f'<img src="assets/uml/W4-{f["slug"]}.svg" alt="{html.escape(f["title"])}" style="max-width:1180px;max-height:520px;display:block;margin:0 auto">',notes,comment='NEW after s26',main=True)

keys=table(['Namespace','Key / descriptor','Authority'],[
['Direct upload','<code>staging/{owner}/{reservation}/source</code>','Adopted in place; UploadReservation<br>pins the exact S3 VersionId.'],
['Edit-derived source','<code>sources/{owner}/{asset}/source</code>','Verified parent primary copied to a new Asset;<br>asset_source_versions stores its pin.'],
['Primary output','<code>jobs/{job}/attempts/{attempt_uuid}/<br>primary.{mp4,mkv,mp3}</code>','Attempt UUID isolates writes.<br>SQL finish fences publication.'],
['HLS output','<code>…/hls/master.m3u8<br>…/hls/v{n}/index.m3u8<br>…/hls/v{n}/seg%05d.ts</code>','Plain uploads only; master uploaded last.<br>Only master is in the output descriptor list.']
],23)
slide('keys','Attempt UUIDs isolate each output namespace',keys+p('Deleting an Asset triggers asynchronous deletion of object versions. Cleanup horizons bound rescans; they do not expire active videos.'),
'Point at attempt_uuid: it is Attempt.id, never attempt_number. The prefix in output_prefix takes a UUID; the integer numbers retries. An accepted direct upload stays at staging/, and source_for_asset reads the finalized reservation before derived-source pins. HLS is attempted only with empty operations, and failure can leave the primary available. The buckets are versioned/private; physical names are deployment outputs. No S3 lifecycle rule or general active-video expiry is configured. '+cite('processing/lifecycle.py',20)+' '+cite('media/services/direct_intake.py',99)+' '+cite('media/services/direct_intake.py',43)+' '+cite('media/services/v1_lifecycle.py',105)+' '+cite('processing/worker/tasks.py',16)+' '+cite('media_engine/hls.py',43)+' '+cite('media/recovery_v1.py',39)+' '+cite('processing/recovery.py',113,end=187)+' '+cite('scripts/aws/v1/definitions.py',548,end=595),comment='REPLACES s27',main=True)

for i,f in enumerate(FIGS[2:]):
    subjects={
    'media-assets':'Media enforces account and source uniqueness',
    'media-upload':'Finalized uploads require a source version pin',
    'media-pins':'Derived assets retain an immutable source pin',
    'media-projection':'Media versions its local result projection',
    'media-intents':'A composite request key makes creation replayable',
    'media-retry':'The legacy retry ledger remains in the schema',
    'media-cleanup':'Media retains deletion progress across retries',
    'media-delivery':'Media persists message identity and relay progress',
    'processing-attempts':'Job and Attempt preserve the current execution fence',
    'processing-intents':'Cancellation can precede a Job',
    'processing-cleanup':'Processing retains cleanup authority per attempt',
    'processing-delivery':'Processing stages work and result envelopes durably',
    'processing-bindings':'SQL records state versions and unique task names',
    'processing-launcher':'The launcher retains its gate and replay request'}
    note='Point at the coloured tables: all their columns are shown. Grey entities, where present, repeat only the referenced key from another sheet. Read each FK separately; ID names do not imply a relationship. PK/UK groups, CHECKs, server defaults and explicit indexes are fully listed in the generated appendix. '+ ' '.join(cite(path,n) for path,n in f['sources'])
    if f['slug']=='media-upload': note+=' UK3(owner_id, request_id) is one composite uniqueness constraint. asset_id is UK without FK; finalized_at IS NOT NULL requires version_id NOT NULL and not empty or literal null. '+cite('media/migrations/versions/0007_finalized_requires_pin.py',14)
    if f['slug']=='media-retry': note+=' Native V1 retry uses a staged command. The table is retained; it must not be presented as a mandatory V1 write. '+cite('media/services/v1_lifecycle.py',50)+' '+cite('legacy/media_peer/lifecycle.py',156)
    if f['slug']=='processing-attempts': note+=' The deferred FK does not constrain an Attempt to the same Job; lock_pair checks that. The reverse FK multiplicity is zero-to-many because current_attempt_id is not unique. source_url is an empty legacy placeholder and source_url_expires_at gets DB time in native V1. Two migration indexes are absent from the ORM: ix_attempts_recovery and ix_cleanup_intents_due. '+cite('processing/lifecycle.py',28)+' '+cite('processing/messaging.py',281)+' '+cite('processing/migrations/versions/0002_lifecycle.py',32)+' '+cite('processing/migrations/versions/0006_cleanup_retirement.py',23,end=29)
    if f['slug']=='processing-intents': note+=' submission_guards.job_id permits null and is not unique. retry_requests has both job_id and attempt_id foreign keys; both cascade on delete.'
    if f['slug']=='processing-cleanup': note+=' Both attempt_id and job_id are foreign keys with ON DELETE CASCADE. Retired cleanup rows remain as audit; only a successful scan beyond the horizon retires them. '+cite('processing/recovery.py',113,end=187)
    if f['slug']=='processing-launcher': note+=' There is no FK between these tables, or from launch_reservations to attempt_tasks. id=1 is a CHECK; no row is implied by DDL. The migration compiles id as PostgreSQL SERIAL, while the ORM supplies Python default 1; the dictionary records the migration sequence default. Tables are read only when the optional unattended launch feature is enabled. '+cite('processing/launcher_models.py',21,end=29)+' '+cite('processing/launcher.py',238)
    slide(f['slug'],subjects[f['slug']],f'<img src="assets/uml/W4-{f["slug"]}.svg" alt="{html.escape(f["title"])}" style="max-width:1180px;max-height:520px;display:block;margin:0 auto">',note,comment='REPLACES s65' if i==0 else 'NEW backup')

# Complete typed wire envelope (all ten fields; nullable fields still required).
left=table(['Envelope field','JSON type / rule'],[
['schema_version','integer = 1'],['message_id','UUID string'],['kind','submit | retry | cancel | work | result'],['owner_id','UUID string'],['asset_id','UUID string']],22)
right=table(['Envelope field','JSON type / rule'],[
['job_id','UUID string | null'],['attempt_id','UUID string | null'],['state_version','strict integer ≥ 0'],['source','Source object | null'],['payload','JSON object']],22)
slide('envelope','All queue lanes use the same ten-field envelope',f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:28px">{left}{right}</div>'+p('All keys must exist. A nullable value is JSON <code>null</code>, not an omitted field. The lane does not change the schema.')+p('Source has six fields: <code>bucket, key, version_id, sha256, size_bytes, content_type</code>.'),
'Point at message_id for dedupe, state_version for ordering and source for immutable identity. contracts.v1.Envelope is the normative top-level schema; payload business semantics are validated separately by the consumer. Only V1 is accepted at this baseline. Unknown top-level/source fields are dropped before fingerprinting. Payloads reject credential/token/media-byte-like key names, HTTP(S) URLs and nonfinite JSON numbers. Queue policies and delivery.sqs producer/consumer lanes establish authority; schema validation alone does not authenticate a sender. '+cite('contracts/v1.py',20,end=44)+' '+cite('contracts/v1.py',158,end=218)+' '+cite('contracts/v1.py',132,end=154)+' '+cite('delivery/sqs.py',1))

slide('kinds','Five message kinds cross four physical lanes',table(['Kind / lane','Produced shape and consumer semantics'],[
['submit → processing-commands','Source required; payload <code>{operations:[Operation]}</code>.<br>Normal finalize: job_id=null, attempt_id=null, state_version=0.'],
['retry → processing-commands','Stored Source emitted; payload <code>{}</code>; operations stay on Job.<br>Consumer request identity: payload.request_id if present, else message_id.'],
['cancel → processing-commands','Source null; payload <code>{}</code>; job/attempt may be null.<br>SubmissionGuard makes cancel-before-submit durable.'],
['work → processing-work<br>or processing-work-short*','Job, Attempt and Source required; payload <code>{operations:[Operation]}</code>.<br>Worker binds envelope to stored Job before reading S3.'],
['result → media-results','Normal payload <code>{status, outputs:[Output], error, attempt_number}</code>.<br>Job/Attempt/Source + monotonic version identify the result.']
],22)+p('*Optional short lane uses the same work schema. Each lane has its own DLQ; a DLQ stores the original message body.'),
'Point down the five rows and separate three command kinds from work/result. This table combines Envelope rules with actual producer shape and consumer checks; Envelope alone does not impose every payload rule. All four queue names here are logical delivery-lane names, not invented physical AWS names. ShortEncodes controls the extra queue and DLQ. Results are snapshots, not event sourcing. Cancel-before-submit acknowledgement is the precise result exception on the next backup. '+cite('media/messaging.py',31)+' '+cite('media/services/v1_lifecycle.py',17)+' '+cite('processing/messaging.py',232)+' '+cite('processing/messaging.py',78)+' '+cite('processing/messaging.py',325)+' '+cite('scripts/aws/v1/definitions.py',596)+' '+cite('scripts/aws/v1/definitions.py',632))

slide('cancel-ack','A cancellation result can acknowledge only a guard',
'<pre style="font:24px/1.5 Menlo,monospace;margin:0 12px">kind: "result"\njob_id: null, attempt_id: null, source: null\nstate_version: 0   // producer value\npayload: {\n  "status": "cancelled",\n  "cancellation_confirmed": true,\n  "command_message_id": "&lt;UUID of cancel command&gt;"\n}</pre>'+p('The payload has exactly these three keys. Media matches the command ID to its cancel outbox row before source cleanup.'),
'Point at all three null identities. No synthetic Job or Attempt is created for this acknowledgement. Envelope validates the exact payload keys; the producer sets state_version=0, while the generic envelope only enforces nonnegative integers. Media confirm_cancellation checks the matching cancel outbox identity. The normal result row does not cover this exception. '+cite('contracts/v1.py',192,end=212)+' '+cite('processing/messaging.py',186)+' '+cite('media/projections.py',139))

slide('json-descriptors','JSONB embeds source and output descriptors',table(['Value','Stored shape','Rules'],[
['Source','<code>{bucket, key, version_id,<br>sha256, size_bytes, content_type}</code>','Nonempty strings; real VersionId; lowercase 64-hex hash.<br>Strict integer size: 1…104,857,600 bytes.'],
['Output','<code>{kind, object_key, media_type,<br>size_bytes, sha256}</code>','kind: primary | hls_manifest.<br>DTO permits null size/hash; Processing finish requires<br>positive size/hash, unique kinds and exactly one primary.'],
['Launch payload','<code>{…RunTask request…}</code>','Operational replay JSON, with stable ECS identity<br>and finite worker overrides; not a video document.'],
['Outbox body','<code>Envelope</code> canonical JSON','Canonical ordering → body_hash.<br>Inbox keeps message identity + hash, not full body.']
],22)+p('Source VersionId is explicit. Output descriptors use an attempt UUID prefix and do not carry an output VersionId.'),
'Point at the DTO versus publication distinction. Native V1 source is contracts.Source, not the old processing.schemas.Source containing asset_id/revision/media_type. Source checks include prefix binding and pinned download hash/size. Media independently requires one primary and a valid output namespace, but its DTO does not reproduce every checksum requirement from Processing.finish. '+cite('contracts/v1.py',100,end=106)+' '+cite('processing/schemas.py',90,end=95)+' '+cite('processing/lifecycle.py',184)+' '+cite('media/projections.py',69)+' '+cite('processing/worker/source.py',31)+' '+cite('processing/launcher.py',90)+' '+cite('delivery/envelope.py',1)+' '+cite('delivery/sql.py',18))

slide('operations','Operations have types and source-aware checks',table(['Operation','params shape','Validation'],[
['clip','<code>{start:number, end:number}</code>','Finite numbers; start ≥ 0; end > start.'],
['crop','<code>{x:int, y:int, w:int, h:int}</code>','Strict integers; x,y ≥ 0; w,h ≥ 1.'],
['downscale / upscale','<code>{height:int}</code>','Strict positive integer.'],
['convert','<code>{format:"mkv" | "mp3"}</code>','Enumerated target format.']
],25)+p('<code>operations: [{operation, params}, …]</code> — at most five; no repeated operation; no simultaneous upscale and downscale.')+p('The worker probes the accepted source and validates bounds before FFmpeg. Browser metadata is not the authority.'),
'Point at the parameter types, then distinguish syntactic validation from source-aware validity. Both Media edit validation and Processing command validation check the operation set; media_engine validates operations against actual probe data. Empty operations select ordinary upload processing, including HLS. '+cite('processing/schemas.py',15,end=20)+' '+cite('media/schemas/edit.py',1)+' '+cite('processing/messaging.py',260,end=271)+' '+cite('media_engine/validation.py',1)+' '+cite('processing/worker/tasks.py',16))

slide('support-stores','Operational stores have limited responsibilities',table(['Store / owner','Schema / key','Consistency / retention'],[
['Frontend S3 / platform','<code>index.html</code>; <code>stem.&lt;hash10&gt;.js/css</code>;<br><code>vendor/…</code>','Versioned, private; index uploaded last.<br>Cache policy differs from object retention.'],
['SSM activity hints / service','<code>/dc2/{env}/activity/{media|processing}/<br>{touched|quiet}</code>','String epoch; quiet = "checked_epoch due_epoch".<br>Missing/malformed hints cause full SQL pass.'],
['SSM configuration / service','Owner-specific runtime/migration DSNs;<br>Media JWT secret','Secret configuration, not user/domain records.<br>Values omitted; no general TTL declared.'],
],21),
'Point at authority: SQL owns domain state; activity markers can skip a pass only after validation. touched is String epoch seconds; quiet holds checked and due epochs, initial zero is not quiet. Frontend build manifest records key, content type, cache control, size, SHA-256 and MD5; it is deployment metadata. JWT secret/DSN values must never appear in slides. S3 retain policy is not an age-expiry TTL. No DynamoDB, MongoDB or Redis store is in the inspected V1 application graph. '+cite('scripts/aws/v1/definitions.py',548,end=595)+' '+cite('scripts/aws/v1/frontend.py',96,end=125)+' '+cite('scripts/aws/v1/frontend.py',63)+' '+cite('scripts/aws/v1/definitions.py',899)+' '+cite('runtime_support/activity.py',1)+' '+cite('scripts/aws/v1/definitions.py',501)+' '+cite('scripts/aws/v1/definitions.py',823)+' '+cite('scripts/aws/v1/definitions.py',1795)+' '+cite('scripts/aws/v1/deploy.py',506)+' '+cite('scripts/aws/journal.py',14))

slide('support-ops','Diagnostics and journals do not own domain state',table(['Store / owner','Schema / key','Consistency / retention'],[
['Secrets Manager / platform','Aurora-managed master password','Bootstrap credential, not an account store.<br>Managed secret lifecycle.'],
['CloudWatch Logs / service','Function/task log events','Diagnostics only; template retention 7 days.'],
['Local JSON journals / operator','Deployment/session/release state','Outside product request path;<br>operator files, no central expiry declared.']
],24),
'Point at each owner and the distinction between bootstrap credentials, diagnostics and operator state. Aurora requests a managed master password; logs have seven-day template retention; local journal files have no central expiry declared. These records do not replace Job/Attempt or inbox/outbox recovery authority. '+cite('scripts/aws/v1/definitions.py',501)+' '+cite('scripts/aws/v1/definitions.py',823)+' '+cite('scripts/aws/v1/definitions.py',1795)+' '+cite('scripts/aws/v1/deploy.py',506)+' '+cite('scripts/aws/journal.py',14))

slide('adr','PostgreSQL preserves the implemented write guarantees',table(['Access pattern','Current SQL guarantee','MongoDB / DynamoDB redesign'],[
['Own Asset + result by ID / owner list','Local Asset/projection join; version checks','Strong document/item fit; retain owner/deletion<br>filtering, paging and conditional updates.'],
['Message-driven state transition','One transaction: inbox + state + outbox','Mongo multi-document transaction or bounded embedded<br>events; DynamoDB item transaction or CDC/outbox.'],
['Retry / execution claims','Unique email / asset / task identities; Job lock;<br>token + deadline fences checked with DB time','Preserve uniqueness reservations, current Attempt,<br>conditional claims and an explicit clock policy.'],
['Due work / cleanup / capacity','Due-time indexes; locked claims; singleton gate','Design due-time partitions/indexes and capacity gate;<br>account for retries, conflicts and reconciliation.']
],21)+p('<b>Decision:</b> retain PostgreSQL authority; keep nested metadata in JSONB and media bytes in S3.')+p('<b>Revisit:</b> measure read latency, volume and idle cost; trial an owner/asset read projection with reconciliation and deletion defined.'),
'Point first to the document-friendly read, then the three write-path obligations. This is a proposed ADR for report adoption, not an existing implementation or benchmark. MongoDB supports atomic single-document writes and multi-document ACID transactions; DynamoDB supports conditional ACID item transactions. Both are feasible. Directly sending to SQS still leaves a dual-write gap. A document read store may fit, but compare it with the existing JSONB projection before adding operations cost. The stores slide links directly to this backup; use Return to stores to resume the main talk. MongoDB transactions require a replica set or sharded cluster, and unique indexes must respect the shard-key rules. DynamoDB TransactWriteItems permits up to 100 actions on distinct items, with 4 MB total, in one account/Region; conditions can be attached to writes. Global secondary indexes do not enforce unique secondary values, so reserve those identities atomically. Code basis: '+cite('media/repositories/assets.py',81,end=93)+' '+cite('media/projections.py',36)+' '+cite('delivery/sql.py',18)+' '+cite('delivery/sql.py',36)+' '+cite('processing/lifecycle.py',24)+' '+cite('processing/messaging.py',325)+' '+cite('processing/launcher.py',238)+'. External R5 F4/F5: <a href="https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html">AWS transactional outbox</a>; <a href="https://www.mongodb.com/docs/manual/core/transactions/">MongoDB transactions</a>; <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html">DynamoDB transactions</a>; <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/data-modeling-foundations.html">DynamoDB modelling foundations</a>; <a href="https://www.mongodb.com/docs/manual/core/transactions-production-consideration/">MongoDB transaction deployment requirements</a>; <a href="https://www.mongodb.com/docs/manual/core/index-unique/">MongoDB unique indexes and shard-key restrictions</a>; <a href="https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html">TransactWriteItems limits</a>; <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html">DynamoDB conditional writes</a>; <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html">DynamoDB nonunique secondary indexes</a>.',tag='ARCHSS · Data-store decision / PE · transaction boundaries')
(FOLDER/'slides/W4.html').write_text('\n\n'.join(S)+'\n')
# Standalone private preview, same CSS and per-slide navigation; image URLs point back to site.
deck=(ROOT/'project-documentation/presentation/site/deck.html').read_text(); css=re.search(r'<style>(.*?)</style>',deck,re.S)[1]
sections='\n'.join(S).replace('src="assets/uml/','src="../../../site/assets/uml/')
preview='<!doctype html><html><head><meta charset="utf-8"><title>W4 data slides review</title><style>'+css+'</style></head><body><div id="stage">'+sections+'</div><script>const s=[...document.querySelectorAll(".slide")]; function show(){let n=Math.max(0,Math.min(s.length-1,Number(location.hash.slice(1)||1)-1));s.forEach((e,i)=>e.classList.toggle("active",i===n));document.title="W4 "+(n+1)+"/"+s.length;}function scale(){document.querySelector("#stage").style.transform="scale("+Math.min(innerWidth/1280,innerHeight/720)+")";}onhashchange=show;onresize=scale;onkeydown=e=>{let n=Number(location.hash.slice(1)||1);if(e.key==="ArrowRight")location.hash=Math.min(s.length,n+1);if(e.key==="ArrowLeft")location.hash=Math.max(1,n-1);};show();scale();</script></body></html>'
(OUT/'W4-preview/index.html').write_text(preview)
print(f'{len(S)} slides; {sum("data-kind=\"main\"" in s for s in S)} main; {len(FIGS)} ER figures')
