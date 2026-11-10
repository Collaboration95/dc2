"""Emit self-contained 1280x720 W4 slide HTML for visual review."""
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DECK=ROOT/'project-documentation/presentation/site/deck.html'
css=re.search(r'<style>(.*?)</style>',DECK.read_text(),re.S)[1]
sections=re.findall(r'<section.*?</section>',(Path(__file__).resolve().parent.parent/'slides/W4.html').read_text(),re.S)
def page(section):
 section=section.replace('class="slide"','class="slide active"').replace('src="assets/uml/','src="'+str(DECK.parent/'assets/uml')+'/')
 return '<!doctype html><html><head><meta charset="utf-8"><style>'+css+'html,body{height:720px;background:white}#stage{position:relative;transform:none}</style></head><body><div id="stage">'+section+'</div></body></html>'
if sys.argv[1]=='list':
 print(json.dumps([{'id':re.search(r'id="([^"]+)"',s)[1],'title':re.search(r'<h1>(.*?)</h1>',s)[1]} for s in sections]))
else:
 section=next(s for s in sections if 'id="'+sys.argv[1]+'"' in s)
 print(page(section))
