'use strict';
let S, currentJob = '', mode = 'keyword', showAll = false, selected = [], editingApp = '', appName = '', allowDuplicates = false;
const ENTRY_TYPES = [['experience','Work experience'],['education','Education'],['project','Projects'],['skill','Technical skills'],['certification','Certifications'],['interest','Interests']];
const entryTypes = () => ENTRY_TYPES.slice(0,4).concat((S?.additional_sections||[]).filter(section=>section.category!=='skill').map(section=>[section.category,section.name]));
const entryType = v => entryTypes().find(([k])=>k===(v.category||'experience'))?.[1]||'Work experience';
const entryHeading = v => (v.category==='experience'?[v.employer,v.role,v.title]:[v.title,v.employer,v.role]).filter(Boolean).join(' · ')||entryType(v);
let filters = {q:'', employer:'', role:'', skill:'',category:''};
let librarySelected = new Set();
let matchGeneration = 0;
let pdfMargins={top:0.75,bottom:0.75,left:0.5,right:0.5};
let pdfFont='Arial';
let activeProfile = '';
let profilesInitialized = false;
let resumeContact = {name:'',location:'',email:'',phone:'',linkedin:''};
try {if(!localStorage.getItem('resume-home-clean-slate-20261012')){localStorage.removeItem('resume-home-contact');localStorage.setItem('resume-home-clean-slate-20261012','1');}} catch {}
try { Object.assign(resumeContact,JSON.parse(localStorage.getItem('resume-home-contact')||'{}')); } catch {}
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const attr = esc;
const version = id => S.versions.find(v => v.id === id);
const job = id => S.jobs.find(j => j.id === id);
const date = d => new Date(d).toLocaleString();
const tags = v => `<div class="tags">${v.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>`;
const button = (label, action, id='', cls='secondary small') => `<button type="button" class="${cls}" data-action="${action}" data-id="${attr(id)}">${label}</button>`;
const evidenceBadge = label => `<span class="badge ${label.startsWith('strong')?'strong':label.startsWith('partial')?'partial':'none'}">${esc(label)}</span>`;
const options = (items, value, placeholder) => `${placeholder !== undefined?`<option value="">${esc(placeholder)}</option>`:''}${items.map(([id,label])=>`<option value="${attr(id)}" ${id===value?'selected':''}>${esc(label)}</option>`).join('')}`;
function notice(msg, error=false) { const el=$('#notice'); el.textContent=msg; el.hidden=false; el.className=error?'error':''; clearTimeout(notice.timer); notice.timer=setTimeout(()=>el.hidden=true,7000); }
async function api(path, data) { const res=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Resume-App':'1'},body:JSON.stringify(data)}); const result=await res.json(); if(!res.ok) throw Error(result.error || 'Request failed.'); return result; }
async function refresh() { S=await api('state');if(!profilesInitialized&&(S.profiles||[]).length){const p=S.profiles[0];activeProfile=p.id;for(const k of Object.keys(resumeContact))resumeContact[k]=p[k]||'';}profilesInitialized=true; $('#library-count').textContent=S.accomplishments.length; $('#job-count').textContent=S.jobs.length; }
function intro(title,subtitle,actions='') { return `<div class="intro"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`; }
function empty(title,body,action='') { return `<div class="empty"><div class="empty-symbol">✧</div><h2>${title}</h2><p>${body}</p>${action}</div>`; }
function route() { return location.hash.slice(1).split('/'); }
async function render() {
  const [page='library',id]=route();
  document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===(page==='history'?'library':page)));
  matchGeneration++;
  if(page==='history') return renderHistory(id);
  if(page==='jobs') return renderJobs(id);
  if(page==='match') return renderMatch();
  if(page==='backup') return renderBackup();
  if(page==='resume') return renderResume();
  renderLibrary();
}
function renderLibrary() {
  const unique = k => [...new Set(S.versions.map(v=>v[k]).filter(Boolean))].sort().map(v=>[v,v]);
  $('#content').innerHTML=intro('Your experience, ready for the next role.','Keep the bullet points you have worked hard on in one place. Build a new resume without starting over.','<a class="button secondary" href="#resume">Import resume</a>'+button('Edit additional sections','manage-additional')+button('+ New entry','new-bullet','',''))+
  `<div class="stats"><div class="stat"><strong>${S.accomplishments.length}</strong><span>Resume entries</span></div><div class="stat"><strong>${S.versions.length}</strong><span>Versions preserved</span></div><div class="stat"><strong>${S.applications.length}</strong><span>Applications assembled</span></div></div>
  <div class="entry-categories" aria-label="Resume sections"><label>SECTION<select id="filter-category">${options(entryTypes(),filters.category,'All sections')}</select></label></div><div class="filters"><label>SEARCH YOUR LIBRARY<input id="filter-q" type="search" placeholder="Search wording, context, or metrics…" value="${attr(filters.q)}"></label><label>ORGANIZATION<select id="filter-employer">${options(unique('employer'),filters.employer,'All organizations')}</select></label><label>ROLE<select id="filter-role">${options(unique('role'),filters.role,'All roles')}</select></label><label>SKILL<select id="filter-skill">${options([...new Set(S.versions.flatMap(v=>v.tags))].sort().map(v=>[v,v]),filters.skill,'All skills')}</select></label></div>
  <div class="section-line"><h2>Resume library</h2><span class="muted tiny">Search includes all saved versions</span></div><div class="actions" id="bulk-actions"></div><div id="library-results"></div>`;
  for(const k of Object.keys(filters)) $('#filter-'+k).addEventListener(k==='q'?'input':'change',e=>{filters[k]=e.target.value; libraryResults();});
  libraryResults();
}
function libraryResults() {
  librarySelected=new Set([...librarySelected].filter(id=>S.accomplishments.some(a=>a.id===id)));
  const list=[];
  for(const a of S.accomplishments) {
    const vs=S.versions.filter(v=>v.accomplishment_id===a.id).sort((a,b)=>b.number-a.number);
    const found=vs.filter(v=>(!filters.category||(v.category||'experience')===filters.category)&&(!filters.employer||v.employer===filters.employer)&&(!filters.role||v.role===filters.role)&&(!filters.skill||v.tags.includes(filters.skill))&&(!filters.q||[v.bullet,v.title,v.date_text,v.context,v.metrics,v.project,v.employer,v.role,...v.tags].join(' ').toLowerCase().includes(filters.q.toLowerCase())));
    if(!found.length) continue;
    const v=found.find(v=>v.id===a.preferred_version_id)||found[0];
    list.push(`<article class="card"><label class="check"><input type="checkbox" data-library-select="${attr(a.id)}" ${librarySelected.has(a.id)?'checked':''}>Select entry</label><div class="card-top"><span><span class="badge">${esc(entryType(v))}</span> ${esc(entryHeading(v))}</span><span class="badge ${v.id===a.preferred_version_id?'preferred':''}">${v.id===a.preferred_version_id?'★ Preferred · ':''}v${v.number}</span></div>${v.project?`<div class="tiny muted">${esc(v.project)}</div>`:''}<p class="bullet">${esc(v.bullet)}</p>${tags(v)}<div class="card-bottom"><span class="tiny muted">${vs.length} version${vs.length===1?'':'s'} · ${esc(v.start_date||v.date_text||'Undated')}${v.end_date?' — '+esc(v.end_date):''}</span><div class="actions">${button('Copy','copy-entry',v.id)}${button('Edit','edit-bullet',v.id)}${button('Delete','delete-entry',a.id,'secondary small danger')}<a class="button secondary small" href="#history/${a.id}">View history ↗</a></div></div></article>`);
  }
  $('#bulk-actions').innerHTML=`<span>${librarySelected.size} selected</span><button class="secondary danger" data-action="delete-selected" ${librarySelected.size?'':'disabled'}>Delete selected</button>${button('Clear selection','clear-selection')}`;
  $('#library-results').innerHTML=list.length?`<div class="cards">${list.join('')}</div>`:S.accomplishments.length?empty('No matching accomplishments','Try a broader search or clear your filters.',button('Clear filters','clear-filters')):empty('Start your resume library','Add work experience, education, a project, skills, certifications, or interests. Each saved entry has its own revision history.',button('+ Add your first entry','new-bullet','',''));
}
function modal(html) { $('#modal-content').innerHTML=html; $('#modal').showModal(); }
const head = title => `<div class="modal-head"><h2>${title}</h2>${button('✕','close','','secondary small')}</div>`;
function field(name,label,value='',type='text',required=false) { return `<label>${label}${required?' *':''}<input name="${name}" type="${type}" value="${attr(value)}" ${required?'required':''}></label>`; }
function area(name,label,value='',required=false) { return `<label>${label}${required?' *':''}<textarea name="${name}" ${required?'required':''}>${esc(value)}</textarea></label>`; }
function formEnd(label) { return `<div class="form-error" hidden role="alert"></div><div class="form-actions">${button('Cancel','close','','secondary')}<button type="submit">${label}</button></div></form>`; }
function bindForm(handler) { $('#modal form').addEventListener('submit',async e=>{e.preventDefault(); const form=e.currentTarget; const submit=form.querySelector('[type=submit]'); submit.disabled=true; try { await handler(Object.fromEntries(new FormData(form)),form); } catch(err) { const el=form.querySelector('.form-error'); el.hidden=false; el.textContent=err.message; } finally { submit.disabled=false; }}); }
function entryCore(category,v) {
  const names={experience:['Employer','Role','Work location (optional)'],education:['School / institution','Field of study (optional)','Degree / qualification'],project:['Organization (optional)','Your role (optional)','Project name'],skill:['Context / organization (optional)','Proficiency / level (optional)','Skill name or group'],certification:['Issuing organization (optional)','Credential ID / level (optional)','Certification name'],interest:['Organization (optional)','Context (optional)','Interest name']};
  const [org,role,title]=names[category]||['Organization (optional)','Context (optional)','Item title'];
  return `<div class="grid2">${field('employer',org,v.employer,'text',category==='experience')}${field('role',role,v.role,'text',category==='experience')}</div>${field('title',title,v.title,'text',category!=='experience')}${category==='education'?field('location','School location (optional)',v.location):''}`;
}
function editBullet(id) {
  const v=id?version(id):{category:filters.category||'experience'};
  modal(head(id?`Revise entry · from v${v.number}`:'Add a resume entry')+`<p class="required-note">* Required. Every saved edit creates a new immutable version.</p><form id="bullet-form"><label>Resume section<select name="category" id="entry-category">${options(entryTypes(),v.category||'experience')}</select></label><div id="entry-core">${entryCore(v.category||'experience',v)}</div>${field('project','Related project (optional)',v.project)}${area('bullet','Entry wording / details',v.bullet,true)}${field('date_text','Dates as written (optional)',v.date_text)}<div class="grid2">${field('start_date','Exact start / issue date (optional)',v.start_date,'date')}${field('end_date','Exact end / expiry date (optional)',v.end_date,'date')}</div>${field('tags','Skill tags · comma separated',(v.tags||[]).join(', '))}${area('metrics','Verified metrics · only supported facts',v.metrics)}${area('context','Supporting context / sources',v.context)}<label>Tailored to job (optional)<select name="tailored_job_id">${options(S.jobs.map(j=>[j.id,j.company+' · '+j.title]),v.tailored_job_id,'General purpose')}</select></label>${field('note','Revision note',id?'':'Initial version')}<label class="check"><input type="checkbox" name="preferred" ${id?'':'checked'}>Mark this version as preferred</label>${formEnd(id?'Save new revision':'Create entry')}`);
  $('#entry-category').onchange=e=>{$('#entry-core').innerHTML=entryCore(e.target.value,Object.fromEntries(new FormData($('#bullet-form'))));};
  bindForm(async data=>{data.tags=data.tags.split(',').map(t=>t.trim()).filter(Boolean);data.preferred=data.preferred==='on';if(id){data.accomplishment_id=v.accomplishment_id;data.parent_id=id;}const result=await api('version',data);$('#modal').close();await refresh();location.hash='history/'+result.id;await render();notice(`Version ${result.number} saved. Earlier versions are preserved.`);});
}
function manageAdditionalSections() {
  modal(head('Additional information sections')+`<p class="muted">Rename a subheading or add one for languages, awards, or other details. Existing entries stay in their section.</p><div class="stack">${S.additional_sections.filter(section=>section.category!=='skill').map(section=>`<div class="row"><strong>${esc(section.name)}</strong>${button('Rename','rename-additional',section.category)}</div>`).join('')}</div><div class="form-actions">${button('+ Add section','add-additional','','')}${button('Done','close')}</div>`);
}
function editAdditionalSection(category='') {
  const section=S.additional_sections.find(item=>item.category===category);
  $('#modal').close();
  modal(head(section?'Rename section':'Add section')+`<form>${field('name','Subheading',section?.name||'','text',true)}<p class="tiny muted">This heading appears under Additional Information in the PDF.</p>${formEnd(section?'Save name':'Create section')}`);
  bindForm(async data=>{await api('additional-section',{...data,...(section?{category}:{})});$('#modal').close();await refresh();await render();manageAdditionalSections();notice('Additional information section saved.');});
}
function renderHistory(id) {
  const a=S.accomplishments.find(a=>a.id===id);
  if(!a){$('#content').innerHTML=empty('Accomplishment not found','Return to the library to choose an accomplishment.','<a class="button" href="#library">Library</a>');return;}
  const vs=S.versions.filter(v=>v.accomplishment_id===id).sort((a,b)=>b.number-a.number), latest=vs[0];
  $('#content').innerHTML=intro('Every version tells a story.',`${esc(entryType(latest))} · ${esc(entryHeading(latest))} · Stable ID: <span class="tiny">${esc(id)}</span>`,button('+ Revise latest','edit-bullet',latest.id,''))+
  `<a href="#library" class="tiny">← Back to library</a><div class="panel" style=""><h3>Compare wording & details</h3>${vs.length>1?`<div class="grid2"><label>FROM<select id="diff-a">${options(vs.map(v=>[v.id,'v'+v.number+' · '+v.note]),vs[1].id)}</select></label><label>TO<select id="diff-b">${options(vs.map(v=>[v.id,'v'+v.number+' · '+v.note]),latest.id)}</select></label></div><div id="diff-result"></div>`:'<p class="muted">Save another version to see additions, removals, and metadata changes.</p>'}</div>
  <div class="section-line"><h2>Immutable revision history</h2><span class="tiny muted">Restoring creates a new revision</span></div><div class="history">${vs.map(v=>`<article class="panel"><div class="card-top"><span><strong>Version ${v.number}</strong> · ${esc(entryType(v))} · ${esc(date(v.created_at))}</span>${v.id===a.preferred_version_id?'<span class="badge preferred">★ Preferred</span>':''}</div><p class="tiny muted">${esc(v.note||'No revision note')} · Parent: ${v.parent_id?'v'+version(v.parent_id).number:'Original'}${v.tailored_job_id?' · Tailored to '+esc(job(v.tailored_job_id)?.title||'job'):''}</p><p class="version-text">${esc(v.bullet)}</p>${tags(v)}${renderProvenance(v.id)}<details><summary>Context, metrics & version ID</summary><div class="metadata">${esc(entryHeading(v))}${v.project?' · '+esc(v.project):''}\nDates: ${esc(v.start_date||'—')} to ${esc(v.end_date||'—')}\nVerified metrics: ${esc(v.metrics||'None recorded')}\nSupporting context: ${esc(v.context||'None recorded')}\nVersion ID: ${esc(v.id)}</div></details><div class="actions">${button('Revise / tailor','edit-bullet',v.id)}${v.id!==a.preferred_version_id?button('★ Prefer this','preferred',v.id):''}${button('Restore as new revision','restore',v.id)}</div></article>`).join('')}</div>`;
  if(vs.length>1){$('#diff-a').onchange=loadDiff;$('#diff-b').onchange=loadDiff;loadDiff();}
}
async function loadDiff() { try {const a=$('#diff-a').value,b=$('#diff-b').value;const diff=await api(`diff?a=${a}&b=${b}`);if(!$('#diff-result')||$('#diff-a').value!==a||$('#diff-b').value!==b)return;$('#diff-result').innerHTML=`<div class="diff">${diff.changes.map(c=>c.op==='equal'?esc(c.before):`${c.before?'<del>'+esc(c.before)+'</del>':''}${c.after?'<ins>'+esc(c.after)+'</ins>':''}`).join('')}</div>${Object.entries(diff.metadata).map(([k,c])=>`<div class="metadata"><strong>${esc(k.replaceAll('_',' '))}:</strong> <del>${esc(Array.isArray(c.before)?c.before.join(', '):c.before||'—')}</del> → ${esc(Array.isArray(c.after)?c.after.join(', '):c.after||'—')}</div>`).join('')}<p class="tiny muted">Red / struck through = removed. Green = added.${a===b?' Same version selected.':''}</p>`;}catch(e){notice(e.message,true);} }
function renderJobs(id) {
  const j=job(id);
  if(!j){$('#content').innerHTML=intro('Know what the role asks for.','Save a job description, then review its requirements against the source.',button('+ Add job description','new-job','',''))+(S.jobs.length?`<div class="cards">${S.jobs.map(j=>`<article class="card"><span class="eyebrow">${esc(j.company)}</span><h2>${esc(j.title)}</h2><p class="muted tiny">${S.requirements.filter(r=>r.job_id===j.id).length} requirements · Saved ${esc(date(j.created_at))}</p><div class="actions"><a class="button secondary" href="#jobs/${j.id}">Review requirements</a>${button('Match bullets →','job-match',j.id,'')}</div></article>`).join('')}</div>`:empty('A role worth applying for','Paste the full job description. Basic extraction creates source-linked candidates for your review.',button('+ Add a job','new-job','','')));return;}
  const reqs=S.requirements.filter(r=>r.job_id===id&&!/^\s*(?:[•*\-]\s*)?(job title|department|employment type|experience level)\s*[:：]/i.test(r.text));
  $('#content').innerHTML=intro(esc(j.title),esc(j.company),button('Match & build →','job-match',id,''))+`<p><a href="#jobs" class="tiny">← All job descriptions</a></p><div class="callout"><strong>Basic extraction · review required.</strong> Local rules suggest skills, tools, and qualifications from sentences and headings. They can miss requirements or include irrelevant lines. Required / preferred is assigned only from explicit language or section headings. Edit or add requirements below.</div><div class="panel"><div class="section-line"><h2>Job details</h2>${button('Edit details','edit-job-details',j.id)}</div><div class="grid2">${[['Job title',j.title],['Department',j.department],['Employment type',j.employment_type],['Experience level',j.experience_level]].map(([label,value])=>`<div><label>${label}</label><p>${esc(value||'Not specified')}</p></div>`).join('')}</div></div><div class="split"><div class="panel"><div class="section-line"><h2>Requirements · ${reqs.length}</h2>${button('+ Add manually','new-requirement',id)}</div>${reqs.length?reqs.map(r=>`<article class="requirement"><div class="row"><span class="badge">${esc(r.priority)}</span><span class="tiny muted">${esc(r.kind)}</span></div><p>${esc(r.text)}</p>${r.source?`<div class="source"><span class="tiny muted">SOURCE PASSAGE</span><br>${esc(r.source)}</div>`:'<p class="tiny muted">Manual requirement · no source passage</p>'}<div class="actions">${button('Edit','edit-requirement',r.id)}${button('Remove','delete-requirement',r.id,'secondary small danger')}</div></article>`).join(''):'<p class="muted">No candidates found. Add requirements manually from the source description.</p>'}</div><div class="panel"><h3>Original job description</h3><div class="job-source">${esc(j.description)}</div></div></div>`;
}
function newJob() { modal(head('Save a job description')+`<form>${field('company','Company','','text',true)}${field('title','Job title (fallback if not found in description)','','text',false)}${field('department','Department')}${field('employment_type','Employment type')}${field('experience_level','Experience level')}${area('description','Paste the full job description','',true)}<p class="tiny muted">The original description is preserved as evidence. Extraction runs locally with simple rules; you can edit every requirement.</p>${formEnd('Save & extract requirements')}`);bindForm(async d=>{const r=await api('job',d);$('#modal').close();await refresh();location.hash='jobs/'+r.id;await render();notice(`${r.count} candidate requirements extracted. Please review them.`);}); }
function editRequirement(id,jid) { const r=S.requirements.find(r=>r.id===id)||{job_id:jid};modal(head(id?'Edit requirement':'Add requirement')+`<form>${area('text','Requirement',r.text,true)}<div class="grid2"><label>Priority<select name="priority">${options(['unspecified','required','preferred'].map(x=>[x,x]),r.priority||'unspecified')}</select></label><label>Type<select name="kind">${options(['skill/tool','qualification','responsibility'].map(x=>[x,x]),r.kind||'skill/tool')}</select></label></div>${area('source','Exact source passage (optional)',r.source)}<details><summary>View original description</summary><div class="job-source">${esc(job(r.job_id).description)}</div></details><p class="tiny muted">Leave source blank for a manual requirement. Editing clears any manual match corrections for this requirement because its meaning may change.</p>${formEnd('Save requirement')}`);bindForm(async d=>{await api('requirement',{...d,id,job_id:r.job_id});$('#modal').close();await refresh();await render();notice('Requirement saved.');}); }
async function renderMatch() {
  if(!S.jobs.length){$('#content').innerHTML=intro('Make your experience relevant.','Connect the role’s requirements to your actual work.')+empty('Start with a job description','Save a job to rank bullet versions and build an application.',button('+ Add job description','new-job','',''));return;}
  if(!job(currentJob))currentJob=S.jobs[0].id;
  $('#content').innerHTML=intro('A resume for this role, without the copy-paste marathon.','Review the job, pick the experience that fits, and leave the page layout to Resume.Home.')+`<div class="match-controls"><label>SAVED JOB<select id="match-job">${options(S.jobs.map(j=>[j.id,j.company+' · '+j.title]),currentJob)}</select></label><label>MATCHING METHOD<select id="match-mode">${options([['keyword','Basic · literal keyword matching'],['semantic','Semantic · local synonym matching']],mode)}</select></label></div><div class="callout" id="mode-note"></div><div class="split"><div><div id="gap-summary"></div><div class="section-line"><h2>Ranked bullet versions</h2><label class="check"><input type="checkbox" id="show-all" ${showAll?'checked':''}>Show all versions</label></div><p class="tiny muted">One best version per accomplishment by default. Relevance is text coverage, not a hiring probability. Tags alone are partial evidence.</p><div id="match-results">Loading evidence…</div></div><div id="builder" class="panel application-builder"></div></div>`;
  $('#match-job').onchange=e=>{currentJob=e.target.value;selected=[];editingApp='';appName='';allowDuplicates=false;renderMatch();};
  $('#match-mode').onchange=e=>{mode=e.target.value;loadMatches();};
  $('#show-all').onchange=e=>{showAll=e.target.checked;loadMatches();};
  renderBuilder();await loadMatches();
}
async function loadMatches() {
  const generation=++matchGeneration;
  $('#mode-note').innerHTML=mode==='keyword'?'<strong>Basic keyword matching.</strong> Compares literal terms in requirements with bullet wording, verified metrics, and manually supplied tags. It does not understand paraphrases or verify claims. Required requirements carry double weight.':'<strong>Limited semantic matching · local synonym dictionary.</strong> Normalizes a small set of related words (e.g. led ↔ leadership, partnered ↔ collaboration, JS ↔ JavaScript). No external AI or embeddings are used. It cannot reliably infer meaning, negation, years of experience, or credentials. Review all evidence labels.';
  try { const m=await api(`matches?job_id=${currentJob}&mode=${mode}`);if(generation!==matchGeneration||!$('#match-results'))return;
    const reqs=S.requirements.filter(r=>r.job_id===currentJob);
    $('#gap-summary').innerHTML=`<div class="panel"><h3>Coverage gaps</h3>${!reqs.length?'<p>No requirements yet. Add them before relying on ranking.</p>':`<p><strong>${m.unsupported.length}</strong> unsupported · <strong>${m.partial.length}</strong> with partial evidence only · ${reqs.length} total</p>${m.unsupported.map(r=>`<div class="source">${evidenceBadge('no evidence')} <span class="badge">${esc(r.priority)}</span><br>${esc(r.text)}</div>`).join('')}${m.partial.length?`<details><summary>Review partial evidence requirements</summary>${m.partial.map(r=>`<p>${esc(r.text)}</p>`).join('')}</details>`:''}${!m.unsupported.length?'<p class="tiny muted">Every requirement has at least some recorded overlap. This does not confirm qualification.</p>':''}`}<a class="tiny" href="#jobs/${currentJob}">Review & edit requirements ↗</a></div>`;
    const seen=new Set();const matches=m.ranked.filter(m=>showAll||(!seen.has(m.version.accomplishment_id)&&seen.add(m.version.accomplishment_id)));
    $('#match-results').innerHTML=matches.length?matches.map(m=>{const v=m.version;return `<article class="panel match-card"><div class="card-top"><span><span class="badge">${esc(entryType(v))}</span> ${esc(entryHeading(v))} · v${v.number}${v.tailored_job_id?' · Tailored':''}</span><span class="match-score">${m.score}<span class="tiny"> /100</span></span></div><p class="version-text">${esc(v.bullet)}</p>${tags(v)}${v.metrics?`<p class="tiny"><strong>Verified metrics:</strong> ${esc(v.metrics)}</p>`:''}<div class="actions">${button(selected.includes(v.id)?'✓ Selected':'+ Add to application','select-version',v.id,'small')}${button('Revise tags / tailor','edit-bullet',v.id)}<a class="button secondary small" href="#history/${v.accomplishment_id}">History</a></div><details><summary>Requirement evidence & manual corrections (${m.evidence.length})</summary>${m.evidence.map(e=>{const r=reqs.find(r=>r.id===e.requirement_id);return `<div class="evidence"><div class="row">${evidenceBadge(e.label)}${e.manual?'<span class="tiny muted">Human reviewed</span>':''}</div><p><strong>${esc(r.text)}</strong></p><p class="muted">${esc(e.explanation)}</p><p class="tiny muted">Evidence is the exact bullet and verified metrics shown above.</p><button class="secondary small" data-action="correct-match" data-id="${e.requirement_id}" data-version="${v.id}">Correct match</button></div>`;}).join('')}</details></article>`;}).join(''):empty('Your evidence starts in the library','Add an accomplishment to see individual versions ranked here.',button('+ New entry','new-bullet','',''));
  }catch(e){notice(e.message,true);if($('#match-results'))$('#match-results').textContent='Matching could not load. Switch the method or reload to retry.';}
}
const BUILDER_HEADERS={experience:'Work experience',education:'Education',project:'Projects',skill:'Technical skills',additional:'Additional information'};
const builderSection = v => ['experience','education','project','skill'].includes(v.category)?v.category:'additional';
function selectedGroups() {
  const groups=new Map();
  for(const id of selected){const v=version(id);if(!v)continue;const key=builderSection(v);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(id);}
  return [...groups].map(([key,ids])=>({key,ids}));
}
function renderSelectedGroups() {
  const groups=selectedGroups();
  if(!groups.length)return '<p class="muted">Add a ranked bullet to begin your selection.</p>';
  return groups.map((group,groupIndex)=>`<section class="builder-group"><div class="builder-group-head"><h3>${BUILDER_HEADERS[group.key]}</h3><div class="actions"><button class="secondary small" data-action="header-up" data-id="${group.key}" ${groupIndex===0?'disabled':''} aria-label="Move ${BUILDER_HEADERS[group.key]} up">↑</button><button class="secondary small" data-action="header-down" data-id="${group.key}" ${groupIndex===groups.length-1?'disabled':''} aria-label="Move ${BUILDER_HEADERS[group.key]} down">↓</button></div></div>${group.ids.map((id,i)=>{
    const v=version(id),coursework=group.key==='education'&&/^(?:relevant\s+)?coursework\b/i.test(v.title.trim()||v.bullet.trim());
    const title=group.key==='education'?(coursework?'':`<span class="builder-work"><span class="builder-work-line"><strong>${esc(v.title)}</strong><span>${esc(v.location||'')}</span></span><span class="builder-work-line"><span>${esc([v.employer,v.role].filter(Boolean).join(' · '))}</span><span>${esc(v.date_text||[v.start_date,v.end_date].filter(Boolean).join(' – '))}</span></span></span>`):group.key==='experience'?`<span class="builder-work"><span class="builder-work-line"><strong>${esc(v.employer)}</strong><span>${esc(v.title||'')}</span></span><span class="builder-work-line"><strong><em>${esc(v.role)}</em></strong><span>${esc(v.date_text||[v.start_date,v.end_date].filter(Boolean).join(' – '))}</span></span></span>`:`<span class="badge">${esc(v.title||v.employer||entryType(v))}</span>`;
    const wording=coursework?/^\s*(?:relevant\s+)?coursework\s*[:：]/i.test(v.bullet)?v.bullet:`Relevant coursework: ${v.bullet}`:v.bullet;
    return `<div class="selection"><div class="row"><div class="builder-entry-title"><span class="tiny muted">${selected.indexOf(id)+1} · v${v.number}</span>${title}</div><div class="actions"><button class="secondary small" data-action="up" data-id="${id}" ${i===0?'disabled':''} aria-label="Move entry ${i+1} up">↑</button><button class="secondary small" data-action="down" data-id="${id}" ${i===group.ids.length-1?'disabled':''} aria-label="Move entry ${i+1} down">↓</button>${button('×','remove-selection',id)}</div></div><p>${group.key==='education'?'• ':''}${esc(wording)}</p></div>`;
  }).join('')}</section>`).join('');
}
function renderBuilder() {
  selected=selectedGroups().flatMap(group=>group.ids);
  const apps=S.applications.filter(a=>a.job_id===currentJob);
  $('#builder').innerHTML=`<span class="eyebrow">APPLICATION BUILDER</span><h2>${editingApp?'Edit saved selection':'Make it yours.'}</h2><p class="muted tiny">Exact version IDs are saved. Future revisions won’t change these selections.</p><label>APPLICATION NAME<input id="app-name" value="${attr(appName)}" placeholder="e.g. ${attr(job(currentJob).company)} · first application"></label><div class="profile-picker"><label>Select profile<select id="builder-profile">${options((S.profiles||[]).map(p=>[p.id,p.label]),activeProfile,'Select profile')}</select></label>${button('Edit profiles','edit-contact','','secondary')}</div><label class="check"><input id="allow-duplicates" type="checkbox" ${allowDuplicates?'checked':''}>Allow multiple versions of one accomplishment</label><div>${renderSelectedGroups()}</div><div class="form-actions"><button class="secondary" data-action="preview-resume" ${selected.length?'':'disabled'}>Preview resume</button><button class="secondary" data-action="export-pdf" ${selected.length?'':'disabled'}>Export PDF</button>${editingApp?button('New selection','new-selection'):''}<button data-action="save-application" ${selected.length?'':'disabled'}>${editingApp?'Save changes':'Save application'} (${selected.length})</button></div><div class="section-line"><h2>Saved applications</h2></div>${apps.length?apps.map(a=>`<div class="saved-app"><h3>${esc(a.name)}</h3><p class="tiny muted">${S.selections.filter(s=>s.application_id===a.id).length} exact versions · ${esc(date(a.created_at))}</p><div class="actions">${button('Open','open-application',a.id)}<a class="button secondary small" href="/api/export?id=${a.id}&format=txt" download>Text ↓</a><a class="button secondary small" href="/api/export?id=${a.id}&format=md" download>Markdown ↓</a></div></div>`).join(''):'<p class="tiny muted">No saved applications for this role yet.</p>'}`;
  $('#builder-profile').onchange=e=>{activeProfile=e.target.value;const profile=(S.profiles||[]).find(p=>p.id===activeProfile);for(const key of Object.keys(resumeContact))resumeContact[key]=profile?.[key]||'';renderBuilder();};
  $('#app-name').oninput=e=>appName=e.target.value;$('#allow-duplicates').onchange=e=>allowDuplicates=e.target.checked;
}
function correction(rid,vid) { const r=S.requirements.find(r=>r.id===rid),v=version(vid),o=S.overrides.find(o=>o.requirement_id===rid&&o.version_id===vid);modal(head('Review the evidence')+`<p><strong>${esc(r.text)}</strong></p><div class="source">${esc(v.bullet)}${v.metrics?'<br>Verified metrics: '+esc(v.metrics):''}</div><form><label>Evidence label<select name="label">${options([['automatic','Use automatic matching'],...['strong evidence','partial evidence','no evidence'].map(x=>[x,x])],o?.label||'automatic')}</select></label>${area('note','Explanation for your correction',o?.note)}<p class="tiny muted">A manual correction applies to this exact requirement and bullet version in both matching modes.</p>${formEnd('Save correction')}`);bindForm(async d=>{await api('override',{...d,requirement_id:rid,version_id:vid});$('#modal').close();await refresh();await loadMatches();notice('Match correction saved.');}); }
function renderBackup() { $('#content').innerHTML=intro('Your library belongs to you.','Keep a complete, portable record of your accomplishments and applications.')+`<div class="grid2"><div class="panel"><h2>Export everything</h2><p class="muted">Includes all versions, parent relationships, preferences, jobs, requirements, manual match corrections, and ordered application selections.</p><a class="button" href="/api/backup" download>Download full JSON backup ↓</a></div><div class="panel"><h2>Import a backup</h2><p class="muted">Imports atomically and adds new records. Identical records are skipped. Conflicting IDs reject the entire import without modifying your data.</p><label>RESUME LIBRARY JSON<input type="file" id="backup-file" accept="application/json,.json"></label>${button('Import backup','import-backup','','')}</div></div><div class="callout warning"><strong>Restoring an older snapshot:</strong> If existing records have changed since export (such as a preferred version or edited requirement), import into a fresh database with <code>python -B app.py --db data/restored.sqlite3 --port 8766</code>. This preserves your current database.</div><div class="panel"><h2>Local by design</h2><p>The app binds only to 127.0.0.1. The Windows browser launcher stores data in the Resume.Home folder under your local app-data directory; running <code>app.py</code> directly stores data under <code>data/resume.sqlite3</code> unless you choose another path. No external services receive your text. There are no API keys or AI service dependencies.</p><p class="muted">No demo data is loaded automatically. A separate demo launcher is documented in the README. Backups contain your personal information; store them somewhere you trust.</p></div>`; }
function openContactEditor(){
  if($('#modal').open)$('#modal').close();
  modal(head('Edit profiles')+`<label>Saved profile<select id="contact-profile">${options((S.profiles||[]).map(p=>[p.id,p.label]),activeProfile,'Choose a profile')}</select></label><div class="actions">${button('Save as new profile','new-profile')}${activeProfile?button('Update profile','update-profile'):''}</div>${field('pdf-name','Full name',resumeContact.name)}${field('pdf-location','Location',resumeContact.location)}${field('pdf-email','Email',resumeContact.email)}${field('pdf-phone','Phone number',resumeContact.phone)}${field('pdf-linkedin','LinkedIn',resumeContact.linkedin)}<div class="form-actions">${button('Done','contact-done')}</div>`);
  for(const key of Object.keys(resumeContact)){ const input=document.querySelector('[name="pdf-'+key+'"]'); if(input)input.oninput=e=>{resumeContact[key]=e.target.value;try{localStorage.setItem('resume-home-contact',JSON.stringify(resumeContact));}catch{}}; }
  $('#contact-profile').onchange=e=>{activeProfile=e.target.value;const p=(S.profiles||[]).find(p=>p.id===activeProfile);if(p)for(const k of Object.keys(resumeContact))resumeContact[k]=p[k]||'';openContactEditor();};
 }
