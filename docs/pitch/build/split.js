const fs=require('fs');const F=JSON.parse(fs.readFileSync('formulas.json','utf8'));const O={};
const cut=(k,sep,keepSepOnSecond)=>{const s=F[k];const i=s.indexOf(sep);if(i<0)throw k;
  const a=s.slice(0,i).trim(), b=(keepSepOnSecond?sep:'')+s.slice(i+sep.length);
  O[k+'_a']=a.replace(/,$/,',');O[k+'_b']=(keepSepOnSecond?b:b.trim()).trim();};
for(const k of Object.keys(F)){
  if(k==='s1_fre') cut(k,'\\approx',true);
  else if(k==='s4_joseph') cut(k,'\\quad',false);
  else if(k==='s4_guard') cut(k,'\\qquad',false);
  else if(k==='o_emis') cut(k,'\\quad',false);
  else O[k]=F[k];
}
fs.writeFileSync('formulas_split.json',JSON.stringify(O,null,1));
for(const k of ['s1_fre_a','s1_fre_b','s4_joseph_a','s4_joseph_b','s4_guard_a','s4_guard_b','o_emis_a','o_emis_b'])console.log(k,'|',O[k]);
