"""Build self-contained 1280x720 previews from the deck CSS and W5 fragments."""
from pathlib import Path
from lxml import html
import json,base64
ROOT=Path(__file__).resolve().parents[5]
BASE=ROOT/'project-documentation/presentation'
QA=Path(__file__).resolve().parent
s=(BASE/'site/deck.html').read_text(); css=s[s.index('<style>')+7:s.index('</style>')]
slides=html.fragments_fromstring((BASE/'feedback-20261026/slides/W5.html').read_text())
items=[]
for sec in slides:
    if not isinstance(sec.tag,str) or sec.tag!='section':continue
    sec.set('class','slide active')
    for img in sec.xpath('.//img'):
        p=BASE/'site'/img.get('src');img.set('src','data:image/svg+xml;base64,'+base64.b64encode(p.read_bytes()).decode())
    script='''<script>window.addEventListener('load',()=>{console.log(JSON.stringify({id:document.querySelector('.slide').id,viewport:[innerWidth,innerHeight],stage:[document.getElementById("stage").offsetWidth,document.getElementById("stage").offsetHeight],overflow:[...document.querySelectorAll('.body>*')].filter(e=>{let r=e.getBoundingClientRect(),b=document.querySelector('.body').getBoundingClientRect();return r.top<b.top-1||r.bottom>b.bottom+1||r.left<49||r.right>1231}).map(e=>e.tagName),images:[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth>0,w:i.width,h:i.height}))}));});</script>'''
    data='<!doctype html><html lang="en"><head><meta charset="utf-8"><style>'+css+'html,body{height:auto;overflow:visible}#stage{position:relative;height:720px}</style></head><body><div id="stage">'+html.tostring(sec,encoding='unicode')+'</div>'+script+'</body></html>'
    file=QA/('W5-'+sec.get('id')+'.html');file.write_text(data)
    items.append({'id':sec.get('id'),'path':str(file)})
(QA/'manifest.json').write_text(json.dumps(items,indent=2)+'\n')
print(json.dumps(items))
