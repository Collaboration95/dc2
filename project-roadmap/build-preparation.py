"""Build preparation reading pages. No application or infrastructure execution."""
from pathlib import Path
from html import escape
from urllib.parse import quote
import json
import re

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
MODULES = [('security', '06', '06-security-recovery', 'Security & recovery', 0),
           ('deployment', '07', '07-deployment', 'Deployment & release', 3),
           ('readiness', '08', '08-build-readiness', 'Build readiness', 2)]

def fmt(value):
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', escape(str(value)))

def read(folder, name, default=None):
    path = ROOT / 'design' / folder / name
    if not path.exists():
        if default is not None: return default
        raise ValueError(f'Missing authored input: {path.relative_to(ROOT)}')
    return json.loads(path.read_text())

def source_links(sources):
    items = []
    for s in sources:
        path = s.get('path', '')
        url = s.get('url')
        if path:
            # Extracted review text is temporary; link its unchanged original.
            if path.endswith('Team17-Proposal.txt'):
                path = 'project-documentation/Team17-Proposal.docx'
            target = BASE / path
            if target.exists() and not Path(path).is_absolute():
                url = '../' + quote(path, safe='/')
        label = s.get('locator') or path or url or 'Source'
        link = '<a href="'+escape(url, quote=True)+'">'+fmt(label)+'</a>' if url else fmt(label)
        items.append('<li>'+link+' <span class="source-note">'+fmt(s.get('note',''))+'</span></li>')
    return '<ul class="source-list">'+''.join(items)+'</ul>'

def table(data):
    return '<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable planning table"><table><thead><tr>'+''.join('<th scope="col">'+fmt(x)+'</th>' for x in data['headers'])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+fmt(x)+'</td>' for x in row)+'</tr>' for row in data['rows'])+'</tbody></table></div>'

def lines(values):
    return '<ul>'+''.join('<li>'+fmt(x)+'</li>' for x in values)+'</ul>' if values else '<p class="source-note">Not separately specified in the source.</p>'

def comparison(choice, sources=(), legacy=False):
    cid = choice['id']
    recorded = choice['status'] == 'proposal-fixed'
    status = 'Proposal decision already recorded' if recorded else 'Recommended planning default · team confirmation pending'
    body = '<p class="choice-status">'+status+'</p><p>'+fmt(choice['why'])+'</p><div class="option-grid">'
    for opt in choice['options']:
        selected = opt['id'] == choice['recommended']
        body += '<section class="option-card'+(' recommended-option' if selected else '')+'"><p class="option-tag">'+('Recorded proposal option' if recorded and selected else 'Recommended option' if selected else 'Alternative')+'</p><h3>'+fmt(opt['label'])+'</h3><h4>Advantages</h4>'+lines(opt.get('advantages',[]))+'<h4>Disadvantages</h4>'+lines(opt.get('disadvantages',[]))+'<h4>Best when</h4><p>'+fmt(opt.get('best_when','Not separately specified in the source.'))+'</p><h4>Impact</h4><p>'+fmt(opt.get('impact','Not separately specified in the source.'))+'</p></section>'
    body += '</div><p class="confirmation-note">'+fmt(choice.get('confirmation','Team confirmation is pending.'))+'</p><p class="source-note">Viewing this comparison records no choice, approval or completed check. Runtime validation: not run.</p>'
    if choice.get('sources'):
        body += '<p class="source-note">Source locators: '+fmt('; '.join(choice['sources']))+'</p>'
    body += source_links(sources)
    title = fmt(choice['title'])
    return '<dialog class="choice-dialog" id="compare-'+cid+'" aria-labelledby="title-'+cid+'"><div class="dialog-head"><h2 id="title-'+cid+'">'+title+'</h2><button type="button" data-close-choice aria-label="Close comparison: '+escape(choice['title'],quote=True)+'">Close</button></div>'+body+'</dialog><section class="print-comparison"><h2>'+title+'</h2>'+body+'</section>'

