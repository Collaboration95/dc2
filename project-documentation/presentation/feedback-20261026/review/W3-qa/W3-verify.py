"""Source, evidence-link and presentation checks for the W3 review only."""
from pathlib import Path
from lxml import etree, html
import ast, re, json, hashlib, subprocess, concurrent.futures
root=Path('project-documentation/presentation')
u=root/'site/assets/uml'; qa=root/'feedback-20261026/review/W3-qa'; png=root/'feedback-20261026/report-notes/W3-qa'
qa.mkdir(parents=True,exist_ok=True); png.mkdir(parents=True,exist_ok=True)
errors=[]; checks=[]
models={
'W3-03-a-intake-classes':{'I':('media/services/direct_intake.py',None),'S':('media/services/storage.py','Storage'),'U':('media/upload_models.py','UploadReservation'),'A':('media/models.py','Asset'),'O':('media/messaging_models.py','MediaOutbox')},
'W3-04-a-execution-classes':{'J':('processing/models.py','Job'),'A':('processing/models.py','Attempt'),'C':('processing/lifecycle.py','Claim'),'B':('processing/messaging_models.py','AttemptTask')},
'W3-05-a-projection-classes':{'P':('media/projections.py',None),'R':('media/projection_models.py','ProcessingProjection'),'S':('media/services/storage.py','Storage')},
'W3-10-b-classes':{'J':('processing/models.py','Job'),'A':('processing/models.py','Attempt'),'R':('processing/models.py','RetryRequest'),'C':('processing/lifecycle.py','Claim')},
'W3-18-lane-policy':{'L':('processing/short_lane.py',None),'P':('media_engine/probe.py','SourceProbe'),'N':('processing/short_lane.py','NotAdmitted')},
'W3-19-execution-adapters':{'T':('processing/worker/tasks.py',None),'S':('processing/worker/supervisor.py','Supervisor'),'I':('processing/worker/source.py','SourceStore'),'O':('processing/worker/storage.py','OutputStore')},
'W3-20-contract-classes':{'E':('contracts/v1.py','Envelope'),'S':('contracts/v1.py','Source')},
'W3-21-lease-functions':{'M':('processing/messaging.py',None),'L':('processing/lifecycle.py',None),'R':('processing/recovery.py',None)},
'W3-24-intake-types':{'R':('media/services/direct_intake.py','ReserveRequest'),'F':('media/services/direct_intake.py','FinalizeRequest'),'S':('media/upload_models.py','SourceVersion')},
}
def anno(n):
 if n is None:return None
 if isinstance(n,ast.Constant) and isinstance(n.value,str):return n.value
 if isinstance(n,ast.Subscript) and ast.unparse(n.value)=='Mapped':return ast.unparse(n.slice)
 return ast.unparse(n)
def signature(fn,implicit=False):
 args=fn.args;pos=args.posonlyargs+args.args;defs=[None]*(len(pos)-len(args.defaults))+list(args.defaults)
 vals=[]
 for a,d in zip(pos,defs):
  if implicit and a.arg in ('self','cls'):continue
  vals.append((a.arg,anno(a.annotation),ast.unparse(d) if d is not None else None))
 if args.vararg:vals.append(('*'+args.vararg.arg,anno(args.vararg.annotation),None))
 elif args.kwonlyargs:vals.append(('*',None,None))
 for a,d in zip(args.kwonlyargs,args.kw_defaults):vals.append((a.arg,anno(a.annotation),ast.unparse(d) if d is not None else None))
 if args.kwarg:vals.append(('**'+args.kwarg.arg,anno(args.kwarg.annotation),None))
 return vals,anno(fn.returns)
