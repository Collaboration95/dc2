"""Build the local design reading pages from the authored design records."""
from pathlib import Path
from html import escape
import re,json,runpy
prep = runpy.run_path(str(Path(__file__).parent / "build-preparation.py"))
adr_records = json.loads((Path(__file__).parent / "design/04-architecture/architecture-decisions.json").read_text())["records"]
earlier_choices = []
for adr in adr_records:
    options = [{"id": adr["id"] + "-recorded", "label": adr["title"], "advantages": adr["positive_consequences"], "disadvantages": adr["negative_consequences"], "best_when": adr["context"], "impact": adr["decision"]}]
    for index, alternative in enumerate(adr["alternatives"], 1):
        label, _, explanation = alternative.partition(":")
        explanation = explanation.strip() or alternative
        parts = re.split(r",? but ", explanation, maxsplit=1)
        options.append({"id": adr["id"] + "-alternative-" + str(index), "label": label, "advantages": [parts[0]] if len(parts) == 2 else [], "disadvantages": [parts[1]] if len(parts) == 2 else [], "best_when": "Not separately specified in the ADR; evaluate against the recorded context.", "impact": alternative})
    earlier_choices.append({"id": adr["id"], "title": adr["title"], "status": "proposal-fixed", "recommended": adr["id"] + "-recorded", "why": adr["context"], "options": options, "confirmation": "Proposal decision already recorded. Detailed design remains for team review; validation is not run. Comparing alternatives does not reopen or approve this decision.", "sources": adr["sources"]})
(Path(__file__).parent / "earlier-choices.json").write_text(json.dumps(earlier_choices, indent=2) + "\n")
O=Path(__file__).parent
BASE=O.parent
# tldraw exports can inherit hidden text and dark-theme outlines from its editor.
# Keep the SVG text and geometry intact while making snapshots portable.
for svg_file in (O/'design').rglob('*.svg'):
    svg=svg_file.read_text()
    svg=re.sub(r'(?<!-)visibility:\s*hidden\s*;', 'visibility: visible;', svg)
    svg=re.sub(r'text-shadow:[^;]*;', 'text-shadow: none;', svg)
    svg_file.write_text(svg)
