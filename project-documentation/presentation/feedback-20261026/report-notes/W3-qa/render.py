from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,base64,json,sys
from lxml import etree
qa=Path(__file__).parent
assets=Path('project-documentation/presentation/site/assets/uml')
def run(p):
 root=etree.parse(str(p)).getroot(); w=float(root.get('width').removesuffix('px'));h=float(root.get('height').removesuffix('px'))
 scale=min(1180/w,550/h,1)
 png=qa/(p.stem+'.png'); fit=qa/(p.stem+'-fit.svg'); final=qa/(p.stem+'-fit.png')
 cmd=['npx','-y','@resvg/resvg-js-cli@2.6.2-beta.1','--background','white','--fit-width',str(round(w*scale)),str(p),str(png)]
 r=subprocess.run(cmd,capture_output=True,text=True,check=True)
 data=base64.b64encode(png.read_bytes()).decode();fw=round(w*scale);fh=round(h*scale)
 fit.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="white"/><image href="data:image/png;base64,{data}" x="{(1280-fw)//2}" y="{100+(550-fh)//2}" width="{fw}" height="{fh}"/></svg>')
 subprocess.run(['npx','-y','@resvg/resvg-js-cli@2.6.2-beta.1',str(fit),str(final)],capture_output=True,text=True,check=True)
 return {'file':p.name,'width':w,'height':h,'fit_scale':round(scale,3),'body_px':round(15*scale,1)}
selected=[assets/x for x in sys.argv[1:]] if len(sys.argv)>1 else sorted(assets.glob('W3-*.svg'))
results=list(ThreadPoolExecutor(5).map(run,selected))
if len(sys.argv)>1 and (qa/'raster-check.json').exists():
 old=json.loads((qa/'raster-check.json').read_text()); merge={x['file']:x for x in old}; merge.update({x['file']:x for x in results}); results=sorted(merge.values(),key=lambda x:x['file'])
(qa/'raster-check.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results))
