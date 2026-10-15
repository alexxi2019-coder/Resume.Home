'use strict';
let resumeDraft=null, resumeText='', duplicateDirty=false, resumeBusy=false;

function renderProvenance(vid) {
  const p=(S.provenance||[]).find(p=>p.version_id===vid);
  if(!p)return '';
  const batch=S.resume_imports.find(b=>b.id===p.import_id);
  return `<details class="import-provenance"><summary>Resume source · ${esc(batch.source_filename)}</summary><p class="tiny">Imported ${esc(date(batch.imported_at))}<br>${esc(p.source_location)}<br>Employment dates as written: ${esc(p.employment_dates||'Not supplied')}</p><strong class="tiny">Original extracted wording</strong><div class="source">${esc(p.original_text)}</div></details>`;
}

function importGroupHeading(g) {return (entryTypes().find(([k])=>k===(g.category||'experience'))?.[1]||'Work experience')+' · '+(g.category==='experience'?[g.employer||'Employer missing',g.role||'Role missing'].join(' · '):g.title||'Title missing');}

function renderResume() {
  if(resumeDraft)return renderResumePreview();
  $('#content').innerHTML=intro('Bring your experience with you.','Upload your current resume or paste its text. Review every bullet before it joins your library.')+
    `<div class="import-steps"><strong>1 · Add resume</strong><span>2 · Review & resolve duplicates</span><span>3 · Confirm import</span></div>
    <div class="callout"><strong>Processed on this device.</strong> No external AI or service receives your resume. Uploads are parsed in memory and discarded after processing. A preview changes nothing in your library. PDF/DOCX files up to 10 MB; pasted text up to 250,000 characters.</div>
    <div class="grid2"><form id="resume-upload" class="panel"><span class="eyebrow">PDF OR WORD</span><h2>Upload your resume</h2><label>Resume file<input id="resume-file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required></label><p class="tiny muted">Searchable PDFs and DOCX files are supported. Scanned PDFs need text recognition in your PDF software first; this app does not include OCR.</p><button type="submit">Extract file preview</button></form>
    <form id="resume-paste" class="panel"><span class="eyebrow">PLAIN TEXT</span><h2>Paste resume text</h2><label>Resume text<textarea id="resume-text" required maxlength="250000" placeholder="Experience&#10;Acme Corp | Data Analyst | Jan 2022 – Present&#10;• Automated Python reporting, saving 8 hours weekly.">${esc(resumeText)}</textarea></label><button type="submit">Extract text preview</button></form></div><div id="resume-error" class="form-error" role="alert" hidden></div><p class="tiny muted">Extraction preserves wording and metrics, joining wrapped lines with spaces. It suggests tags only when their names occur in a bullet. Complex layouts may need corrections in the preview.</p>`;
  $('#resume-text').oninput=e=>resumeText=e.target.value;
  $('#resume-paste').onsubmit=async e=>{e.preventDefault();await buildResumePreview({kind:'text',text:$('#resume-text').value});};
  $('#resume-upload').onsubmit=async e=>{
    e.preventDefault();const file=$('#resume-file').files[0];
    try {
      if(!file)throw Error('Choose a PDF or DOCX first.');
      if(!/\.(pdf|docx)$/i.test(file.name))throw Error('Only PDF and DOCX files are supported. Paste text for other formats.');
      if(file.size>10*1024*1024)throw Error('File exceeds the 10 MB limit.');
      if(!file.size)throw Error('The selected file is empty.');
      const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not read this file.'));reader.readAsDataURL(file);});
      await buildResumePreview({kind:'file',filename:file.name,content_base64:base64});
    }catch(err){resumeError(err.message);}
  };
}

