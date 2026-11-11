"""Render the reviewed W5 activity figures directly, then create PNG previews.
Run from the dc2-rescue root: python3 .../slides/W5-qa/render_figures.py
Each source is a complete activity view; no compositing or manual SVG edits.
"""
from pathlib import Path
from lxml import etree as E
import subprocess
ROOT = Path(__file__).resolve().parents[5]
ASSETS = ROOT / 'project-documentation/presentation/site/assets/uml'
QA = Path(__file__).resolve().parent
NS = 'http://www.w3.org/2000/svg'
for tier in ('main', 'full', 'release'):
    name = 'W5-pipeline-' + tier
    subprocess.run(['java','-Djava.awt.headless=true','-jar',str(Path.home()/'dc2-tools/plantuml-1.2026.9.jar'),'-tsvg',str(ASSETS/(name+'.puml'))],check=True)
    subprocess.run(['npx','-y','@resvg/resvg-js-cli@2.6.2-beta.1','--background','white','--fit-width','1180',str(ASSETS/(name+'.svg')),str(QA/(name+'.png'))],check=True)
    print(name)
