"""Generate design-only OpenAPI documents. Does not import or change application code."""
from pathlib import Path
from copy import deepcopy
import json
O=Path(__file__).parent
uuid={'type':'string','format':'uuid'}
text={'type':'string'}
time={'type':'string','format':'date-time'}
url={'type':'string','format':'uri'}
def obj(props,required=(),strict=True):return {'type':'object','properties':props,'required':list(required),'additionalProperties':not strict}
def ref(name):return {'$ref':'#/components/schemas/'+name}
def array(x,**kw):return {'type':'array','items':x,**kw}
S={
'Error':obj({'error':text},['error'],False),
'ValidationError':obj({'detail':array(obj({'loc':array({'type':['string','integer']}),'msg':text,'type':text},['loc','msg','type'],False))},['detail'],False),
'Credentials':obj({'email':{'type':'string','format':'email'},'password':{'type':'string','minLength':8,'maxLength':72}},['email','password']),
'User':obj({'id':uuid,'email':{'type':'string','format':'email'},'role':{'type':'string','enum':['user','operator']}},['id','email','role'],False),
'Accepted':obj({'job_id':{**uuid,'description':'Legacy name for the Media Management asset ID. Not the internal Processing job ID.'}},['job_id'],False),
'PublicJob':obj({'id':uuid,'filename':text,'status':{'type':'string','enum':['queued','processing','done','failed']},'submission_status':{'type':'string','enum':['pending','submitted','error'],'description':'Additive field. Pending is durable intake awaiting Processing.'},'output_url':url,'hls_url':text,'error':text},['id','filename','status'],False),
'Source':obj({'asset_id':uuid,'revision':{'type':'integer','minimum':1},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'size_bytes':{'type':'integer','minimum':1},'media_type':text},['asset_id','revision','sha256','size_bytes','media_type']),
'Output':obj({'kind':{'type':'string','enum':['primary','hls_manifest']},'object_key':{'type':'string','minLength':1,'description':'Relative key under the configured output store. Never an arbitrary URL/bucket.'},'media_type':text,'size_bytes':{'type':'integer','minimum':0},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},['kind','object_key','media_type'],False),
'Attempt':obj({'attempt_id':uuid,'number':{'type':'integer','minimum':1},'state':{'type':'string','enum':['queued','processing','succeeded','failed','abandoned','cancelled']},'queued_at':time,'started_at':time,'finished_at':time,'error':text},['attempt_id','number','state','queued_at'],False),
'ProcessingJob':obj({'job_id':uuid,'asset_id':uuid,'owner_id':uuid,'status':{'type':'string','enum':['queued','processing','done','failed']},'source':ref('Source'),'current_attempt':ref('Attempt'),'outputs':array(ref('Output')),'error':text,'created_at':time,'updated_at':time},['job_id','asset_id','owner_id','status','source','current_attempt','outputs','created_at','updated_at'],False),
'SourceAccess':obj({'source_url':url,'expires_at':time,'source':ref('Source')},['source_url','expires_at','source']),
}
# Preserve the inherited edit request variants without inventing a new editor.
ops=[]
for name,props,req in [
('clip',{'start':{'type':'number','minimum':0},'end':{'type':'number','exclusiveMinimum':0}},['start','end']),
('crop',{'x':{'type':'integer','minimum':0},'y':{'type':'integer','minimum':0},'w':{'type':'integer','minimum':1},'h':{'type':'integer','minimum':1}},['x','y','w','h']),
('downscale',{'height':{'type':'integer','minimum':1}},['height']),
('upscale',{'height':{'type':'integer','minimum':1}},['height']),
('convert',{'format':{'type':'string','enum':['mkv','mp3']}},['format'])]:
 ops.append(obj({'operation':{'const':name},'params':obj(props,req)},['operation','params']))
S['EditOperation']={'oneOf':ops,'description':'Also enforce unique operation names, end > start, no simultaneous up/downscale and source geometry checks in contract tests.'}
S['EditRequest']=obj({'operations':array(ref('EditOperation'),minItems=1,maxItems=5)},['operations'])
S['SubmitJob']=obj({'asset_id':uuid,'owner_id':uuid,'source':ref('Source'),'source_url':url,'source_url_expires_at':time,'operations':array(ref('EditOperation'),minItems=1,maxItems=5)},['asset_id','owner_id','source','source_url','source_url_expires_at'])
S['RetryRequest']=obj({'retry_request_id':uuid},['retry_request_id'])
S['SourceAccessRequest']=obj({'revision':{'type':'integer','minimum':1}},['revision'])
def parameter(name,where,schema,required=True,description=''):
 return {'name':name,'in':where,'required':required,'schema':deepcopy(schema),'description':description}