modules=[('ddd','03','03-ddd','Domain-driven design','Boundaries that follow the work.','Separate ownership and consistency rules justify the two-service design. Worker replication alone does not.','Maya’s source remains the same when an encode fails. A retry changes the attempt, not ownership.',0),('architecture','04','04-architecture','Logical architecture','Two services. Clear responsibilities.','Media Management is the public entry point. Processing owns the asynchronous lifecycle and its independently released code.','Sam can release Processing independently only when its data, migrations and compatibility rules allow it.',3),('contracts','05','05-contracts','Contracts and persistence','Agree on the handover.','Keep the browser routes stable. Make identifiers, replay rules, ownership and durable state explicit before coding.','Jules should need the published contract and a session cookie. Service internals and database credentials stay private.',2)]
def table(head,rows):return '<div class="table-wrap"><table><thead><tr>'+''.join('<th scope="col">'+fmt(s)+'</th>' for s in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+fmt(str(s))+'</td>' for s in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def fmt(s):
 s=escape(s)
 s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
 # Preserve exact source locators, but keep dense citations visually secondary.
 s=re.sub(r'\[([^\[\]]*(?:P2 |F01|Team17|project-roadmap/|project-documentation/|Media_player/|AD-0|C0[1-9]|BS;|U04)[^\[\]]*)\]',r'<span class="reference-note">Source: \1</span>',s)
 return s

def content(s):
 out=''.join('<p>'+fmt(p)+'</p>' for p in s.get('paragraphs',[]))
 if s.get('bullets'):out+='<ul>'+''.join('<li>'+fmt(x)+'</li>' for x in s['bullets'])+'</ul>'
 if s.get('table'):out+=table(s['table']['headers'],s['table']['rows'])
 return out

def buddy(text,i):return '<aside class="buddy-note '+('paper' if i==2 else 'operator' if i==3 else '')+'"><span class="buddy-sprite buddy-'+str(i)+'" aria-hidden="true"></span><span class="speaker">'+['Maya','Arun','Jules','Sam'][i]+' · design reminder</span><p>'+escape(text)+'</p></aside>'
def artifact(path,label,desc):return '<a class="artifact-link" href="'+path+'"><b>'+label+'</b><span>'+desc+'</span></a>'
panels=[]
for key,num,folder,title,tagline,answer,quote,person in modules:
 d=json.loads((O/'design'/folder/'content.json').read_text())
 m=json.loads((O/'design'/folder/'diagram-manifest.json').read_text())
 path='design/'+folder+'/'
 intro='<div class="studio-intro"><div><p class="eyebrow">Step '+num+' / '+title+'</p><h2>'+tagline+'</h2><p class="reading-intro">Prepared design, ready for team review. Runtime checks and application implementation remain ahead.</p></div><aside class="board-card"><strong>Edit the diagrams</strong><a href="'+m['boardUrl']+'" target="_blank" rel="noopener">Open this tldraw board</a><p>Native editable shapes. The live board is shared for editing through its link.</p></aside></div><div class="first-answer"><p>'+answer+'</p></div>'
 diagrams='<div class="diagram-strip">'
 for i,x in enumerate(m['diagrams']):
  svg=x.get('svg');source=x.get('source');did=x.get('id',x.get('key','diagram-'+str(i)));dt=x.get('title',did.replace('-',' ').title())
  if not svg or not (O/'design'/folder/svg).exists():continue
  board=x.get('pageUrl') or m['boardUrl']
  diagrams+='<section class="diagram-card" id="'+key+'-diagram-'+did+'"><h3>'+escape(dt)+'</h3><figure><img src="'+path+svg+'" alt="'+escape(dt)+'. Editable design diagram. The adjoining text defines its rules." loading="lazy"><figcaption>Design view for step '+num+'. The SVG is a saved snapshot; changes on the live board do not automatically update this page.</figcaption></figure><div class="diagram-tools"><a href="'+board+'" target="_blank" rel="noopener">Edit in tldraw</a><a href="'+path+svg+'" target="_blank" rel="noopener">Open full-size SVG</a>'+(('<a href="'+path+source+'">Diagram source</a>') if source else '')+'</div></section>'
 diagrams+='</div>'
 index='<nav class="section-index" aria-label="'+title+' contents"><a href="#'+key+'-drawings">Diagrams</a>'
 sec=''
 for i,s in enumerate(d['sections']):
  sid=key+'-'+s['id'];index+='<a href="#'+sid+'">'+escape(s['title'].replace('Step 04: ',''))+'</a>'
  if s['id'].startswith('AD-'):
   sec+='<details class="adr-detail" id="'+sid+'"><summary>'+escape(s['title'])+'</summary><div class="adr-body">'+content(s)+prep['choice_button'](next(c for c in earlier_choices if c['id'] == s['id']))+'</div></details>'
  else:sec+='<section class="design-section" id="'+sid+'"><h2>'+escape(s['title'])+'</h2>'+content(s)+'</section>'
  if i==4:sec+=buddy(quote,person)
 index+='</nav>'
 extra=''
 if key=='contracts':
  files=[('public.openapi.json','Public OpenAPI','Web and CLI routes, sessions, errors and compatibility.'),('processing.openapi.json','Processing OpenAPI','Submit, query, retry and delete, with owner-scoped calls.'),('media-internal.openapi.json','Source-access OpenAPI','Reverse capability grant with a separate service token.'),('persistence-model.json','Persistence register','Owned tables, transactions and retention choices.'),('contract-cases.json','25 contract cases','Expected results. All remain marked not run.'),('examples.json','Request and response examples','Illustrative IDs and URLs. No live credentials.')]
  extra='<section class="design-section" id="contracts-downloads"><h2>Use these as implementation inputs</h2><p>OpenAPI 3.1 design documents. They describe intended behavior and contain no running service.</p><div class="artifact-grid">'+''.join(artifact(path+f,t,desc) for f,t,desc in files)+'</div><p class="studio-help">Version the contracts with the implementation. Validate real handlers and wire the planned cases into CI later.</p></section>'
  cases=json.loads((O/'design'/folder/'contract-cases.json').read_text())
  extra+='<section class="design-section" id="contracts-case-register"><h2>Contract case register</h2>'+table(['Case','Input','Expected result'],[[c['id']+' · '+c['case'],c['input'],c['expected']+' [not run]'] for c in cases])+'</section>'
 if key=='architecture':extra='<section class="design-section"><h2>Decision records</h2><div class="artifact-grid">'+''.join(artifact(path+'AD-'+str(i).zfill(2)+'.md','AD-'+str(i).zfill(2),'Editable architecture decision record.') for i in range(1,9))+'</div></section>'
 # Link original and implementation sources with verified filesystem targets.
 src=[('project-documentation/Team17-Proposal.docx','Proposal · §§2–3'),('project-documentation/original-reference/02 Project Report Template for Practice Project.docx','Report template · §3'),('project-roadmap/records/project-decisions.txt','Lecturer feedback and baseline'),('project-roadmap/business-scope.json','Personas and use cases'),('Media_player/app/models/job.py','Inherited job model'),('Media_player/app/api/jobs.py','Inherited routes'),('Media_player/app/api/auth.py','Cookie sessions'),('Media_player/app/api/hls.py','HLS behavior'),('Media_player/app/worker/tasks.py','Worker claims'),('Media_player/app/worker/reaper.py','Recovery task'),('Media_player/docker-compose.yml','Current deployment')]
 if d.get('sources'):
  for ss in d['sources']:
   if ss.get('path') and (BASE/ss['path']).exists() and ss['path'] not in [p for p,_ in src]:src.append((ss['path'],ss['id']+' · '+ss.get('locator','')))
 from urllib.parse import quote as urlquote
 sourceLinks='<section class="design-section" id="'+key+'-originals"><h2>Open the source files</h2><p>Source locators in this module refer to the following unchanged originals and inspected code.</p><ul>'+''.join('<li><a href="../'+urlquote(p,safe='/')+'" target="_blank" rel="noopener">'+escape(label)+'</a><br><span class="source-code">'+escape(p)+'</span></li>' for p,label in src)+'</ul>'
 if key=='contracts':sourceLinks+='<p>Format reference: <a href="https://spec.openapis.org/oas/v3.1.0.html">OpenAPI 3.1.0</a>. Privilege reference: <a href="https://www.postgresql.org/docs/16/ddl-priv.html">PostgreSQL 16 privileges</a>.</p>'
 sourceLinks+='</section>'
 panels.append('<section class="studio-panel" id="'+key+'"'+(' hidden' if key!='ddd' else '')+'>'+intro+'<div class="module-layout">'+index+'<div><div id="'+key+'-drawings">'+diagrams+'</div>'+sec+extra+sourceLinks+'</div></div></section>')
html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="FlickPond Team 17 domain model, logical architecture, decisions, API contracts and persistence design."><title>Team 17 · Design studio</title><link rel="stylesheet" href="style.css"><link rel="stylesheet" href="design-studio.css"><link rel="stylesheet" href="preparation.css"><script src="preparation.js" defer></script><script src="design-studio.js" defer></script></head><body><a class="skip" href="#ddd">Skip to design content</a><main class="design-page"><div class="studio-top"><a href="index.html#step-3">FlickPond / Team 17 / Roadmap</a><span>9 October 2026 · local baseline 8854537</span><button type="button" id="print-design" class="print-studio">Print design pack</button></div><p class="eyebrow">Steps 03—05 / Design before implementation</p><h1>Give every rule a home.</h1><p class="lead">From people and business rules to service boundaries, decisions and contracts. Maya, Arun, Jules and Sam keep the design tied to real tasks.</p><nav class="studio-tabs" aria-label="Design modules">'''+''.join('<a href="#'+k+'" data-module="'+k+'"><b>'+n+' · '+t+'</b><span>'+s+'</span></a>' for k,n,t,s in [('ddd','03','DDD','Models, invariants and suitability'),('architecture','04','Architecture','Components and AD-01–AD-08'),('contracts','05','Contracts','APIs, data and compatibility')])+'''</nav>'''+''.join(panels)+'''<footer class="studio-footer">Prepared design, not implemented behavior. Original course documents remain authoritative. <a href="business-scope.html">Business and personas</a> · <a href="assets/persona-poses-prompt.txt">Illustration prompt</a><p>tldraw snapshots accompany live editable boards. Sources and contracts remain local files. This work stops at step 05.</p></footer></main></body></html>'''
adr_sources = [{'path': 'project-roadmap/design/04-architecture/architecture-decisions.json', 'locator': 'AD-01–AD-08 · recorded decision and consequences', 'note': 'Alternatives retain source wording. Unspecified trade-offs are labelled.'}, {'path': 'project-documentation/Team17-Proposal.docx', 'locator': 'Proposal §2.4 · AD-01–AD-08', 'note': 'Original proposal unchanged.'}]
html = html.replace('</main>', '<div class="comparison-appendix"><h1 class="print-only">Recorded architecture comparison appendix</h1>'+''.join(prep['comparison'](c, adr_sources, legacy=True) for c in earlier_choices)+'</div></main>')
(O/'design-studio.html').write_text(html)
print('Built design-studio.html')