for stem,classes in models.items():
 txt=(u/(stem+'.puml')).read_text()
 blocks=re.findall(r'^class .*? as (\w+).*?\{\n(.*?)^\}',txt,re.M|re.S)
 for alias,body in blocks:
  path,cls=classes[alias]; tree=ast.parse(Path(path).read_text()); scope=tree if cls is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
  funcs={n.name:n for n in scope.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
  fields={n.target.id:n for n in scope.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)}
  constants={n.targets[0].id:n for n in scope.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
  for row in body.splitlines():
   row=row.strip();row=re.sub(r'^\{static\}\s*','',row);row=re.sub(r'^[+\-#~]\s*','',row)
   if not row:continue
   if '(' in row:
    m=re.fullmatch(r'(\w+)\((.*)\)(?::\s*(.*))?',row); name,params,ret=m.groups(); expected=funcs[name]
    synthetic=ast.parse('def '+name+'('+params+')'+(' -> '+ret if ret else '')+': pass').body[0]
    good=signature(synthetic)==signature(expected,implicit=cls is not None)
    checks.append({'figure':stem,'member':(cls+'.' if cls else '')+name,'source':path,'line':expected.lineno,'kind':'operation','matches':good})
    if not good:errors.append((stem,row,signature(synthetic),signature(expected,implicit=cls is not None)))
   elif ':' in row:
    name,typ=map(str.strip,row.split(':',1)); n=fields[name];good=typ==anno(n.annotation)
    checks.append({'figure':stem,'member':cls+'.'+name,'source':path,'line':n.lineno,'kind':'attribute','matches':good})
    if not good:errors.append((stem,row,anno(n.annotation)))
   elif '=' in row:
    name,val=map(str.strip,row.split('=',1));n=constants[name];good=ast.dump(ast.parse(val,mode='eval').body)==ast.dump(n.value)
    checks.append({'figure':stem,'member':name,'source':path,'line':n.lineno,'kind':'constant','matches':good})
    if not good:errors.append((stem,row,'constant mismatch'))
paths=[root/'feedback-20261026/slides/W3.html',root/'feedback-20261026/report-notes/W3.md',*u.glob('W3-*.puml')]
if (root/'feedback-20261026/review/W3-review.md').exists(): paths.append(root/'feedback-20261026/review/W3-review.md')
links=sorted(set(re.findall(r'https://github.com/Collaboration95/dc2/blob/76282d3/([^\s<>\"\)]+)', '\n'.join(p.read_text() for p in paths))))
linkchecks=[];used=set()
for item in links:
 path,anchor=item.split('#L');n=int(anchor.split('-L')[0]);p=Path(path);lines=p.read_text().splitlines();line=lines[n-1] if 0<n<=len(lines) else ''
 good=bool(line.strip());used.add(path);linkchecks.append({'target':item,'line_text':line.strip(),'nonempty_target':good})
 if not good:errors.append(('permalink',item,'blank or nonexistent'))
sourcechecks=[]
for path in sorted(used):
 pinned=subprocess.check_output(['git','show','76282d3:'+path]);same=pinned==Path(path).read_bytes();sourcechecks.append({'path':path,'sha256':hashlib.sha256(pinned).hexdigest(),'matches_pinned':same})
 if not same:errors.append(('source changed',path))
protected=json.loads((qa/'protected-hashes.json').read_text());boundary=[p for p,h in protected.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
deck_path=str(root/'site/deck.html')
code_boundary=[p for p in boundary if p!=deck_path]
if code_boundary:errors.append(('protected code files changed',code_boundary))
slides=html.fromstring('<main>'+paths[0].read_text()+'</main>').xpath('//section'); ids=[s.get('id') for s in slides];main=[s for s in slides if s.get('data-kind')=='main'];man=[]
if len(ids)!=len(set(ids)):errors.append('duplicate slide IDs')
if not 7<=len(main)<=8:errors.append('main slide count')
for s in slides:
 comment=s.getprevious();placement=comment.text.strip() if isinstance(comment,etree._Comment) else None
 if s.get('data-kind')=='back' and s.get('id') not in ('s61','s67') and placement!='NEW backup':errors.append(('backup placement',s.get('id'),placement))
 man.append({'id':s.get('id'),'kind':s.get('data-kind'),'placement':placement,'figures':[i.get('src').split('/')[-1] for i in s.xpath('.//img')]})
metrics=[]
for p in sorted(u.glob('W3-*.svg')):
 x=etree.parse(str(p)).getroot();w,h=map(float,x.get('viewBox').split()[2:]);sc=min(1,1180/w,535/h);fonts=[float(e.get('font-size')) for e in x.iter() if e.get('font-size')]
 metrics.append({'figure':p.stem,'width':w,'height':h,'scale':sc,'minimum_font_px':round(min(fonts)*sc,2),'main':any(p.name in r['figures'] and r['kind']=='main' for r in man)})
 if 'Syntax Error' in ''.join(x.itertext()):errors.append(('PlantUML error',p.name))
for r in metrics:
 if r['main'] and r['minimum_font_px']<13:errors.append(('main text below 13px',r))
def render(r):
 p=u/(r['figure']+'.svg')
 for opts,suffix in (([],''),(['--fit-zoom',str(r['scale'])],'-fit')):
  result=subprocess.run(['npx','-y','@resvg/resvg-js-cli@2.6.2-beta.1',*opts,'--background','white',str(p),str(png/(p.stem+suffix+'.png'))],capture_output=True,text=True)
  if result.returncode:raise RuntimeError(result.stderr)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(render,metrics))
css=re.search(r'<style>(.*?)</style>',(root/'site/deck.html').read_text(),re.S).group(1)
css=css.replace('html,body{margin:0;height:100%;','html,body{margin:0;')
mainpages=[]
for i,s in enumerate(main,1):
 s.set('class','slide active')
 for im in s.xpath('.//img'):
  im.set('src',str((root/'site'/im.get('src')).resolve())); im.set('data-minfont',str(min(float(e.get('font-size')) for e in etree.parse(im.get('src')).getroot().iter() if e.get('font-size'))))
 content=etree.tostring(s,method='html',encoding='unicode');doc='<!DOCTYPE html><html><head><meta charset="utf-8"><style>'+css+'html,body{height:auto;overflow:visible;background:white}#stage{position:relative;width:1280px;height:720px}</style></head><body><div id="stage">'+content+'</div><script>window.addEventListener("load",()=>{const i=document.querySelector("img");const b=i.getBoundingClientRect(),body=document.querySelector(".body").getBoundingClientRect();console.log(JSON.stringify({id:document.querySelector("section").id,image:[b.x,b.y,b.width,b.height],minFont:Math.min(b.width/i.naturalWidth,b.height/i.naturalHeight)*Number(i.dataset.minfont),inBody:b.top>=body.top-1&&b.bottom<=body.bottom+1,inStage:b.left>=0&&b.right<=1280&&b.bottom<=682}));});</script></body></html>'
 f=qa/('main-'+str(i).zfill(2)+'.html');f.write_text(doc);mainpages.append(str(f.resolve()))
(qa/'class-signature-audit.json').write_text(json.dumps(checks,indent=2));(qa/'permalink-audit.json').write_text(json.dumps(linkchecks,indent=2));(qa/'source-audit.json').write_text(json.dumps(sourcechecks,indent=2));(qa/'slides-manifest.json').write_text(json.dumps(man,indent=2));(qa/'render-metrics.json').write_text(json.dumps(metrics,indent=2))
result={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'class_members_checked':len(checks),'permalinks_checked':len(links),'source_files_checked':len(sourcechecks),'protected_files_checked':len(protected),'protected_changes':boundary,'protected_code_changes':code_boundary,'shared_deck_changed_outside_review_writes':deck_path in boundary,'sources':len(list(u.glob('W3-*.puml'))),'svgs':len(metrics),'main_sections':len(main),'backup_sections':len(slides)-len(main),'main_minimum_font_px':min(r['minimum_font_px'] for r in metrics if r['main']),'all_figures_minimum_font_px':min(r['minimum_font_px'] for r in metrics),'errors':errors,'main_pages':mainpages}
(qa/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if errors:raise SystemExit(1)