def response(desc,schema=None,media='application/json'):
 r={'description':desc}
 if schema:r['content']={media:{'schema':schema}}
 return r
def body(schema,media='application/json'):
 return {'required':True,'content':{media:{'schema':schema}}}
def error_res(codes):return {str(c):response({401:'Missing or invalid credentials.',403:'Valid caller lacks this operation.',404:'Resource absent or belongs to another owner.',409:'State or idempotency conflict.',410:'Previously accepted item is deleted.',413:'File exceeds 100 MiB.',415:'Unsupported or unrecognised media.',422:'Request validation failed.',503:'Dependency unavailable. Do not report unconfirmed success.'}[c],ref('ValidationError' if c==422 else 'Error')) for c in codes}
def operation(id,summary,success,params=(),request=None,codes=(401,404,422,503),description='',security=None):
 r={'operationId':id,'summary':summary,'description':description,'responses':{**success,**error_res(codes)}}
 if params:r['parameters']=list(params)
 if request:r['requestBody']=request
 if security is not None:r['security']=security
 return r
def document(title,server,security,scheme):
 return {'openapi':'3.1.0','info':{'title':title,'version':'1.0.0-design','description':'Step 05 design specification, 9 October 2026. Not an implemented API. Baseline 8854537. Proposed behavior and compatibility changes are recorded in the design pack.'},'servers':[{'url':server}],'security':security,'paths':{},'components':{'securitySchemes':scheme,'schemas':deepcopy(S)}}
idp=parameter('job_id','path',uuid,description='Public legacy identifier: Media Management asset_id.')
assetp=parameter('asset_id','path',uuid)
jobp=parameter('job_id','path',uuid,description='Internal Processing job UUID.')
owner=parameter('X-Owner-Id','header',uuid,description='Derived and set by Media Management after session/role authorisation. Processing compares it with persisted ownership. Never trust a public caller-supplied header.')
key=parameter('Idempotency-Key','header',uuid,False,'Optional for legacy callers. New web/CLI clients reuse a UUID for retries of one logical request. A different request with the same key is 409. Deleted prior result is 410.')
limits=[parameter('limit','query',{'type':'integer','minimum':1,'maximum':200,'default':50},False),parameter('offset','query',{'type':'integer','minimum':0,'default':0},False)]
pub=document('FlickPond public facade','/api',[{'SessionCookie':[]}],{'SessionCookie':{'type':'apiKey','in':'cookie','name':'access_token','description':'Existing signed JWT cookie. Secure, HttpOnly, SameSite=Strict. CLI uses an HTTPS cookie jar. Cookie expiry is inherited; logout does not revoke a copied token.'}})
P=pub['paths']
for route,status in [('register',201),('login',200)]:
 op=operation(route,route.title(),{str(status):response('User plus Secure HttpOnly Set-Cookie header.',ref('User'))},request=body(ref('Credentials')),codes=(401,422,503),security=[])
 op['responses'][str(status)]['headers']={'Set-Cookie':{'description':'access_token cookie with Secure, HttpOnly, SameSite=Strict and configured lifetime.','schema':text}}
 if route=='register':op['responses']['409']=response('Email already registered. Preserve the inherited empty response body.')
 P['/auth/'+route]={'post':op}