function resumeError(msg) {const el=$('#resume-error');if(el){el.hidden=false;el.textContent=msg;}else notice(msg,true);}
async function buildResumePreview(data) {
  if(resumeBusy)return;resumeBusy=true;
  document.querySelectorAll('#content button[type=submit]').forEach(b=>b.disabled=true);
  notice('Extracting locally… Your library is unchanged.');
  try {
    const result=await api('resume/preview',data);
    resumeDraft=result;
    for(const item of result.items){item.selected=true;item.action=result.duplicates[item.id]?.length?'review':'new';item.target_version_id=result.duplicates[item.id]?.find(c=>c.version_id)?.version_id||'';}
    duplicateDirty=false;renderResumePreview();notice('Preview ready. Review associations, wording, and duplicate choices before confirming.');
  }catch(err){resumeError(err.message);}finally{resumeBusy=false;document.querySelectorAll('#content button[type=submit]').forEach(b=>b.disabled=false);updateImportStatus();}
}

function importField(label,kind,id,key,value,area=false) {
  const attrs=`data-resume-kind="${kind}" data-resume-id="${attr(id)}" data-resume-field="${key}"`;
  return `<label>${label}${area?`<textarea ${attrs}>${esc(value)}</textarea>`:`<input ${attrs} value="${attr(value)}">`}</label>`;
}