def choice_button(choice):
    return '<button type="button" class="compare-button" aria-haspopup="dialog" data-compare="compare-'+choice['id']+'">Compare options: '+fmt(choice['title'])+'</button>'

def build():
    panels, dialogs, ids = [], [], set()
    for key, num, folder, title, persona in MODULES:
        data = read(folder, 'content.json')
        for source in data.get('sources', []):
            if source.get('path', '').startswith('.'):
                source['path'] = str((ROOT/'design'/folder/source['path']).resolve().relative_to(BASE))
        choices = read(folder, 'choices.json')
        if not isinstance(choices, list): raise ValueError(f'{folder}/choices.json must be an array')
        lookup = {c['id']: c for c in choices}
        for c in choices:
            if not c['id'].startswith(num) or c['id'] in ids: raise ValueError('Duplicate or unprefixed choice ID: '+c['id'])
            ids.add(c['id'])
            if c['status'] not in ('recommended','proposal-fixed'): raise ValueError('Invalid choice status')
            if c['recommended'] not in [o['id'] for o in c['options']]: raise ValueError('Missing recommended option')
            dialogs.append(comparison(c, data.get('sources',[])))
        sections, toc = [], []
        for s in data['sections']:
            sid = s['id']
            if not sid.startswith(num) or sid in ids: raise ValueError('Duplicate or unprefixed section ID: '+sid)
            ids.add(sid)
            toc.append('<a href="#'+sid+'">'+fmt(s['title'])+'</a>')
            body = ''.join('<p>'+fmt(p)+'</p>' for p in s.get('paragraphs',[]))
            if s.get('bullets'): body += lines(s['bullets'])
            if s.get('table'): body += table(s['table'])
            for cid in s.get('choice_ids',[]):
                if cid not in lookup: raise ValueError('Unknown choice reference: '+cid)
                body += choice_button(lookup[cid])
            sections.append('<section class="prep-section" id="'+sid+'"><h2>'+fmt(s['title'])+'</h2>'+body+'</section>')
        manifest = read(folder, 'diagram-manifest.json', {'diagrams':[]})
        path = 'design/'+folder+'/'
        drawings = ''
        for d in manifest.get('diagrams',[]):
            if not d.get('svg'): continue
            for field in ('svg','source'):
                if d.get(field) and not (ROOT/path/d[field]).exists(): raise ValueError('Missing diagram file: '+path+d[field])
            drawings += '<figure class="prep-diagram"><h3>'+fmt(d['title'])+'</h3><a href="'+path+d['svg']+'"><img src="'+path+d['svg']+'" alt="'+escape(d['title'],quote=True)+'" loading="lazy"></a><figcaption>Planned design. <a href="'+path+d['svg']+'">Open editable SVG</a>'+(' · <a href="'+path+d['source']+'">Diagram source</a>' if d.get('source') else '')+'</figcaption></figure>'
        board = '<a href="'+escape(manifest['boardUrl'],quote=True)+'" target="_blank" rel="noopener">Open shared editable tldraw board</a><p class="source-note">Saved SVG previews do not update automatically after board edits.</p>' if manifest.get('boardUrl') else ''
        downloads = read(folder, 'downloads.json', [])
        download_html = ''
        for d in downloads:
            if not (ROOT/path/d['file']).exists(): raise ValueError('Missing download: '+path+d['file'])
            download_html += '<a class="download-card" href="'+path+quote(d['file'],safe='/')+'"><b>'+fmt(d['label'])+'</b><span>'+fmt(d['description'])+'</span></a>'
        for f,l in [('content.json','Authored content'),('choices.json','Planning comparisons')]:
            download_html += '<a class="download-card" href="'+path+f+'"><b>'+l+'</b><span>Structured documentation source.</span></a>'
        notes = {'security':'Maya’s retry must preserve ownership and use the stored source. Recovery and negative tests still need runtime evidence.', 'deployment':'Sam needs a separate Processing release and a fair CPU budget. AWS prerequisites are distinct from starting a local build.', 'readiness':'Jules can use the prepared contracts to start implementation. Team confirmation and measured results must be recorded separately.'}
        buddy = '<aside class="prep-buddy"><span class="prep-sprite persona-'+str(persona)+'" aria-hidden="true"></span><b>'+['Maya','Arun','Jules','Sam'][persona]+' · planning reminder</b><p>'+notes[key]+'</p></aside>'
        terminal = ('<section class="prep-section terminal-gate" id="08-terminal-gate"><p class="eyebrow">End of pre-build preparation</p><h2>Local build inputs ready; cloud prerequisites pending</h2><p>Local implementation can start in a later authorised task using documented defaults. Application implementation has not started. The build checklist remains for team review.</p><p>Before cloud execution, record verified account access, credentials, capacity, TLS, secret delivery and budget approval. Runtime results remain not run.</p><a href="#08-gates">Inspect the build gate</a> · <a href="design/08-build-readiness/first-build-work-order.txt">Open the first local work order</a></section>' if key == 'readiness' else '')
        panels.append('<section class="prep-panel" id="'+key+'"'+(' hidden' if key!='security' else '')+'><header class="module-head"><p class="eyebrow">Step '+num+' / Prepared documentation</p><h2>'+fmt(data['title'])+'</h2><p>Accepted proposal commitments remain fixed. Recommended defaults await team confirmation. All runtime results are not run.</p></header><div class="prep-layout"><nav class="prep-toc" aria-label="'+title+' contents">'+''.join(toc)+'<a href="#'+num+'-choices">Decision index</a><a href="#'+num+'-downloads">Downloads & sources</a></nav><div>'+buddy+(' <section class="prep-section"><h2>Design previews</h2>'+board+drawings+'</section>' if drawings or board else '')+''.join(sections)+'<section class="prep-section" id="'+num+'-choices"><h2>Decision index</h2><p>Open any comparison to inspect every option. These buttons do not approve the plan.</p><div class="decision-index">'+''.join(choice_button(c) for c in choices)+'</div></section><section class="prep-section" id="'+num+'-downloads"><h2>Downloads & sources</h2><div class="download-grid">'+download_html+'</div>'+source_links(data.get('sources',[]))+'</section>'+terminal+'</div></div></section>')
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Team 17 · Build preparation</title><link rel="stylesheet" href="style.css"><link rel="stylesheet" href="preparation.css"><script src="preparation.js" defer></script></head><body><a class="skip" href="#preparation">Skip to preparation</a><main class="preparation-page" id="preparation"><div class="prep-top"><a href="index.html#step-6">FlickPond / Team 17 / Roadmap</a><span>9 October 2026 · baseline 8854537</span><button type="button" data-print-preparation>Print preparation pack</button></div><p class="eyebrow">Steps 06—08 / Before application coding</p><h1>Prepare the next move.</h1><p class="lead">Security, recovery, release and evidence plans for the two-service platform. Compare the trade-offs, then carry the explicit build gate into implementation.</p><nav class="prep-tabs" aria-label="Preparation modules">'''+''.join('<a href="#'+k+'" data-prep-module="'+k+'"><b>'+n+' · '+t+'</b><span>'+sub+'</span></a>' for (k,n,f,t,p),sub in zip(MODULES,['Trust boundaries & failure behavior','AWS containers & independent releases','Protocols, report & local build gate']))+'</nav>'+''.join(panels)+'<footer class="prep-footer">Prepared for team review. No application or infrastructure execution. <a href="design-studio.html">Steps 03–05 design</a> · <a href="business-scope.html">Business & personas</a> · <a href="records/project-decisions.txt">Decision provenance</a></footer><div class="comparison-appendix"><h1 class="print-only">Planning comparison appendix</h1>'+''.join(dialogs)+'</div></main></body></html>'
    (ROOT/'build-preparation.html').write_text(html)
    print('Built build-preparation.html from all three authored modules')

if __name__ == '__main__': build()