document.addEventListener('change',e=>{const id=e.target.dataset.librarySelect;if(!id)return;if(e.target.checked)librarySelected.add(id);else librarySelected.delete(id);libraryResults();});
document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el)return;const {action,id}=el.dataset;
  try {
    if(action==='clear-selection'){librarySelected.clear();return libraryResults();}
    if(action==='delete-selected'){
      const ids=[...librarySelected];
      if(!ids.length)return;
      modal(head('Delete selected entries?')+`<form><p>Permanently delete ${ids.length} entries and all their versions? This cannot be undone.</p><p>If any entry is used in a saved application, nothing will be deleted. Remove that entry from the saved application first.</p>${formEnd('Delete selected entries')}</form>`);
      bindForm(async()=>{await api('entries/delete',{ids});librarySelected.clear();$('#modal').close();await refresh();selected=selected.filter(id=>version(id));await render();notice(`${ids.length} entries deleted.`);});return;
    }
    if(action==='edit-contact')return openContactEditor();
    if(action==='contact-done'){$('#modal').close();renderBuilder();return;}
    if(action==='new-profile'||action==='update-profile'){
      for(const k of Object.keys(resumeContact))resumeContact[k]=document.querySelector('[name="pdf-'+k+'"]').value.trim();
      const current=(S.profiles||[]).find(p=>p.id===activeProfile);
      $('#modal').close();
      modal(head(action==='new-profile'?'Create contact profile':'Update contact profile')+`<form>${field('label','Profile name',action==='new-profile'?resumeContact.name:current.label,'text',true)}${field('name','Full name',resumeContact.name,'text',true)}${field('location','Location',resumeContact.location)}${field('email','Email',resumeContact.email)}${field('phone','Phone number',resumeContact.phone)}${field('linkedin','LinkedIn',resumeContact.linkedin)}${formEnd('Save profile')}</form>`);
      bindForm(async d=>{const result=await api('profile',{...d,...(action==='update-profile'?{id:activeProfile}:{})});activeProfile=result.id;for(const k of Object.keys(resumeContact))resumeContact[k]=d[k];await refresh();$('#modal').close();renderBuilder();notice('Contact profile saved.');});return;
    }
    if(action==='close')return $('#modal').close();
    if(action==='new-bullet')return editBullet();
    if(action==='manage-additional')return manageAdditionalSections();
    if(action==='add-additional')return editAdditionalSection();
    if(action==='rename-additional')return editAdditionalSection(id);
    if(action==='edit-bullet')return editBullet(id);
    if(action==='copy-entry'){
      const entry=version(id);
      if(!entry)throw Error('This entry is no longer available. Refresh the library.');
      try {
        await navigator.clipboard.writeText(entry.bullet);
        return notice('Entry copied to clipboard.');
      } catch {
        modal(head('Copy entry')+`<p>Clipboard access is unavailable. Select the text below and press Ctrl+C (or Command+C).</p><textarea id="copy-entry-text" readonly aria-label="Entry wording">${esc(entry.bullet)}</textarea><div class="form-actions">${button('Done','close')}</div>`);
        $('#copy-entry-text').focus();
        $('#copy-entry-text').select();
        return;
      }
    }
    if(action==='delete-entry'){
      const versions=S.versions.filter(v=>v.accomplishment_id===id);
      const latest=versions.reduce((a,b)=>a.number>b.number?a:b);
      modal(head('Delete entry?')+`<form><p><strong>${esc(entryHeading(latest))}</strong></p><p>Delete this entry and all ${versions.length} saved versions? This cannot be undone. Entries used in saved applications must be removed from those applications first.</p>${formEnd('Delete entry')}</form>`);
      bindForm(async()=>{await api('entry/delete',{id});selected=selected.filter(vid=>!versions.some(v=>v.id===vid));$('#modal').close();await refresh();await render();notice('Entry and its revision history deleted.');});
      return;
    }
    if(action==='clear-filters'){filters={q:'',employer:'',role:'',skill:'',category:''};return renderLibrary();}
    if(action==='preferred'){await api('preferred',{version_id:id});await refresh();await render();return notice('Preferred version updated.');}
    if(action==='restore'){const r=await api('restore',{version_id:id});await refresh();await render();return notice(`Restored as version ${r.number} and marked preferred. Full history preserved.`);}
    if(action==='new-job')return newJob();
    if(action==='edit-job-details'){
      const j=job(id);
      modal(head('Edit job details')+`<form>${field('title','Job title',j.title,'text',true)}${field('department','Department',j.department)}${field('employment_type','Employment type',j.employment_type)}${field('experience_level','Experience level',j.experience_level)}${formEnd('Save details')}`);
      bindForm(async d=>{await api('job',{...j,...d});$('#modal').close();await refresh();await render();notice('Job details saved.');});return;
    }
    if(action==='new-requirement')return editRequirement(undefined,id);
    if(action==='edit-requirement')return editRequirement(id);
    if(action==='delete-requirement'){if(!confirm('Remove this requirement and its manual match corrections?'))return;await api('requirement/delete',{id});await refresh();return render();}
    if(action==='job-match'){currentJob=id;selected=[];editingApp='';appName='';allowDuplicates=false;location.hash='match';return render();}
    if(action==='correct-match')return correction(id,el.dataset.version);
    if(action==='select-version'){
      if(selected.includes(id))return notice('That version is already selected.');
      if(!allowDuplicates&&selected.some(s=>version(s).accomplishment_id===version(id).accomplishment_id))return notice('Another version of this accomplishment is selected. Remove it first, or explicitly allow duplicates.',true);
      selected.push(id);renderBuilder();return loadMatches();
    }
    if(action==='remove-selection'){selected=selected.filter(v=>v!==id);renderBuilder();return loadMatches();}
    if(action==='header-up'||action==='header-down'){
      const groups=selectedGroups(),i=groups.findIndex(group=>group.key===id),next=i+(action==='header-up'?-1:1);
      if(i>=0&&next>=0&&next<groups.length)[groups[i],groups[next]]=[groups[next],groups[i]];
      selected=groups.flatMap(group=>group.ids);return renderBuilder();
    }
    if(action==='up'||action==='down'){
      const groups=selectedGroups(),group=groups.find(item=>item.ids.includes(id));
      if(!group)return;
      const i=group.ids.indexOf(id),next=i+(action==='up'?-1:1);
      if(next>=0&&next<group.ids.length)[group.ids[i],group.ids[next]]=[group.ids[next],group.ids[i]];
      selected=groups.flatMap(item=>item.ids);return renderBuilder();
    }
    if(action==='preview-resume'){
      if(!selected.length)return notice('Select at least one entry first.',true);
      if(!resumeContact.name){openContactEditor();return notice('Enter your full name for the preview.',true);}
      modal(head('Resume preview')+`<form id="margin-form"><label>Resume font<select name="font">${options([['Arial','Arial'],['Calibri','Calibri'],['Times New Roman','Times New Roman']],pdfFont)}</select></label><div class="grid2">${Object.entries(pdfMargins).map(([key,value])=>`<label>${key[0].toUpperCase()+key.slice(1)} margin (cm)<input name="${key}" type="number" min="0" max="5" step="0.05" value="${value}" required></label>`).join('')}</div><p class="tiny muted">Update the preview to apply the font and margins to both the preview and PDF export.</p><div class="form-error" hidden role="alert"></div><div class="form-actions"><button type="submit">Update preview</button></div></form><div id="preview-pages" class="resume-preview">Loading preview…</div><div class="form-actions">${button('Done','close')}</div>`);
      const container=$('#preview-pages');
      const draw=result=>{container.innerHTML=result.pages.map((src,i)=>`<figure><img src="${attr(src)}" alt="Resume page ${i+1}"><figcaption>Page ${i+1} of ${result.pages.length}</figcaption></figure>`).join('');};
      const form=$('#margin-form');
      const update=async (margins,font)=>{
        const submit=form.querySelector('button');submit.disabled=true;
        try{const result=await api('export/preview',{contact:{...resumeContact},version_ids:[...selected],margins,font});pdfMargins=margins;pdfFont=font;draw(result);form.querySelector('.form-error').hidden=true;}
        catch(err){const error=form.querySelector('.form-error');error.textContent=err.message;error.hidden=false;}
        finally{submit.disabled=false;}
      };
      form.onsubmit=e=>{e.preventDefault();const values=Object.fromEntries(new FormData(form));const font=values.font;delete values.font;update(Object.fromEntries(Object.entries(values).map(([key,value])=>[key,Number(value)])),font);};
      await update({...pdfMargins},pdfFont);return;
    }
    if(action==='export-pdf'){
      if(!selected.length)return notice('Select at least one entry first.',true);

      appName=$('#app-name').value.trim();
      if(!resumeContact.name){openContactEditor();document.querySelector('[name="pdf-name"]').focus();return notice('Enter your full name for the PDF header.',true);}
      if(!appName){$('#app-name').focus();return notice('Enter an application name for the PDF filename.',true);}
      el.disabled=true;
      try{
        if(window.pywebview?.api?.save_pdf){const result=await window.pywebview.api.save_pdf({application_name:appName,contact:resumeContact,version_ids:selected,margins:pdfMargins,font:pdfFont});notice(result.saved?'PDF saved.':'PDF export cancelled.');return;}
        const response=await fetch('/api/export/pdf',{method:'POST',headers:{'Content-Type':'application/json','X-Resume-App':'1'},body:JSON.stringify({application_name:appName,contact:resumeContact,version_ids:selected,margins:pdfMargins,font:pdfFont})});
        if(!response.ok){const error=await response.json();throw Error(error.error||'PDF export failed.');}
        const url=URL.createObjectURL(await response.blob());
        const link=document.createElement('a');link.href=url;link.download=(appName.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/g,'')||'Application')+'.pdf';document.body.append(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),60000);
        notice('PDF download started.');
      }finally{el.disabled=false;}
      return;
    }
    if(action==='save-application'){el.disabled=true;try{const a=await api('application',{id:editingApp||undefined,job_id:currentJob,name:appName,version_ids:selected,allow_duplicates:allowDuplicates});editingApp=a.id;await refresh();renderBuilder();notice('Application saved with exact bullet versions.');}finally{el.disabled=false;}return;}
    if(action==='open-application'){editingApp=id;appName=S.applications.find(a=>a.id===id).name;selected=S.selections.filter(s=>s.application_id===id).sort((a,b)=>a.position-b.position).map(s=>s.version_id);allowDuplicates=new Set(selected.map(id=>version(id).accomplishment_id)).size<selected.length;renderBuilder();return loadMatches();}
    if(action==='new-selection'){editingApp='';appName='';selected=[];allowDuplicates=false;renderBuilder();return loadMatches();}
    if(action==='import-backup'){const file=$('#backup-file').files[0];if(!file)throw Error('Choose a JSON backup file first.');if(file.size>20_000_000)throw Error('Backup exceeds the 20 MB limit.');let data;try{data=JSON.parse(await file.text());}catch{throw Error('This file is not valid JSON.');}el.disabled=true;try{const r=await api('import',data);await refresh();await render();notice(`Backup imported: ${r.inserted} records added. Version relationships preserved.`);}finally{el.disabled=false;}return;}
  }catch(err){notice(err.message,true);}
});
window.addEventListener('hashchange',()=>render().catch(e=>notice(e.message,true)));
refresh().then(render).catch(e=>{notice('Could not load the local database: '+e.message,true);$('#content').innerHTML=empty('Unable to connect','Make sure the Python server is running, then reload this page.');});