function renderResumePreview() {
  const d=resumeDraft;
  const groups=d.groups.map(g=>[g.id,importGroupHeading(g)]);
  const targets=S.versions.slice().sort((a,b)=>b.number-a.number).map(v=>[v.id,`${entryType(v)} · ${entryHeading(v)} · v${v.number} · ${v.bullet.slice(0,90)}`]);
  const eligible=d.items.filter(i=>i.selected&&i.action!=='skip');
  const unresolved=eligible.filter(i=>i.action==='review');
  $('#content').innerHTML=intro('Review before it becomes history.',esc(d.source_filename),button('Cancel preview','resume-cancel','','secondary'))+
    `<div class="import-steps"><span>1 · Add resume</span><strong>2 · Review & resolve duplicates</strong><span>3 · Confirm import</span></div><div class="callout"><strong>Your library is unchanged.</strong> ${d.items.length} entry candidates, grouped by resume section and organization. Correct uncertain headers, move bullets as needed, and choose what to import. Previews expire after 30 minutes or a server restart.</div>
    ${d.warnings.map(w=>`<p class="callout warning">${esc(w)}</p>`).join('')}
    <div class="actions import-toolbar">${button('+ Add entry group','resume-add-group')}${button('Edit extracted text & reparse','resume-reparse')}${button('Recheck duplicates','resume-duplicates')}<span class="tiny muted">Exact = same wording after case/whitespace normalization. Likely = similar wording; metrics may differ.</span></div>
    <div id="resume-error" class="form-error" role="alert" hidden></div>
    <div class="stack">${d.groups.map(g=>`<section class="panel import-group"><div class="section-line"><h2>${esc(importGroupHeading(g))}</h2><span class="badge">${d.items.filter(i=>i.group_id===g.id).length} bullets</span></div>
    ${g.warnings.length?`<details open><summary>Fields to review</summary><ul>${g.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}
    <label>Resume section<select data-resume-category="${g.id}">${options(entryTypes(),g.category||'experience')}</select></label>${importField(g.category==='experience'?'Entry title (optional)':'Entry title / qualification / project name *','group',g.id,'title',g.title||'')}<div class="grid2">${importField(g.category==='experience'?'Employer *':g.category==='education'?'School / institution (optional)':'Organization / issuer (optional)','group',g.id,'employer',g.employer)}${importField(g.category==='experience'?'Role / job title *':'Field / level / context (optional)','group',g.id,'role',g.role)}${importField('Dates · as written','group',g.id,'employment_dates',g.employment_dates)}${importField('Default project (optional)','group',g.id,'project',g.project)}</div>
    ${g.source_header?`<details><summary>Original role header</summary><div class="source">${esc(g.source_header)}</div></details>`:''}
    ${d.items.filter(i=>i.group_id===g.id).map(i=>`<article class="import-bullet ${!i.selected?'not-selected':''}" data-preview-item="${i.id}"><div class="section-line"><label class="check"><input type="checkbox" data-resume-select="${i.id}" ${i.selected?'checked':''}>Import this entry</label><span class="tiny muted">${esc(i.source_location)}</span></div>
    ${i.warnings.map(w=>`<p class="tiny muted">${esc(w)}</p>`).join('')}
    ${importField('Entry wording *','item',i.id,'bullet',i.bullet,true)}<div class="grid2">${importField('Skill tags · comma separated','item',i.id,'tags',i.tags.join(', '))}${importField('Bullet project (overrides group default)','item',i.id,'project',i.project)}</div>
    <label>Move to group<select data-resume-move="${i.id}">${options(groups,i.group_id)}</select></label>
    <details><summary>Original extracted wording</summary><div class="source">${esc(i.original_text)}</div></details>
    <div class="duplicate-box">${(d.duplicates[i.id]||[]).length?`<strong>Possible duplicate${d.duplicates[i.id].length>1?'s':''}</strong>${d.duplicates[i.id].map(c=>`<div class="source"><span class="badge">${esc(c.kind)} · ${c.similarity}%</span> ${esc(c.employer)} · ${esc(c.role)}${c.version_id?' · v'+c.number:' · '+esc(c.preview_item_id)}<br>${esc(c.bullet)}</div>`).join('')}`:'<p class="tiny muted">No duplicates found at the last check.</p>'}
    <label>Import decision<select data-resume-action="${i.id}">${options([['review','Choose how to handle this duplicate…'],['new','New accomplishment (only if no duplicate)'],['skip','Skip this bullet'],['separate','Import as a separate accomplishment'],['revision','Add a new version to an existing accomplishment']],i.action)}</select></label>
    ${i.action==='revision'?`<label>Existing version to use as parent<select data-resume-target="${i.id}">${options(targets,i.target_version_id,'Choose an existing bullet version…')}</select></label><p class="tiny muted">A new revision will be appended. The existing preferred version and saved applications stay unchanged.</p>`:''}</div></article>`).join('')}
    </section>`).join('')}</div>
    <details class="panel import-separated"><summary>Other resume information · ${d.separate.length} lines · not imported as bullets</summary><p class="tiny muted">Contact details, summaries, and unclassified text stay outside the resume library. The other recognized sections are selectable entries above.</p>${d.separate.map(s=>`<div class="source"><span class="badge">${esc(s.section)}</span> <span class="tiny muted">${esc(s.source_location)}</span><br>${esc(s.text)}</div>`).join('')}</details>
    <details class="panel import-separated"><summary>Full extracted source text</summary><div class="job-source">${esc(d.extracted_text)}</div></details>
    <div class="import-confirm panel"><div><strong id="import-count">${eligible.length} selected for import</strong><p id="duplicate-status" class="tiny muted">${duplicateDirty?'Wording or selections changed. Recheck duplicates before importing.':unresolved.length?unresolved.length+' duplicate decisions need review.':'Duplicate check complete. Confirm only after reviewing the selected wording and associations.'}</p></div><div class="actions">${button('Recheck duplicates','resume-duplicates')}${button('Confirm import','resume-confirm','','')}</div></div>`;
  $('#content').addEventListener('input',resumeInput);
  $('#content').addEventListener('change',resumeChange);
  updateImportStatus();
}

function resumeInput(e) {
  const el=e.target;if(!resumeDraft||!el.dataset.resumeField)return;
  const collection=el.dataset.resumeKind==='group'?resumeDraft.groups:resumeDraft.items;
  const item=collection.find(i=>i.id===el.dataset.resumeId);if(!item)return;
  item[el.dataset.resumeField]=el.dataset.resumeField==='tags'?el.value.split(',').map(t=>t.trim()).filter(Boolean):el.value;
  if(el.dataset.resumeField==='bullet')duplicateDirty=true;
  updateImportStatus();
}
function resumeChange(e) {
  if(!resumeDraft)return;const el=e.target;
  if(el.dataset.resumeCategory){const g=resumeDraft.groups.find(g=>g.id===el.dataset.resumeCategory);g.category=el.value;renderResumePreview();return;}
  for(const [key,field] of [['resumeSelect','selected'],['resumeMove','group_id'],['resumeAction','action'],['resumeTarget','target_version_id']]) {
    if(!el.dataset[key])continue;
    const i=resumeDraft.items.find(i=>i.id===el.dataset[key]);i[field]=field==='selected'?el.checked:el.value;
    if(field==='selected')duplicateDirty=true;
    renderResumePreview();return;
  }
}
function updateImportStatus() {
  if(!resumeDraft||!$('#import-count'))return;
  const items=resumeDraft.items.filter(i=>i.selected&&i.action!=='skip');
  $('#import-count').textContent=`${items.length} selected for import`;
  const unresolved=items.some(i=>i.action==='review'||(i.action==='revision'&&!i.target_version_id));
  const incomplete=items.filter(i=>{const g=resumeDraft.groups.find(g=>g.id===i.group_id);return !g||!i.bullet.trim()||((g.category||'experience')==='experience'?(!g.employer.trim()||!g.role.trim()):!g.title?.trim());});
  $('#duplicate-status').textContent=!resumeDraft.items.length?'No bullets were extracted. Use “Edit extracted text & reparse” to review the source.':!items.length?'Select at least one bullet to import.':incomplete.length?`${incomplete.length} selected entry/entries need required fields: wording plus employer/role for work, or a title for other sections. Complete the fields or deselect those entries.`:duplicateDirty?'Recheck duplicates after editing wording or selection.':unresolved?'Resolve all selected duplicate decisions and choose revision targets.':'Ready to import. Your selected fields and duplicate decisions are complete.';
  document.querySelector('[data-action="resume-confirm"]').disabled=resumeBusy||duplicateDirty||unresolved||!!incomplete.length||!items.length;
}

async function recheckResumeDuplicates() {
  const result=await api('resume/duplicates',{token:resumeDraft.token,items:resumeDraft.items});
  resumeDraft.duplicates=result.duplicates;
  for(const i of resumeDraft.items){if(result.duplicates[i.id]?.length&&i.action==='new')i.action='review';if(!result.duplicates[i.id]?.length&&i.action==='review')i.action='new';}
  duplicateDirty=false;renderResumePreview();notice('Duplicates checked against current library and other preview bullets.');
}

document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el||!el.dataset.action.startsWith('resume-'))return;
  const action=el.dataset.action;
  try {
    if(action==='resume-cancel') {await api('resume/cancel',{token:resumeDraft.token});resumeDraft=null;resumeText='';renderResume();notice('Preview cancelled. Your library was not changed.');}
    if(action==='resume-reparse') {resumeText=resumeDraft.extracted_text;await api('resume/cancel',{token:resumeDraft.token});resumeDraft=null;renderResume();}
    if(action==='resume-add-group') {resumeDraft.groups.push({id:'role-'+crypto.randomUUID(),category:'project',title:'',employer:'',role:'',employment_dates:'',project:'',warnings:['New group; choose a section and enter a title before importing.'],source_header:''});renderResumePreview();}
    if(action==='resume-duplicates') {el.disabled=true;await recheckResumeDuplicates();}
    if(action==='resume-confirm') {
      if(resumeBusy)return;
      const items=resumeDraft.items.filter(i=>i.selected&&i.action!=='skip').map(i=>{const g=resumeDraft.groups.find(g=>g.id===i.group_id);return {...i,category:g.category||'experience',title:g.title||'',employer:g.employer,role:g.role,employment_dates:g.employment_dates,project:i.project||g.project};});
      if(items.some(i=>!i.bullet.trim()||(i.category==='experience'?(!i.employer.trim()||!i.role.trim()):!i.title.trim())))throw Error('Work entries require employer, role, and wording. Other entries require a title and wording. Complete missing fields or deselect the entry.');
      if(duplicateDirty)throw Error('Recheck duplicates before confirming.');
      resumeBusy=true;updateImportStatus();
      const result=await api('resume/confirm',{token:resumeDraft.token,items});resumeDraft=null;resumeText='';await refresh();location.hash='library';await render();notice(`${result.imported} bullet version${result.imported===1?'':'s'} imported. All earlier versions are preserved.`);
    }
  }catch(err){resumeError(err.message);}finally{resumeBusy=false;el.disabled=false;updateImportStatus();}
});
