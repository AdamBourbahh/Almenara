const fs=require('fs');
const {mathjax}=require('mathjax-full/js/mathjax.js');
const {TeX}=require('mathjax-full/js/input/tex.js');
const {SVG}=require('mathjax-full/js/output/svg.js');
const {liteAdaptor}=require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler}=require('mathjax-full/js/handlers/html.js');
const {AllPackages}=require('mathjax-full/js/input/tex/AllPackages.js');
const adaptor=liteAdaptor(); RegisterHTMLHandler(adaptor);
const doc=mathjax.document('',{InputJax:new TeX({packages:AllPackages}),OutputJax:new SVG({fontCache:'local'})});
const [,,inFile,outFile,color,emPx]=process.argv;
const F=JSON.parse(fs.readFileSync(inFile,'utf8')); const out={};
for(const [k,tex] of Object.entries(F)){
  const node=doc.convert(tex,{display:true});
  let svg=adaptor.innerHTML(node);
  if(/<text|merror|data-mjx-error/.test(svg)) throw new Error('render problem in '+k+': '+svg.slice(0,300));
  const vb=svg.match(/viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"/).slice(1).map(Number);
  const inner=svg.replace(/^<svg[^>]*>/,'').replace(/<\/svg>$/,'')
    .replace(/ data-[a-z-]+="[^"]*"/g,'').replace(/currentColor/g,color).replace(/<title[^>]*>.*?<\/title>/g,'');
  const k2=Number(emPx)/1000, W=+(vb[2]*k2).toFixed(1), H=+(vb[3]*k2).toFixed(1);
  const s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-label="__ALT__"><g transform="scale(${k2}) translate(${-vb[0]},${-vb[1]})">${inner}</g></svg>`;
  out[k]={W,H,bytes:s.length,svg:s,tex};
}
fs.writeFileSync(outFile,JSON.stringify(out));
for(const [k,v] of Object.entries(out)) console.log(k.padEnd(14),String(v.W).padStart(7),String(v.H).padStart(6),v.bytes);
