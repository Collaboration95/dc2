(async () => {
  await document.fonts.ready;
  const slides = [...document.querySelectorAll('#stage > section.slide')];
  await Promise.all([...document.images].map(i => i.decode().catch(() => {})));
  const svgs = {};
  const results = [];
  const box = r => ({x:r.x, y:r.y, w:r.width, h:r.height});
  for (let i = 0; i < slides.length; i++) {
    const slide = slides[i];
    slide.classList.add('active');
    const r = slide.getBoundingClientRect(), scale = r.width / 1280;
    const relative = e => {
      const b = e.getBoundingClientRect();
      return {x:(b.x-r.x)/scale, y:(b.y-r.y)/scale, w:b.width/scale, h:b.height/scale};
    };
    const clips = [], outside = [], small = [], images = [], htmlFonts = [], inlineFonts = [];
    const body = relative(slide.querySelector('.body'));
    for (const e of slide.querySelectorAll('*')) {
      if (e.closest('aside') || getComputedStyle(e).display === 'none') continue;
      const b = relative(e), cs = getComputedStyle(e);
      if (!b.w || !b.h) continue;
      if ((cs.overflow === 'hidden' || cs.overflowY === 'hidden') &&
          (e.scrollHeight > e.clientHeight + 2 || e.scrollWidth > e.clientWidth + 2)) {
        clips.push({tag:e.tagName, class:String(e.className), text:e.textContent.slice(0,80),
          client:[e.clientWidth,e.clientHeight], scroll:[e.scrollWidth,e.scrollHeight]});
      }
      const hasText = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (hasText && !e.closest('svg')) {
        const size = parseFloat(cs.fontSize);
        htmlFonts.push(size);
        if (size < 13) small.push({text:e.textContent.slice(0,80),size});
      }
      if ((e.tagName === 'IMG' || hasText) && !e.closest('svg,.foot,.sec')) {
        if (b.x < 45 || b.x+b.w > 1235 || b.y+b.h > 682) {
          outside.push({tag:e.tagName,text:e.textContent.slice(0,60),...b});
        }
      }
    }
    for (const e of slide.querySelectorAll('svg text')) {
      if (!e.textContent.trim()) continue;
      const c = e.getScreenCTM();
      const size = parseFloat(getComputedStyle(e).fontSize) * Math.hypot(c.a,c.b) / scale;
      inlineFonts.push(size);
      if (size < 13) small.push({text:e.textContent.slice(0,80),size});
    }
    for (const image of slide.querySelectorAll('img')) {
      const b = relative(image);
      let minText = null;
      if (image.src.endsWith('.svg')) {
        const doc = svgs[image.src] ||= new DOMParser().parseFromString(
          await (await fetch(image.src)).text(), 'image/svg+xml');
        const root = doc.documentElement;
        const vb = root.getAttribute('viewBox')?.split(/[ ,]+/).map(Number);
        const width = vb?.[2] || parseFloat(root.getAttribute('width'));
        const height = vb?.[3] || parseFloat(root.getAttribute('height'));
        const factor = Math.min(b.w/width,b.h/height);
        const fonts = [...doc.querySelectorAll('text')].filter(e=>e.textContent.trim()).map(e=>({
          text:e.textContent.slice(0,80),
          size:parseFloat(e.getAttribute('font-size') || e.style.fontSize || 16)*factor
        }));
        if (fonts.length) minText = fonts.reduce((a,b)=>a.size<b.size?a:b);
      }
      images.push({src:image.getAttribute('src'),ok:image.complete&&image.naturalWidth>0,...b,minText});
    }
    results.push({n:i+1,id:slide.id,kind:slide.dataset.kind,sec:slide.querySelector('.sec')?.textContent||'',
      footer:slide.querySelector('.foot')?.innerText,body,clips,outside,small,
      htmlMin:htmlFonts.length?Math.min(...htmlFonts):null,
      inlineMin:inlineFonts.length?Math.min(...inlineFonts):null,images});
    slide.classList.remove('active');
  }
  slides[0].classList.add('active');
  window.deckQA = results;
  return {count:results.length,viewport:{width:innerWidth,height:innerHeight},
    bad:results.filter(s=>s.clips.length||s.outside.length||s.small.length||s.images.some(i=>
      !i.ok||(s.kind==='main'&&i.minText&&i.minText.size<13))).map(s=>({n:s.n,id:s.id,
        clips:s.clips,outside:s.outside,small:s.small,images:s.images.filter(i=>!i.ok||(i.minText&&i.minText.size<13))})),
    imageCount:results.reduce((n,s)=>n+s.images.length,0),
    mainFigureMin:Math.min(...results.filter(s=>s.kind==='main').flatMap(s=>s.images.map(i=>i.minText?.size??Infinity)))};
})()
