(()=>{
const panels=[...document.querySelectorAll('.studio-panel')];
function route(){
 const hash=location.hash.slice(1)||'ddd';const target=document.getElementById(hash);
 const panel=target?.classList.contains('studio-panel')?target:target?.closest('.studio-panel')||panels[0];
 panels.forEach(p=>p.hidden=p!==panel);
 document.querySelectorAll('[data-module]').forEach(a=>a.toggleAttribute('aria-current',false));
 document.querySelector(`[data-module="${panel.id}"]`)?.setAttribute('aria-current','page');
 if(target && target!==panel)requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
 else window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);route();
document.getElementById('print-design').addEventListener('click',()=>window.print());
const prior=new Map();window.addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>{prior.set(d,d.open);d.open=true}));
window.addEventListener('afterprint',()=>{prior.forEach((v,d)=>d.open=v);prior.clear()});
})();
