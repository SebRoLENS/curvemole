// Read the citation bundled with this deployment, never a newer main revision.
(()=>{
 const text=document.getElementById('citationText'),link=document.getElementById('citationDoi'),status=document.getElementById('citationStatus');
 const conceptText=document.getElementById('citationConceptText'),conceptLink=document.getElementById('citationConceptDoi'); // 10.5281/zenodo.22113854
 let citation=text.textContent;
 async function refreshCitation(){
  try{
   const response=await fetch('CITATION.cff',{cache:'no-cache',signal:AbortSignal.timeout(8000)});
   if(!response.ok)return;
   const cff=await response.text();
   const field=name=>{const match=cff.match(new RegExp('^'+name+':\\s*(.+)$','m'));return match?match[1].trim().replace(/^["']|["']$/g,''):''};
   const doi=field('doi'),version=field('version'),date=field('date-released'),title=field('title');
   if(!/^10\.\d{4,9}\/[-._;()/:a-zA-Z0-9]+$/.test(doi)||!version||!/^\d{4}-\d{2}-\d{2}$/.test(date)||!title)return;
   citation=`Romi, S. (${date.slice(0,4)}). ${title} (v${version}) [Software]. Zenodo.`;
   text.textContent=citation;link.href='https://doi.org/'+doi;link.textContent='doi:'+doi+' ↗';
  }catch{/* Retain the verified bundled citation if offline. */}
 }
 document.getElementById('copyCitation').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(citation+' '+link.href+'\n'+conceptText.textContent+' '+conceptLink.href);status.textContent='Citations copied.'}catch{status.textContent='Select the citation text to copy it.'}});
 refreshCitation();document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshCitation()});
})();
