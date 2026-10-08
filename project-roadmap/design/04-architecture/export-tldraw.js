// Execute through tldraw_exec on board 0GOUcscLFXmGeNDXAJTx5 after rendering.
// Returns exports and exact observed IDs; write returned SVG strings to local files.
const keys = [
  {key:'inherited-vs-proposed',name:'01 Inherited vs proposed — logical architecture'},
  {key:'success-sequence',name:'02 Success sequence — durable intake to owner playback'}
];
const pages = editor.getPages();
const result = [];
for (const d of keys) {
  const page = pages.find(p => p.name === d.name);
  if (!page) throw new Error('Missing rendered page: '+d.name);
  editor.setCurrentPage(page.id);
  const shapes = editor.getCurrentPageShapes();
  const output = await editor.getSvgString(shapes);
  result.push({key:d.key,pageId:page.id,rootShapeId:shapes.find(s=>s.type==='group')?.id || shapes[0]?.id || null,shapeIds:shapes.map(s=>s.id),output});
}
editor.setCurrentPage(result[0].pageId);
editor.zoomToFit();
return {boardId:'0GOUcscLFXmGeNDXAJTx5',diagrams:result};