P['/auth/logout']={'post':operation('logout','Clear session cookie',{'204':response('Clears access_token cookie. No response body.')},codes=(),security=[])}
P['/auth/me']={'get':operation('currentUser','Read the current user',{'200':response('Current user.',ref('User'))},codes=(401,503))}
P['/health']={'get':operation('health','Liveness only',{'200':response('Process is responsive.',obj({'status':{'const':'ok'}},['status']))},codes=(),security=[])}
P['/upload']={'post':operation('uploadAsset','Upload an owned source',{'202':response('Source and asset are durable. Processing may still be pending.',ref('Accepted'))},[key],body(obj({'file':{'type':'string','format':'binary','description':'Supported video, maximum 104857600 file bytes. Multipart overhead is not video size.'}},['file']),'multipart/form-data'),(401,409,410,413,415,422,503),description='MM validates and stores the source, commits a pending Asset, then attempts SubmitJob. A temporary Processing outage still returns 202 after durable intake. Pending maps to status=queued plus submission_status=pending. Object/DB intake failure is 503. An upload request without an idempotency key creates a fresh asset.')}
P['/jobs']={'get':operation('listAssets','List the owner’s assets',{'200':response('Ordered by created_at descending then id. Same array response as the baseline.',array(ref('PublicJob')))},limits,codes=(401,422,503),description='Media Management pages its own assets, then requests submitted jobs as an owner-filtered batch. Pending assets appear as queued. If submitted state cannot be read, return 503 instead of inventing a current state.')}
P['/jobs/{job_id}']={
'get':operation('getAsset','Get status and playback access',{'200':response('Owner-scoped public projection. Only done includes playback links. Failed includes a safe error.',ref('PublicJob'))},[idp],description='Translate the public asset ID into the internal Processing job ID. Pending submission is queued/pending. If Processing is unavailable for a submitted asset, return 503. Never expose raw keys, service credentials or another owner’s record.'),
'delete':operation('deleteAsset','Delete an owned library item',{'204':response('Asset tombstone and cleanup intent are durable. No response body.')},[idp],description='Preserve inherited delete UI. Hide the asset immediately, deny new source/playback grants, then call DELETE /internal/v1/assets/{asset_id}/job and reconcile private object cleanup. Existing signed URLs remain capabilities until expiry or object removal. Repeat delete by same owner is 204 while tombstone retained.')}
P['/jobs/{job_id}/retry']={'post':operation('retryAsset','Retry using stored source',{'202':response('Retry confirmed by Processing.',ref('Accepted'))},[idp,key],codes=(401,404,409,410,422,503),description='MM forwards one stable retry_request_id. A lost response is retried with the same key, never by re-uploading. Processing is authoritative: only failed may start a new attempt. An uncertain downstream result returns 503 with the same request key retained by the client.')}
P['/jobs/{job_id}/edit']={'post':operation('editAsset','Preserve the existing edit API',{'202':response('New derived Asset accepted.',ref('Accepted'))},[idp,key],body(ref('EditRequest')),(401,404,409,410,422,503),description='No new editor UI. After authorising the owner and completed source, copy its selected primary output into a new private immutable source. Persist immutable operations with the derived Asset and request key in one transaction before submission. Reconciliation replays these saved operations. A copy/commit failure must not report acceptance. The independent copy avoids deleting one item breaking another.')}
P['/jobs/{job_id}/hls/{path}']={'get':operation('getHls','Read playlist or signed segment redirect',{
'200':response('Playlist body. Keep relative references on this owner-checked route.',text,'application/vnd.apple.mpegurl'),
'307':{'description':'Segment redirect to a freshly signed HTTPS output URL.','headers':{'Location':{'schema':url,'description':'Short-lived signed URL.'}}}},[idp,parameter('path','path',{'type':'string','pattern':'^(?:v[0-9]{1,2}/)?[A-Za-z0-9_-]+\\.(?:m3u8|ts)$'},description='Framework catch-all path. Includes nested rendition names. Validate against the authorised output prefix.')],description='Never redirect playlists to the object store: relative segment URLs would lose signatures. Return Cache-Control: private, no-store for owner-scoped playlists.')}
P['/admin/jobs']={'get':operation('adminListAssets','Preserve operator library access',{'200':response('Operator-authorised array.',array(ref('PublicJob')))},limits,codes=(401,403,422,503),description='Require the existing operator role in MM. Group the asset page by actual owner when calling Processing. Never create an unscoped internal query.')}
P['/admin/jobs/{job_id}']={'delete':operation('adminDeleteAsset','Preserve operator deletion',{'204':response('Authorised tombstone and cleanup intent.')},[idp],codes=(401,403,404,422,503),description='Check operator role before resolving the target. Forward the asset’s recorded owner to Processing. No new admin product features.')}
proc=document('FlickPond Processing private API','/internal/v1',[{'MediaServiceToken':[]}],{'MediaServiceToken':{'type':'http','scheme':'bearer','description':'A high-entropy MM-to-Processing service secret from configuration. Distinct from user cookies and the reverse source-access token. Private network only.'}})
P=proc['paths']
P['/jobs']={
'post':operation('submitJob','Idempotent SubmitJob',{'201':response('New durable job and queued attempt.',ref('ProcessingJob')),'200':response('Existing job for the same immutable request.',ref('ProcessingJob'))},[owner],body(ref('SubmitJob')),(401,403,404,409,410,422,503),description='Reserve/lock the owner-bound submission_guards row for asset_id before accepting. A deleted guard returns 410. Unique asset_id. Header owner, body owner and persisted owner must agree; other-owner access is 404. source.asset_id must equal asset_id. Canonical request fingerprint includes source revision/digest/type/size and ordered operations, but excludes source_url and URL expiry. Same key with a changed fingerprint is 409. Commit job/attempt before enqueue. If queue write fails after commit, return the durable queued job and reconcile delivery; never create another job.'),
'get':operation('listJobs','Owner-filtered batch GetJobs',{'200':response('Only matching, nondeleted records. Missing requested assets are omitted.',array(ref('ProcessingJob')))},[owner,parameter('asset_ids','query',array(uuid,minItems=1,maxItems=200),description='Comma-separated requested asset UUIDs; batch aligns with the MM asset page.')],description='Owner filter must run in the database query. No unscoped list operation. MM detects missing submitted jobs as a reconciliation discrepancy, not done or failed evidence.')}
P['/jobs']['get']['parameters'][1].update(style='form',explode=False)
P['/jobs/{job_id}']={'get':operation('getJob','Owner-filtered GetJob',{'200':response('Internal job plus durable output references.',ref('ProcessingJob'))},[jobp,owner])}
P['/assets/{asset_id}/job']={'delete':operation('cancelAssetJob','Tombstone processing by stable Asset identity',{'204':response('Owner-bound cancellation guard committed. Job cancellation and output cleanup intent commit when a job exists.')},[assetp,owner],codes=(401,403,404,422,503),description='MM always cancels by asset_id, including when a Submit response was lost. Submit and cancellation lock the same persistent submission_guards row. Cancel-first creates a tombstone that rejects later same-owner Submit with 410. Submit-first tombstones its job, cancels attempts and schedules output cleanup. Another owner is 404. Same-owner repeated cancellation is 204. Retain guards throughout the demo environment. No FK to MM.')}
P['/jobs/{job_id}/retry']={'post':operation('retryJob','Idempotent RetryJob',{'202':response('New queued attempt, or current job for a replayed retry_request_id.',ref('ProcessingJob'))},[jobp,owner],body(ref('RetryRequest')),(401,403,404,409,410,422,503),description='First check the saved retry request under the owner. A replay returns the current job without a second transition, even if it has since finished. Otherwise lock the failed job, create one queued attempt and record retry_request_id in the same transaction. Nonfailed is 409. Enqueue after commit; reconcile queue failures.')}
mi=document('FlickPond source access private API','/internal/v1',[{'ProcessingServiceToken':[]}],{'ProcessingServiceToken':{'type':'http','scheme':'bearer','description':'Separate Processing-to-MM source-grant secret. Limited to this capability API. Not interchangeable with the MM-to-Processing secret.'}})
mi['paths']['/assets/{asset_id}/source-access']={'post':operation('refreshSourceAccess','Issue a fresh source read capability',{'200':response('Short-lived GET URL for one immutable source.',ref('SourceAccess'))},[assetp,owner],body(ref('SourceAccessRequest')),(401,403,404,409,422,503),description='MM checks asset owner, immutable source revision and nondeleted state in its own DB. Revision mismatch is 409. It does not call Processing or read its database. Processing checks the active attempt before making the call. Never accept caller-supplied object keys, buckets or arbitrary URLs. A dependency failure gives 503, not a fabricated URL.')}
for fn,doc in [('public.openapi.json',pub),('processing.openapi.json',proc),('media-internal.openapi.json',mi)]:
 (O/fn).write_text(json.dumps(doc,indent=2)+'\n')
print('Wrote 3 design-only OpenAPI contracts')
