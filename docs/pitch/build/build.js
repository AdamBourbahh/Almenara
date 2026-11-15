const fs=require('fs');
const R=JSON.parse(fs.readFileSync('rendered.json','utf8'));
let t=fs.readFileSync('matematica.tpl.html','utf8'); const used=new Set();
// label preceding each placeholder becomes the alt text
t=t.replace(/<p class="fl">([^<]*)<\/p>((?:\{\{\+?[a-z0-9_]+\}\})+)/gi,(m,label,phs)=>{
  const out=phs.replace(/\{\{(\+?)([a-z0-9_]+)\}\}/gi,(m2,plus,k)=>{
    if(!R[k]) throw new Error('missing '+k); used.add(k);
    return R[k].svg.replace('<svg ',`<svg class="${plus?'fx2':'fx'}" `).replace('__ALT__','Fórmula: '+label);
  });
  return `<p class="fl">${label}</p>`+out;
});
if(/\{\{/.test(t)) throw new Error('unfilled placeholder');
const unused=Object.keys(R).filter(k=>!used.has(k)); if(unused.length) throw new Error('unused '+unused);
fs.mkdirSync('../deck/project/slides',{recursive:true});
fs.writeFileSync('../deck/project/slides/matematica.html',t);
console.log('bytes',t.length,'svgs',(t.match(/<svg /g)||[]).length,'elements~',(t.match(/<(div|p|h2|h3|svg|x-shape|span|section)\b/g)||[]).length);
