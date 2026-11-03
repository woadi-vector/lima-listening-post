let token, state, selectedRecord, selectedSpan, editingClaim, notionPlan;
let previewFile, fileReadVersion=0, reviewFilter='all';
const reviewOpenBuckets=new Map();
function lessonLearning(c){return c.context_category==='class'&&c.kind==='reference'&&!c.review_block_reason&&!c.reference_block_reason&&!c.due_date&&!/\b(assignment|deadline|exam|submit|submission|due|homework)\b/i.test(c.subject+' '+c.value);}
const $ = s => document.querySelector(s);
const el = (tag, text, cls) => { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; };
function notify(text,error=false){const e=$('#notice');e.textContent=text;e.className=error?'error':'';e.hidden=false;}
async function api(path,data){const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Lima-Token':token},body:data===undefined?undefined:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;}
async function busy(button,fn){const changesText=button.tagName==='BUTTON';const old=button.textContent;button.disabled=true;if(changesText)button.textContent='Working…';try{await fn();}catch(e){notify(e.message,true);}finally{button.disabled=false;if(changesText)button.textContent=old;}}
function page(name){if(name==='recordings'){document.querySelectorAll('.page').forEach(e=>e.hidden=e.id!==name);$('#section-label').textContent='RECORDINGS';$('#heading').textContent='From recording to context';$('#subtitle').textContent='Transcribe locally, review, then import.';return;}document.querySelectorAll('.page').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('nav button').forEach(e=>e.classList.toggle('active',e.dataset.page===name));const titles={'day-review':['DAILY REVIEW','Your day, ready for review.','Amend, dismiss, or approve each proposed next step.'],home:['TODAY','A little more clarity.','Your conversations, connected to what matters next.'],sources:['SOURCES','Bring the day together.','Conversations and recordings, ready to make sense of.'],review:['REVIEW','You have the final say.','Keep what matters. Check the evidence. Leave the rest.'],drafts:['NOTES','Ready for your next step.','Review a note, make it yours, then choose where it goes.']};$('#section-label').textContent=titles[name][0];$('#heading').textContent=titles[name][1];$('#subtitle').textContent=titles[name][2];}
async function refresh(){state=await api('/api/state');render();await refreshBackground();if($('#brief-panel').open)renderBrief(await api('/api/brief'));}
function badge(text,warn=false){return el('span',text,'tag'+(warn?' warn':''));}
function workControls(item){
 const details=el('details',undefined,'work-controls');details.append(el('summary',item.state==='done'?'Reopen or update':'Update status'));
 const form=el('form');const label=el('label','Work state');const select=el('select');select.setAttribute('aria-label',`Work state for ${item.subject}`);
 for(const [value,text] of [['planned','Planned'],['in_progress','In progress'],['blocked','Blocked'],['done','Complete']]){const option=el('option',text);option.value=value;option.selected=value===item.state;select.append(option);}label.append(select);
 const reasonLabel=el('label','What changed?');const reason=el('input');reason.required=true;reason.maxLength=2000;reason.placeholder='A short reason, saved as evidence';reasonLabel.append(reason);const save=el('button','Save status');
 form.append(label,reasonLabel,save);form.onsubmit=e=>{e.preventDefault();busy(save,async()=>{await api('/api/work-update',{claim_id:item.id,state:select.value,reason:reason.value});await refresh();notify('Work status updated. Previous evidence and your reason are preserved.');});};details.append(form);return details;
}
function dependencyControls(project){
 const details=el('details',undefined,'dependency-controls');details.append(el('summary','Work dependencies'));details.append(el('p','Choose what must finish before another deliverable can proceed. Your instruction is saved as evidence.','fine'));
 for(const edge of project.dependencies){const row=el('form',undefined,'dependency-row');const blocked=JSON.parse(edge.blocked_key),prerequisite=JSON.parse(edge.prerequisite_key);row.append(el('p',`${blocked.subject} waits for ${prerequisite.subject}`));const reason=el('input');reason.required=true;reason.placeholder='Reason for removing';reason.setAttribute('aria-label',`Reason for removing dependency ${blocked.subject}`);const remove=el('button','Remove dependency','secondary');row.append(reason,remove);row.onsubmit=e=>{e.preventDefault();busy(remove,async()=>{await api('/api/dependency-remove',{dependency_id:edge.id,reason:reason.value});await refresh();notify('Dependency removed. Its history is preserved.');});};details.append(row);}
 const work=project.current.filter(c=>['deliverable','commitment'].includes(c.kind));const open=work.filter(c=>c.state!=='done');if(!open.length||work.length<2){details.append(el('p','Add at least two reviewed work items to set a dependency.','fine'));return details;}
 const form=el('form');const blockedLabel=el('label','This work item');const blocked=el('select');blocked.setAttribute('aria-label',`Dependent work in ${project.name}`);for(const item of open){const option=el('option',`${item.subject} · ${item.kind}`);option.value=item.id;blocked.append(option);}blockedLabel.append(blocked);
 const prerequisiteLabel=el('label','Must wait for');const prerequisite=el('select');prerequisite.setAttribute('aria-label',`Prerequisite in ${project.name}`);function options(){prerequisite.replaceChildren();for(const item of work.filter(c=>c.id!==blocked.value)){const option=el('option',`${item.subject} · ${item.state}`);option.value=item.id;prerequisite.append(option);}}options();blocked.onchange=options;prerequisiteLabel.append(prerequisite);
 const reasonLabel=el('label','Why does it depend on this?');const reason=el('input');reason.required=true;reason.maxLength=2000;reasonLabel.append(reason);const save=el('button','Save dependency');form.append(blockedLabel,prerequisiteLabel,reasonLabel,save);form.onsubmit=e=>{e.preventDefault();busy(save,async()=>{await api('/api/dependencies',{project_id:project.id,blocked_claim_id:blocked.value,prerequisite_claim_id:prerequisite.value,reason:reason.value});await refresh();notify('Dependency saved. Ready work is prioritized within this project.');});};details.append(form);return details;
}
function render(){let demoNotice=$('#demo-notice');if(state.demo_notice&&!demoNotice){demoNotice=el('p',state.demo_notice,'demo-notice');demoNotice.id='demo-notice';document.querySelector('main').prepend(demoNotice);}renderToday();if(typeof renderSubjectFolders==='function')renderSubjectFolders();const projects=state.projects;renderMemoryProjects(projects);const pending=projects.reduce((a,p)=>a+p.pending_count,0);$('#review-count').textContent=pending;$('#metrics').replaceChildren();const work=projects.reduce((n,p)=>n+p.work.length,0);const overdue=projects.reduce((n,p)=>n+p.overdue_count,0);for(const [label,value,note] of [['PROJECTS',projects.length,'Your chosen priorities'],['OPEN DELIVERABLES',work,'Separate from app completion'],['AWAITING REVIEW',pending,'Interpretations to check'],['OVERDUE',overdue,'Verified deadlines only']]){const box=el('div',undefined,'metric');box.append(el('small',label),el('strong',String(value)),el('span',note));$('#metrics').append(box);}$('#empty').hidden=projects.length>0;
document.querySelectorAll('.project-select').forEach(select=>{const previous=select.value;select.replaceChildren();for(const p of projects){const option=el('option',p.name);option.value=p.id;select.append(option);}if(projects.some(p=>p.id===previous))select.value=previous;});
if(typeof renderDayHome==='function')renderDayHome();$('#collisions').replaceChildren();for(const collision of state.collisions){const box=el('div',undefined,'panel');box.append(el('h3',`Shared deadline · ${collision.date}`),el('p',collision.items.map(i=>`${i.project}: ${i.subject}`).join(' / ')));$('#collisions').append(box);}
$('#projects').replaceChildren();for(const project of projects){const card=el('article',undefined,'project');const head=el('div',undefined,'project-head');const title=el('div');title.append(el('h2',project.name));const tags=el('div',undefined,'tags');if(project.work.length)tags.append(badge(`${project.work.length} open`));if(project.pending_count)tags.append(badge(`${project.pending_count} to review`,true));if(project.references?.length)tags.append(badge(`${project.references.length} saved notes`));if(project.conflicts.length)tags.append(badge(`${project.conflicts.length} conflicts`,true));if(project.overdue_count)tags.append(badge(`${project.overdue_count} overdue`,true));title.append(tags);const priority=el('select');priority.setAttribute('aria-label',`Priority for ${project.name}`);for(let i=1;i<=5;i++){const o=el('option',`Priority ${i}${i===1?' · Highest':''}`);o.value=i;o.selected=i===project.priority;priority.append(o);}priority.onchange=()=>busy(priority,async()=>{await api('/api/priority',{project_id:project.id,priority:Number(priority.value)});await refresh();});head.append(title,priority);card.append(head);
for(const item of project.work){const row=el('div',undefined,'work-row');const copy=el('div',undefined,'work-copy');copy.append(el('strong',item.subject),el('p',item.value),el('small',`Owner: ${item.owner}`,'fine'));copy.append(el('p',item.waiting_on.length?`Waiting for ${item.waiting_on.map(p=>p.subject).join(', ')}`:item.ready?'Ready to work on':'Blocked','readiness'+(item.ready?' ready':'')));copy.append(workControls(item));row.append(el('span',undefined,'work-dot'),copy,badge(item.date_basis==='verified'?`Due ${item.due_date}`:item.date_basis==='tentative'?`Tentative ${item.due_date}`:'Date unconfirmed',item.date_basis!=='verified'));card.append(row);}
if(!project.work.length)card.append(el('p',project.pending_count?'Review the imported evidence to establish what needs doing.':'No confirmed tasks yet.'));
for(const q of project.questions)card.append(el('p',q,'question'));
const references=project.references||[];if(references.length){const learning=el('details');learning.append(el('summary',`Reference & learning (${references.length})`),el('p','What the source says — kept separately from your decisions and commitments.','fine'));for(const reference of references){learning.append(el('h3',reference.subject),el('p',reference.value),el('blockquote',reference.quote),el('small',`Source: ${reference.external_id} · attribution: ${reference.attribution}`,'fine'));}card.append(learning);}
if(project.changes?.length)card.append(changeView(project));const completed=project.current.filter(c=>['deliverable','commitment'].includes(c.kind)&&c.state==='done');if(completed.length){const done=el('details');done.append(el('summary',`Completed work (${completed.length})`));for(const item of completed){done.append(el('h3',item.subject),workControls(item));}card.append(done);}
const details=el('details');details.append(el('summary','Project history & settings'));const list=el('ul');for(const c of project.history){const li=el('li',`${c.subject} · ${c.value} [${c.review}]`);li.append(el('blockquote',c.quote));if(c.supersedes)li.append(el('small','Explicitly replaces an earlier claim.'));list.append(li);}details.append(dependencyControls(project),list);const prep=el('div');prep.append(el('h3','Prepared checklist · local draft'));for(const item of project.draft.items)prep.append(el('p',`□ ${item.text}${item.ready?'':' (waiting / blocked)'}`));prep.append(el('p','Nothing has been sent or published.','fine'));details.append(prep);card.append(details);$('#projects').append(card);}
renderReconciliationSummaries();$('#record-list').replaceChildren(el('h2','Imported sources'));for(const record of state.records){const b=el('button',`${record.external_id} · ${record.characters.toLocaleString()} characters · ${new Date(record.created_at).toLocaleString()} · ${record.id.slice(0,6)}`,'record-button');b.onclick=()=>busy(b,()=>openRecord(record.id));$('#record-list').append(b);}if(!state.records.length)$('#record-list').append(el('p','Your imported conversations will appear here.'));
const filter=$('#review-source');filter.replaceChildren();const allOption=el('option',`All sources · ${pending} pending`);allOption.value='all';filter.append(allOption);for(const association of state.associations){const project=projects.find(p=>p.id===association.project_id),record=state.records.find(r=>r.id===association.record_id);if(!project||!record)continue;const n=project.history.filter(c=>c.record_id===record.id&&c.review==='pending').length;const option=el('option',`${project.name} / ${record.external_id} · ${record.characters.toLocaleString()} characters · ${n} pending · ${record.id.slice(0,6)}`);option.value=project.id+':'+record.id;filter.append(option);}filter.value=reviewFilter;if(!filter.value){reviewFilter='all';filter.value='all';}$('#review-scope').textContent=reviewFilter==='all'?`Showing all ${pending} pending suggestions across your workspace.`:'Showing only the selected project and source version. The sidebar count includes all sources.';$('#claims').replaceChildren();let count=0;
const contextLabels={class:'Class & learning',meeting:'Meeting',conversation:'Conversation',personal:'Personal',uncertain:'Context needs sorting'};
const reviewRows=[];for(const project of projects)for(const claim of project.history.filter(c=>c.review==='pending'&&(reviewFilter==='all'||reviewFilter===project.id+':'+c.record_id)))reviewRows.push({project,claim});
reviewRows.sort((a,b)=>{const ra=state.records.find(r=>r.id===a.claim.record_id),rb=state.records.find(r=>r.id===b.claim.record_id);return (ra?.captured_at||ra?.created_at||'').localeCompare(rb?.captured_at||rb?.created_at||'')||a.project.id.localeCompare(b.project.id)||a.claim.record_id.localeCompare(b.claim.record_id)||a.claim.start_offset-b.claim.start_offset;});
const groups=new Map();for(const row of reviewRows){const category=row.claim.context_category||'uncertain';const key=row.project.id+':'+row.claim.record_id+':'+category;if(!groups.has(key))groups.set(key,{key,category,rows:[]});groups.get(key).rows.push(row);}
for(const group of groups.values()){
 const bucket=el('details',undefined,'review-bucket');bucket.open=reviewOpenBuckets.has(group.key)?reviewOpenBuckets.get(group.key):groups.size===1;bucket.addEventListener('toggle',()=>reviewOpenBuckets.set(group.key,bucket.open));const first=group.rows[0];
 const label=contextLabels[group.category]||contextLabels.uncertain;
 const lessonRows=group.category==='class'?group.rows.filter(r=>lessonLearning(r.claim)):[];const lessonIds=new Set(lessonRows.map(r=>r.claim.id));const separateCount=group.rows.length-lessonRows.length;
 bucket.append(el('summary',lessonRows.length?`Daily class lesson · ${lessonRows.length} supporting points${separateCount?` · ${separateCount} to check separately`:''} · ${first.claim.external_id}`:`${label} · ${group.rows.length} to review · ${first.claim.external_id}`));
 bucket.append(el('p',`${first.project.name} · In source order. Context labels are AI suggestions, not verified speaker identity.`,'fine'));
 const learning=group.rows.map(r=>r.claim).filter(c=>c.kind==='reference'&&!c.review_block_reason&&!c.reference_block_reason).slice(0,100);
 if(learning.length&&group.category!=='class'){const controls=el('div',undefined,'learning-group');const confirm=el('input');confirm.type='checkbox';const checkLabel=el('label',undefined,'background-choice');checkLabel.append(confirm,document.createTextNode(` I reviewed these ${learning.length} reference notes and want to keep them as learning.`));const keep=el('button',`Keep ${learning.length} learning notes`,'secondary');keep.disabled=true;confirm.onchange=()=>keep.disabled=!confirm.checked;keep.onclick=()=>busy(keep,async()=>{const result=await api('/api/keep-learning-group',{ids:learning.map(c=>c.id)});await refresh();notify(`${result.kept} learning notes kept. No commitments created.`);});controls.append(checkLabel,keep);bucket.append(controls);}
 let lessonDetails;
 if(lessonRows.length){
  const lesson=el('article',undefined,'class-lesson');const titleLabel=el('label','Daily lesson title');const title=el('input');title.value=`${first.project.name} — Daily class lesson`.slice(0,200);title.maxLength=200;titleLabel.append(title);lesson.append(titleLabel,el('p','One class period, with topics inside. This outline collects transcript interpretations; it is not an independent fact check.','fine'));
  const topics=new Map();for(const {claim} of lessonRows){if(!topics.has(claim.subject))topics.set(claim.subject,[]);topics.get(claim.subject).push(claim);}
  for(const [topic,claims] of topics){lesson.append(el('h3',topic));const list=el('ul');for(const claim of claims)list.append(el('li',claim.value));lesson.append(list);}
  lessonDetails=el('details',undefined,'lesson-evidence');lessonDetails.append(el('summary','Check source passages, remove a point or correct wording'));lesson.append(lessonDetails);
  const confirm=el('input');confirm.type='checkbox';const confirmation=el('label',undefined,'background-choice');confirmation.append(confirm,document.createTextNode(' I reviewed this outline and its evidence as one class period. Keep it as learning.'));const save=el('button','Keep daily lesson');save.disabled=true;confirm.onchange=()=>save.disabled=!confirm.checked;save.onclick=()=>busy(save,async()=>{if(!confirm.checked)throw Error('Review the lesson first.');const result=await api('/api/keep-class-lesson',{ids:[...lessonIds],title:title.value});await refresh();await refreshDrafts();showDraft(result.draft);page('drafts');notify('Daily lesson saved in Notes. You can edit it there. No assignment was accepted and nothing was published.');});lesson.append(confirmation,save);bucket.append(lesson);
 }
 const groupCards=el('div');if(group.category==='class'&&separateCount)groupCards.append(el('h3','Check separately: possible assignments, dates or uncertain evidence'),el('p','These are review candidates, not confirmed obligations. They are excluded from Keep daily lesson.','fine'));bucket.append(groupCards);$('#claims').append(bucket);
 for(const {project,claim} of group.rows){count++;const card=el('article',undefined,'claim');const head=el('div',undefined,'claim-head');head.append(el('h3',claim.subject),badge(claim.attribution,['ambient','uncertain'].includes(claim.attribution)));const evidence=el('details',undefined,'review-details');evidence.append(el('summary','More details & correction'),el('p',`${claim.kind} · ${claim.state} · owner: ${claim.owner} · ${claim.due_date?`${claim.date_basis}: ${claim.due_date}`:'date unknown'}`,'fine'),el('p',`Source: ${claim.external_id} · Interpretation: ${claim.proposer}`,'fine'));card.append(head,el('p',claim.value),el('blockquote',claim.quote),el('small',`${project.name} / ${claim.external_id}`,'fine'));
const replacement=el('select');replacement.setAttribute('aria-label','Earlier claim this replaces');replacement.append(el('option','Keep as a new claim (differences will be flagged)'));replacement.options[0].value='';const replaced=new Set(project.history.filter(c=>c.review==='accepted').map(c=>c.supersedes));for(const old of project.history.filter(c=>c.review==='accepted'&&!replaced.has(c.id)&&c.kind===claim.kind&&c.subject.toLowerCase()===claim.subject.toLowerCase())){const o=el('option',`Replaces: ${old.value}`);o.value=old.id;replacement.append(o);}evidence.append(replacement);
const actions=el('div',undefined,'actions');const moreActions=el('div',undefined,'actions');const openSource=el('button','Open source','secondary');openSource.onclick=()=>busy(openSource,()=>openRecord(claim.record_id,project.id));moreActions.append(openSource);const attributionBlocked=!!claim.review_block_reason||claim.kind!=='reference'&&(['ambient','uncertain'].includes(claim.attribution)||(['deliverable','commitment'].includes(claim.kind)&&claim.owner.toLowerCase()==='unknown')||(claim.owner.toLowerCase()==='user'&&claim.attribution!=='user'));for(const [label,decision] of [['Accept interpretation','accepted'],['Reject','rejected']]){const b=el('button',label,decision==='rejected'?'secondary':undefined);if(decision==='accepted'&&(attributionBlocked||claim.kind==='reference')){b.hidden=true;b.disabled=true;b.title=claim.review_block_reason||'Work needs supported attribution and an identified owner. Keep as reference or correct the evidence.';}b.onclick=()=>busy(b,async()=>{await api('/api/review',{claim_id:claim.id,decision,supersedes:decision==='accepted'?(replacement.value||null):null});notify('Evidence review saved. Project state reconciled.');await refresh();});actions.append(b);}const keep=el('button','Keep as reference','secondary');if(claim.review_block_reason)evidence.append(el('p',claim.review_block_reason,'fine'));if(claim.reference_block_reason){keep.disabled=true;keep.title=claim.reference_block_reason;}keep.onclick=()=>busy(keep,async()=>{await api('/api/keep-reference',{claim_id:claim.id});await refresh();notify('Saved under Reference & learning. No task or personal commitment was created.');});if(attributionBlocked||claim.kind==='reference'){keep.className='';actions.prepend(keep);}else moreActions.append(keep);const edit=el('button','Correct interpretation','secondary');edit.onclick=()=>busy(edit,async()=>{await openRecord(claim.record_id,project.id);const form=$('#claim-form');for(const key of ['kind','subject','value','attribution','owner','state','due_date','date_basis'])form.elements[key].value=claim[key]||'';selectedSpan={start:claim.start_offset,end:claim.end_offset};$('#selected-quote').textContent=claim.quote;editingClaim=claim.id;$('#manual-details').open=true;page('sources');notify('Save your correction as new evidence, then review it. The original pending interpretation will be rejected.');});moreActions.append(edit);evidence.append(moreActions);card.append(actions,evidence);(lessonIds.has(claim.id)?lessonDetails:groupCards).append(card);}}if(!count){const empty=el('div',undefined,'panel');empty.append(el('p',reviewFilter==='all'?'No interpretations awaiting review. Import a conversation to begin.':`No pending suggestions for this source version. ${pending} remain across your workspace.`));if(reviewFilter!=='all'&&pending){const show=el('button','Show pending suggestions from all sources','secondary');show.onclick=()=>{reviewFilter='all';render();};empty.append(show);}$('#claims').append(empty);}}
async function openRecord(id,project){$('#sources').classList.add('source-focus');$('#manual-details').open=false;selectedRecord=await api('/api/record/'+id);selectedSpan=null;editingClaim=null;$('#interpret-provider').value='ollama';$('#interpret-cloud-consent').checked=false;$('#interpret-meta-warning').hidden=true;$('#interpret').textContent='Find updates with local AI';$('#evidence-panel').hidden=false;$('#record-title').textContent=selectedRecord.external_id;const length=[...selectedRecord.content].length;$('#source-metadata').textContent=`${length.toLocaleString()} characters · imported ${new Date(selectedRecord.created_at).toLocaleString()} · version ${selectedRecord.id.slice(0,6)}${length<200?' · This is a short entry; check that it contains the text you intended to import.':''}`;$('#source-content').value=selectedRecord.content;$('#selected-quote').textContent='Select a passage above first.';$('#claim-form').reset();const linked=state.associations.filter(a=>a.record_id===id);$('#source-project').value=project||(linked[0]&&linked[0].project_id)||state.projects[0].id;$('#source-mode').value=selectedRecord.interpretation_modes[$('#source-project').value]||'mixed';page('sources');renderIdeas();renderReconciliation();$('#reconciliation-consent').checked=false;}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>page(b.dataset.page));
$('#import-file').onchange=async e=>{const version=++fileReadVersion;previewFile=null;$('#file-preview-panel').hidden=true;const file=e.target.files[0];if(!file)return;try{if(file.size>1000000)throw Error('Choose a text file smaller than 1 MB.');const decoded=LimaFiles.decode(file.name,await file.arrayBuffer());if(version!==fileReadVersion)return;previewFile=decoded;$('#file-summary').textContent=`${decoded.name} · ${decoded.characters.toLocaleString()} characters · preview only`;$('#file-preview').textContent=decoded.text.slice(0,800)+(decoded.text.length>800?'\n…':'');$('#file-preview-panel').hidden=false;notify('File preview ready. Click Use file text, then Import conversation when you are ready.');}catch(error){if(version===fileReadVersion)notify(error.message,true);}};
$('#use-file').onclick=()=>{if(!previewFile)return;const form=$('#import-form');form.elements.content.value=previewFile.text;form.elements.external_id.value=previewFile.name;form.elements.kind.value=previewFile.kind;notify('File text loaded into the form. Check the project and source type, then click Import conversation.');};
$('#add-project').onclick=()=>{$('#project-form').hidden=!$('#project-form').hidden;if(!$('#project-form').hidden)$('#project-form input').focus();};
$('#project-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const f=e.target;await api('/api/projects',{name:f.elements.name.value,priority:Number(f.elements.priority.value)});f.reset();f.hidden=true;await refresh();notify('Project created. Import a conversation to add context.');});};
$('#import-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const f=e.target;const data=Object.fromEntries(new FormData(f));const project=data.project_id;delete data.project_id;data.project_ids=[project];const result=await api('/api/import',data);let readingError,readingQueued=false;if(!$('#handoff-tools').hidden&&$('#handoff-read').checked){try{await api('/api/analysis',{project_id:project,record_id:result.id,mode:'mixed'});readingQueued=true;}catch(error){readingError=error.message;}}await refresh();await openRecord(result.id,project);notify(readingError?'Chat imported, but reading was not queued: '+readingError:readingQueued?'Chat handoff imported and queued for reading. Interpretations remain pending for review.':'Conversation imported. Select evidence or ask local AI to suggest work updates.',!!readingError);});};
$('#use-selection').onclick=()=>{const area=$('#source-content');const start=[...area.value.slice(0,area.selectionStart)].length;const end=[...area.value.slice(0,area.selectionEnd)].length;if(start===end)return notify('Select a passage in the original source first.',true);selectedSpan={start,end};$('#selected-quote').textContent=area.value.slice(area.selectionStart,area.selectionEnd);};
$('#claim-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{if(!selectedSpan)throw Error('Select supporting evidence first.');const data=Object.fromEntries(new FormData(e.target));data.due_date=data.due_date||null;if(data.kind==='reference')Object.assign(data,{owner:'unknown',state:'planned',due_date:null,date_basis:'unknown'});Object.assign(data,selectedSpan,{project_id:$('#source-project').value,record_id:selectedRecord.id});const result=await api('/api/claims',data);if(editingClaim&&result.id!==editingClaim)await api('/api/review',{claim_id:editingClaim,decision:'rejected'});editingClaim=null;await refresh();page('review');notify('Interpretation saved for review.');});};
$('#associate').onclick=e=>busy(e.target,async()=>{await api('/api/import',{project_ids:[$('#source-project').value],kind:selectedRecord.kind,external_id:selectedRecord.external_id,content:selectedRecord.content,captured_at:selectedRecord.captured_at,source_uri:selectedRecord.source_uri});await refresh();notify('Source linked to the selected project.');});
$('#interpret').onclick=e=>busy(e.target,async()=>{const job=await api('/api/analysis',{project_id:$('#source-project').value,record_id:selectedRecord.id,mode:$('#source-mode').value,provider:$('#interpret-provider').value,cloud_consent:$('#interpret-cloud-consent').checked});await monitorReading(job.id);});
$('#refresh').onclick=e=>busy(e.target,async()=>{await api('/api/reconcile',{});await refresh();notify('Project state reconciled from reviewed evidence.');});
$('#backup').onclick=e=>busy(e.target,async()=>{const response=await fetch('/api/backup',{headers:{'X-Lima-Token':token}});if(!response.ok)throw Error('Could not create a workspace backup.');const url=URL.createObjectURL(await response.blob());const link=el('a');link.href=url;link.download=`lima-workspace-${new Date().toISOString().slice(0,10)}.sqlite3`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Workspace backup downloaded. It includes imported conversation text and reviewed history; keep it private. This is a snapshot, not live sync.');});
$('#demo').onclick=e=>busy(e.target,async()=>{await api('/api/demo',{});await refresh();notify('Synthetic sample loaded. It contains no real project information.');});
(async()=>{try{token=(await (await fetch('/api/session')).json()).token;await refresh();reconnectReading().catch(e=>notify(e.message,true));}catch(e){notify(e.message,true);}})();

$('#source-mode').onchange=e=>busy(e.target,async()=>{const mode=e.target.value;const project=$('#source-project').value;await api('/api/source-mode',{project_id:project,record_id:selectedRecord.id,mode});selectedRecord.interpretation_modes[project]=mode;notify('Source reading mode saved. Existing suggestions remain unchanged.');});
$('#source-project').onchange=()=>{if(selectedRecord)$('#source-mode').value=selectedRecord.interpretation_modes[$('#source-project').value]||'mixed';};

$('#review-source').onchange=e=>{reviewFilter=e.target.value;render();};

$('#back-to-sources').onclick=()=>{$('#sources').classList.remove('source-focus');$('#evidence-panel').hidden=true;};
$('#import-form').addEventListener('invalid',e=>{let node=e.target.parentElement;while(node){if(node.tagName==='DETAILS')node.open=true;node=node.parentElement;}},true);

let readingJob=null;
async function monitorReading(id){
 if(readingJob)return;
 readingJob=id;$('#reading-progress').hidden=false;$('#interpret').disabled=true;$('#stop-reading').disabled=false;
 try{
  while(true){
   const job=await api('/api/analysis/'+id);
   $('#reading-meter').max=job.total||1;$('#reading-meter').value=job.processed;
   $('#reading-label').textContent=job.status==='queued'?'Waiting for local AI…':`Reading ${job.provider==='meta'?'with Meta Muse':'locally'} · ${job.processed} of ${job.total||'…'} sections finished`;
   if(!['queued','running'].includes(job.status)){
    await refresh();
    if(job.result&&job.purpose==='reconciliation'){renderReconciliation();notify(`Muse reconciliation prepared ${job.result.new_count} cited comparisons.${job.result.section_errors.length?' Some sections need a retry.':''} Confirmed work is unchanged.`,job.status!=='completed');}
    else if(job.result&&job.purpose==='ideas'){renderIdeas();notify(`${job.result.new_count} new ideas; ${job.result.pending_source_count} awaiting review.${job.result.section_errors.length?' Some sections could not be validated.':''} No decisions or assignments changed.`,job.status!=='completed');}
    else if(job.result){const r=job.result;reviewFilter=job.project_id+':'+job.record_id;render();if(selectedRecord&&selectedRecord.id===job.record_id)page('review');const outcome=job.status==='completed'?`Read all ${r.sections_total} sections.`:job.status==='cancelled'?`Stopped after ${r.sections_processed} of ${r.sections_total} sections.`:`${r.section_errors.length} sections could not be read; retry to fill the gaps.`;notify(`${outcome} ${r.new_count} new suggestions; ${r.pending_source_count} pending for this source.${r.evidence_scope==='transcript_only'?' AI-written report notes were excluded; only the transcript was analyzed.':''}${r.section_errors.length?' '+r.section_errors.map(e=>`Section ${e.section}: ${e.reason}`).join(' '):''} Earlier suggestions were preserved.`,job.status==='partial');}
    else notify(job.error||'Reading stopped. Saved suggestions remain available.',true);
    break;
   }
   await new Promise(resolve=>setTimeout(resolve,750));
  }
 }finally{readingJob=null;$('#reading-progress').hidden=true;$('#interpret').disabled=false;}
}
$('#stop-reading').onclick=e=>busy(e.target,async()=>{if(readingJob){await api('/api/analysis-cancel',{id:readingJob});notify('Stopping after the current section. Already saved suggestions will remain available.');}});
async function reconnectReading(){const jobs=await api('/api/analysis');const active=jobs.find(j=>['running','queued'].includes(j.status));if(active)await monitorReading(active.id);}

let recordingJob=null, recordingPoll=0, recordingAudioUrl=null;
async function showRecordings(){
 page('recordings');const recordings=await api('/api/recordings');const select=$('#recording-choice');select.replaceChildren();const empty=el('option','Choose a recording…');empty.value='';select.append(empty);for(const r of recordings){const o=el('option',`${r.name} · ${(r.bytes/1000000).toFixed(1)} MB`);o.value=r.path;select.append(o);}
 await listRecordingDrafts();
}
async function listRecordingDrafts(){const jobs=await api('/api/transcriptions');$('#recording-jobs').replaceChildren();if(jobs.length)$('#recording-jobs').append(el('h3','Recording drafts'));for(const job of jobs){const b=el('button',`${job.name} · ${job.status} · ${job.processed}/${job.total||'…'} parts`,'record-button');b.onclick=()=>busy(b,()=>openRecordingDraft(job.id));$('#recording-jobs').append(b);}}
async function openRecordingDraft(id){
 clearTimeout(recordingPoll);recordingJob=id;$('#recording-result').hidden=false;$('#recording-text').value='';if(recordingAudioUrl){URL.revokeObjectURL(recordingAudioUrl);recordingAudioUrl=null;}$('#recording-listen').hidden=true;await updateRecordingDraft(id);
}
async function updateRecordingDraft(id){
 const job=await api('/api/transcriptions/'+id);if(recordingJob!==id)return;
 $('#recording-title').textContent=job.name;$('#recording-status').textContent=job.error||`${job.stage} · ${job.processed} of ${job.total||'…'} parts saved`;
 $('#recording-meter').max=job.total||1;$('#recording-meter').value=job.processed;
 const active=['queued','running'].includes(job.status);$('#recording-stop').hidden=!active;$('#recording-resume').hidden=!['stopped','interrupted','failed'].includes(job.status);$('#recording-import').hidden=job.status!=='completed';$('#recording-download').hidden=job.processed===0;$('#recording-form button').disabled=active;
 if(job.has_preview&&!recordingAudioUrl){const response=await fetch('/api/transcriptions/'+id+'/preview',{headers:{'X-Lima-Token':token}});if(response.ok){const blob=await response.blob();if(recordingJob!==id)return;recordingAudioUrl=URL.createObjectURL(blob);$('#recording-player').src=recordingAudioUrl;$('#recording-listen').hidden=false;}}
 if(!active){const result=await api('/api/transcriptions/'+id+'/text');if(recordingJob!==id)return;$('#recording-text').value=result.text;await listRecordingDrafts();if(job.status==='completed')$('#recording-text-details').open=true;}
 else recordingPoll=setTimeout(()=>updateRecordingDraft(id).catch(e=>notify(e.message,true)),2000);
}
$('#show-recordings').onclick=e=>busy(e.target,showRecordings);
$('#recordings-back').onclick=()=>page('sources');
$('#recording-choice').onchange=()=>{$('#recording-path').value='';};
$('#recording-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const path=$('#recording-path').value.trim()||$('#recording-choice').value;if(!path)throw Error('Choose a recording or paste its full file path.');const job=await api('/api/transcriptions',{path});notify('Local transcription started. This is a draft; nothing has entered project memory.');await openRecordingDraft(job.id);});};
$('#recording-stop').onclick=e=>busy(e.target,async()=>{await api('/api/transcription-stop',{id:recordingJob});notify('Stopping after the current part. Saved progress can be resumed.');});
$('#recording-resume').onclick=e=>busy(e.target,async()=>{await api('/api/transcription-resume',{id:recordingJob});await openRecordingDraft(recordingJob);});
$('#recording-download').onclick=e=>busy(e.target,async()=>{const result=await api('/api/transcriptions/'+recordingJob+'/text');const url=URL.createObjectURL(new Blob([result.text],{type:'text/plain;charset=utf-8'}));const a=el('a');a.href=url;a.download='lima-transcript.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#recording-import').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const project=$('#recording-project').value;if(!project)throw Error('Create a project before importing this transcript.');const result=await api('/api/transcription-import',{id:recordingJob,project_id:project,mode:$('#recording-mode').value,reviewed_text:$('#recording-text').value});await refresh();await openRecord(result.id,project);notify('Reviewed transcript imported as evidence. Ask Lima for suggestions when you are ready.');});};

let beeEnabled=false,beeItem,contextEnabled=false;
async function refreshBee(){
 const data=await api('/api/bee');beeEnabled=!!data.enabled;contextEnabled=!!data.context_enabled;$('#bee-context-toggle').textContent=contextEnabled?'Pause context suggestions':'Enable context suggestions';
 $('#bee-toggle').textContent=beeEnabled?'Pause Bee delivery':'Enable Bee delivery';
 $('#bee-status').textContent=data.error||`${beeEnabled?'Delivery enabled · checks every minute while Lima runs':'Delivery paused'} · ${data.items.filter(i=>!i.imported_record).length} ready · ${data.waiting} waiting${data.last_sync?' · checked '+new Date(data.last_sync).toLocaleString():''}`;
 if(data.unavailable_in_bee)$('#bee-status').textContent+=` · ${data.unavailable_in_bee} unavailable Bee item(s) skipped; saved sources retained`;
 $('#bee-items').replaceChildren();
 for(const item of data.items){const b=el('button',`Bee ${item.conversation_id} · ${item.characters.toLocaleString()} characters${item.imported_record?' · imported':''}${item.context_checked?' · context checked':''}`,'record-button');b.onclick=()=>busy(b,async()=>{const full=await api('/api/bee/'+item.id);beeItem=item.id;$('#bee-reconcile').checked=false;$('#bee-text').textContent=full.content;$('#bee-preview').hidden=false;$('#bee-project').value='';renderBeeRoutes(full.routes);renderBeeContext(full.context_review);renderContextSuggestion(full);renderBeeSpeakers(full);});$('#bee-items').append(b);}
}
$('#bee-panel').ontoggle=()=>{if($('#bee-panel').open)refreshBee().catch(e=>notify(e.message,true));};
$('#bee-toggle').onclick=e=>busy(e.target,async()=>{await api('/api/bee-enable',{enabled:!beeEnabled});await refreshBee();});
$('#bee-refresh').onclick=e=>busy(e.target,refreshBee);
$('#bee-import').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const project=$('#bee-project').value;if(!beeItem||!project)throw Error('Choose an inbox item and project.');const result=await api('/api/bee-import',{item_id:beeItem,project_id:project,mode:$('#bee-mode').value,analyze:$('#bee-analyze').checked,reconcile:$('#bee-reconcile').checked,cloud_consent:$('#bee-reconcile').checked,memory_consent:$('#bee-reconcile').checked});await refresh();await refreshBee();await openRecord(result.record_id,project);if(result.reconciliation_job){notify('Bee transcript imported. Muse reconciliation is queued with your project context; nothing is confirmed or published.');monitorReading(result.reconciliation_job.id).catch(e=>notify(e.message,true));return;}notify(result.analysis_error?'Transcript imported, but reading was not queued: '+result.analysis_error:result.analysis_job?'Transcript imported and queued for local reading. You can keep working; results will appear in Mission Control.':'Bee transcript imported. Speaker identity remains unverified; suggestions require review.',!!result.analysis_error);});};
setInterval(()=>{if(token&&$('#bee-panel').open)refreshBee().catch(()=>{});},15000);

function renderBeeRoutes(routes){
 const box=$('#bee-routes');box.replaceChildren(el('h3','Suggested projects'));
 if(!routes.length)box.append(el('p','No matching phrases found. Choose a project below, or add a matching rule.','fine'));
 if(routes.length>1)box.append(el('p','Several projects match. Choose the context you want to review first.','fine'));
 for(const route of routes){const b=el('button',`Use ${route.name}`,'secondary');b.type='button';b.onclick=()=>{$('#bee-reconcile').checked=false;$('#bee-project').value=route.project_id;$('#bee-mode').value=route.mode;};box.append(b);for(const match of route.matches){box.append(el('p',`Matched phrase: ${match.phrase}`,'fine'),el('blockquote',match.quote));}}
}
async function loadBeeRule(){const rules=await api('/api/bee-rules');const rule=rules.find(r=>r.project_id===$('#bee-rule-project').value);$('#bee-rule-phrases').value=rule?rule.phrases.join('\n'):'';$('#bee-rule-mode').value=rule?rule.mode:'mixed';$('#bee-rule-status').textContent=rule?'Saved matching rule':'No matching rule for this project yet.';}
$('#bee-routing').ontoggle=()=>{if($('#bee-routing').open)loadBeeRule().catch(e=>notify(e.message,true));};
$('#bee-rule-project').onchange=()=>loadBeeRule().catch(e=>notify(e.message,true));
$('#bee-rule-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{await api('/api/bee-rules',{project_id:$('#bee-rule-project').value,phrases:$('#bee-rule-phrases').value.split('\n').map(s=>s.trim()).filter(Boolean),mode:$('#bee-rule-mode').value});await loadBeeRule();if(beeItem){const full=await api('/api/bee/'+beeItem);renderBeeRoutes(full.routes);}notify('Project matching saved. Inbox items stay unassigned until you choose.');});};

let backgroundBusy=false,backgroundSignature,latestBeeReady;
async function refreshBackground(){
 if(backgroundBusy||!token||!state)return; backgroundBusy=true;
 try{
  const [bee,jobs]=await Promise.all([api('/api/bee'),api('/api/analysis')]);
  const active=jobs.filter(j=>['running','queued'].includes(j.status));
  const ready=bee.items.filter(i=>!i.imported_record).length;
  if(latestBeeReady!==ready){latestBeeReady=ready;renderToday();}
  $('#background-title').textContent=`Background work · ${active.length+(bee.context_reading||0)} reading · ${ready} Bee ready`;
  $('#background-summary').textContent=`${ready} Bee conversations awaiting a project. ${active.length} project sources queued or reading. ${bee.context_reading||0} Bee context reads; ${bee.context_ready||0} context results. Suggestions need your review.${bee.error?' Bee delivery needs attention.':''}`;
  const box=$('#background-jobs');box.replaceChildren();
  if(ready||bee.error||bee.context_reading||bee.context_ready){const open=el('button','Open Bee inbox','secondary');open.onclick=()=>{page('sources');$('#bee-panel').open=true;refreshBee().catch(e=>notify(e.message,true));};box.append(open);}
  for(const job of [...jobs].reverse().slice(0,8)){
   const record=state.records.find(r=>r.id===job.record_id),project=state.projects.find(p=>p.id===job.project_id);
   if(!record||!project)continue;
   const row=el('div');const pending=project.history.filter(c=>c.record_id===job.record_id&&c.review==='pending').length;
   const outcome=job.status==='completed'?'Read complete':job.status==='partial'?'Partially read — retry needed':job.status==='failed'?'Reading failed':job.status==='cancelled'?'Reading stopped':job.status==='queued'?'Queued':`Reading ${job.processed} of ${job.total||'…'} sections`;
   row.append(el('p',`${project.name} / ${record.external_id} · ${outcome}${job.restarted?' · resumed after restart':''} · ${pending} pending`));
   const open=el('button',pending?'Review suggestions':'Open source','secondary');open.onclick=()=>busy(open,async()=>{if(pending){reviewFilter=project.id+':'+record.id;render();page('review');}else await openRecord(record.id,project.id);});row.append(open);
   if(['partial','failed','cancelled'].includes(job.status)){const retry=el('button','Retry reading','secondary');retry.onclick=()=>busy(retry,async()=>{if(['ideas','reconciliation'].includes(job.purpose)){await openRecord(record.id,project.id);if(job.purpose==='reconciliation')reconciliationPanel.open=true;else $('#ideas-panel').open=true;notify('Review sharing consent and rerun this reading from the source.');return;}await api('/api/analysis',{project_id:project.id,record_id:record.id,mode:job.mode});await refreshBackground();notify('Reading queued. Earlier suggestions are preserved.');});row.append(retry);}
   box.append(row);
  }
  const signature=jobs.map(j=>j.id+':'+j.status).join('|');
  if(backgroundSignature!==undefined&&backgroundSignature!==signature){state=await api('/api/state');render();}
  backgroundSignature=signature;
 }finally{backgroundBusy=false;}
}
setInterval(()=>{if(token&&!$('#home').hidden)refreshBackground().catch(()=>{});},5000);

let savedBrief;
function chicagoDay(){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const value=k=>parts.find(p=>p.type===k).value;return `${value('year')}-${value('month')}-${value('day')}`;}
function renderBrief(brief){
 savedBrief=brief;$('#brief-text').hidden=!brief;$('#download-brief').hidden=!brief;$('#brief-evidence').hidden=!brief;
 if(!brief){$('#brief-status').textContent='No saved brief yet.';return;}
 $('#brief-status').textContent=`Saved for ${brief.as_of}${brief.stale||brief.as_of!==chicagoDay()?' · Workspace or date changed — prepare a fresh brief.':' · Based on reviewed evidence.'} Nothing has been sent or published.`;
 $('#brief-text').textContent=brief.text;const box=$('#brief-sources');box.replaceChildren();
 const seen=new Set();for(const project of brief.projects){for(const claim of [...project.work,...project.decisions,...project.completed,...project.references,...project.conflicts.flatMap(c=>c.evidence)]){const key=project.id+':'+claim.record_id;if(seen.has(key))continue;seen.add(key);const b=el('button',`${project.name} / ${claim.external_id}`,'record-button');b.onclick=()=>busy(b,()=>openRecord(claim.record_id,project.id));box.append(b);}}
}
$('#brief-panel').ontoggle=()=>{if($('#brief-panel').open){api('/api/brief').then(renderBrief).catch(e=>notify(e.message,true));loadNightly().catch(e=>notify(e.message,true));}};
$('#prepare-brief').onclick=e=>busy(e.target,async()=>{renderBrief(await api('/api/brief',{as_of:chicagoDay()}));notify('Daily brief prepared from reviewed state. Pending interpretations remain separate.');});
$('#download-brief').onclick=()=>{if(!savedBrief)return;const url=URL.createObjectURL(new Blob([savedBrief.text],{type:'text/plain;charset=utf-8'}));const a=el('a');a.href=url;a.download=`lima-brief-${savedBrief.as_of}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

function showNightly(schedule){
 $('#nightly-enabled').checked=!!schedule.enabled;$('#nightly-time').value=schedule.at_time;$('#nightly-drafts').checked=!!schedule.prepare_drafts;
 const last=schedule.last_run;
 $('#nightly-status').textContent=`${schedule.enabled?'Enabled':'Paused'} · ${schedule.at_time} Central. ${last?last.status==='prepared'?'Last prepared: '+last.day:last.status==='failed'?last.error:'Preparing the current brief…':'No nightly brief prepared yet.'}`;
}
async function loadNightly(){showNightly(await api('/api/brief-schedule'));}
$('#nightly-options').ontoggle=()=>{if($('#nightly-options').open)loadNightly().catch(e=>notify(e.message,true));};
$('#nightly-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{showNightly(await api('/api/brief-schedule',{enabled:$('#nightly-enabled').checked,at_time:$('#nightly-time').value,prepare_drafts:$('#nightly-drafts').checked}));notify('Nightly schedule saved. Lima prepares locally while your computer is awake and the app is running.');});};

function renderBeeContext(context){$('#bee-participation').value=context?.participation||'uncertain';$('#bee-relevance').value=context?.relevance||'uncertain';$('#bee-context-notes').value=context?.notes||'';$('#bee-context-status').textContent=context?'Your context check is saved. Earlier checks are retained.':'Not checked yet. Participation and relevance remain unverified.';}
$('#bee-context-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{if(!beeItem)throw Error('Choose a Bee conversation first.');await api('/api/bee-context',{item_id:beeItem,participation:$('#bee-participation').value,relevance:$('#bee-relevance').value,notes:$('#bee-context-notes').value});const item=await api('/api/bee/'+beeItem);renderBeeContext(item.context_review);await refreshBee();notify('Context check saved for testing. No assignments or speaker identity were inferred.');});};

function renderBeeSpeakers(item){const select=$('#bee-wearer');select.replaceChildren();const unknown=el('option','Unknown — do not infer my identity');unknown.value='';select.append(unknown);for(const speaker of item.speakers){const o=el('option',speaker);o.value=speaker;select.append(o);}select.value=item.wearer_speaker||'';}
function renderContextSuggestion(item){
 const suggestion=item.context_suggestion,box=$('#bee-suggestion-evidence');box.replaceChildren();
 $('#bee-context-retry').disabled=!!suggestion&&['queued','running'].includes(suggestion.status);
 $('#bee-context-difference').textContent='';
 if(!suggestion){$('#bee-suggestion-status').textContent=contextEnabled?'Waiting for local context reading.':'Automatic context suggestions are paused.';$('#bee-suggestion-identity').textContent='Your assessment below is kept separately.';return;}
 const label={work:'ongoing work',reference:'learning / reference',personal:'personal',unrelated:'unrelated background',mixed:'mixed context',uncertain:'uncertain'};
 $('#bee-suggestion-status').textContent=['queued','running'].includes(suggestion.status)?`Reading context · ${suggestion.processed} of ${suggestion.total||'…'} sections`:`Suggested relevance: ${label[suggestion.relevance]}. Participation: ${suggestion.participation}.${suggestion.incomplete?' Incomplete read — retry to fill the gaps.':''}`;
 $('#bee-suggestion-identity').textContent=suggestion.identity_basis+' Suggestions do not change project state.';
 for(const section of suggestion.sections){if(section.error){box.append(el('p',section.error,'fine'));continue;}box.append(el('p',`Section suggestion: ${label[section.relevance]} · ${section.explanation}`,'fine'));for(const e of section.evidence)box.append(el('blockquote',e.quote));}
 const check=item.context_review;if(check&&['completed','partial'].includes(suggestion.status)&&(check.relevance!==suggestion.relevance||check.participation!==suggestion.participation))$('#bee-context-difference').textContent='This suggestion differs from your saved assessment. Your assessment has not been changed.';
}
$('#bee-context-toggle').onclick=async e=>{await busy(e.target,async()=>{await api('/api/bee-context-enable',{enabled:!contextEnabled});await refreshBee();notify(contextEnabled?'Automatic local context reading enabled for existing and incoming Bee transcripts.':'Context reading pauses after the current section.');});e.target.textContent=contextEnabled?'Pause context suggestions':'Enable context suggestions';};
$('#bee-context-retry').onclick=e=>busy(e.target,async()=>{if(!beeItem)return;await api('/api/bee-context-retry',{item_id:beeItem});renderContextSuggestion(await api('/api/bee/'+beeItem));notify(contextEnabled?'Context reading queued.':'Context reading queued; enable context suggestions to begin.');});
$('#bee-speaker-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{await api('/api/bee-speaker',{item_id:beeItem,speaker:$('#bee-wearer').value||null});renderContextSuggestion(await api('/api/bee/'+beeItem));notify('Speaker confirmation saved for this transcript only. No claims or assignments changed.');});};
setInterval(()=>{if(token&&beeItem&&!$('#sources').hidden&&!$('#bee-preview').hidden)api('/api/bee/'+beeItem).then(renderContextSuggestion).catch(()=>{});},5000);

let currentDraft;
async function refreshDrafts(){const [drafts,batch]=await Promise.all([api('/api/drafts'),api('/api/draft-batch')]);showDraftBatch(batch);const box=$('#draft-list');box.replaceChildren();if(!drafts.length)box.append(el('p','No drafts prepared yet. Choose a project with reviewed evidence.'));for(const d of drafts){const b=el('button',undefined,'record-button draft-row');b.append(el('strong',d.subject),el('span',`${d.as_of} · ${d.stale?'Needs a fresh review':d.status==='prepared'?'Ready to review':d.status==='approved'?'Marked ready':'Dismissed'}`));b.onclick=()=>busy(b,async()=>showDraft(await api('/api/drafts/'+d.id)));box.append(b);}}
function showDraft(d){currentDraft=d;$('#draft-editor').hidden=false;$('#draft-subject').value=d.subject;$('#draft-body').value=d.body;$('#draft-status').textContent=`${d.status.toUpperCase()} · prepared for ${d.as_of}${d.stale?' · Project evidence changed. Prepare a fresh draft before approval.':''}. Local approval does not publish. Notion delivery uses a separate confirmation.`;$('#draft-approve').disabled=d.stale||d.status!=='prepared';$('#draft-dismiss').disabled=d.status!=='prepared';const box=$('#draft-evidence');box.replaceChildren();for(const claim of d.evidence){box.append(el('p',claim.subject),el('blockquote',claim.quote));const b=el('button',`Open ${claim.external_id}`,'secondary');b.onclick=()=>busy(b,()=>openRecord(claim.record_id,d.project_id));box.append(b);}}
function unchangedDraft(){if(!currentDraft)throw Error('Open a draft first.');if($('#draft-subject').value!==currentDraft.subject||$('#draft-body').value!==currentDraft.body)throw Error('Save your edits before reviewing or downloading this version.');}
document.querySelector('nav button[data-page="drafts"]').addEventListener('click',()=>refreshDrafts().catch(e=>notify(e.message,true)));
$('#draft-prepare').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const d=await api('/api/drafts',{project_id:$('#draft-project').value,kind:$('#draft-kind').value,as_of:chicagoDay()});showDraft(d);await refreshDrafts();notify('Local draft prepared from reviewed evidence. No recipient was selected and nothing was sent.');});};
$('#draft-edit').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{if(!currentDraft)return;showDraft(await api('/api/draft-edit',{draft_id:currentDraft.id,version_id:currentDraft.version_id,subject:$('#draft-subject').value,body:$('#draft-body').value}));await refreshDrafts();notify('Draft edits saved. Changed text needs a new review.');});};
for(const [id,decision] of [['draft-approve','approved'],['draft-dismiss','dismissed']])$("#"+id).onclick=async e=>{await busy(e.target,async()=>{unchangedDraft();showDraft(await api('/api/draft-review',{draft_id:currentDraft.id,version_id:currentDraft.version_id,decision}));await refreshDrafts();notify(decision==='approved'?'Local draft approved. Nothing has been sent or published.':'Draft dismissed. Its history is retained.');});if(currentDraft)showDraft(currentDraft);};
$('#draft-download').onclick=e=>busy(e.target,async()=>{unchangedDraft();const url=URL.createObjectURL(new Blob([`Subject: ${currentDraft.subject}\nStatus: ${currentDraft.status} (local only)\n\n${currentDraft.body}`],{type:'text/plain;charset=utf-8'}));const a=el('a');a.href=url;a.download=`lima-${currentDraft.kind}-${currentDraft.as_of}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});

function showDraftBatch(batch){$('#draft-batch-status').textContent=batch?`Latest preparation (${batch.as_of}): drafts — ${batch.created} new, ${batch.retained} retained; projects skipped — ${batch.skipped.length} (no applicable reviewed evidence). Nothing was sent or published.`:'';}
$('#draft-prepare-all').onclick=e=>busy(e.target,async()=>{const result=await api('/api/draft-batch',{as_of:chicagoDay()});await refreshDrafts();showDraftBatch(result);notify('Reviewed-project drafts are ready locally. Existing edits and approvals were preserved.');});

function renderMemoryProjects(projects){const select=$('#memory-project'),previous=select.value;select.replaceChildren();const all=el('option','All projects');all.value='';select.append(all);for(const p of projects){const option=el('option',p.name);option.value=p.id;select.append(option);}if(projects.some(p=>p.id===previous))select.value=previous;}
$('#memory-search-form').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const data=await api('/api/memory-search',{query:$('#memory-query').value,project_id:$('#memory-project').value||null});$('#memory-results-panel').hidden=false;$('#memory-search-status').textContent=`${data.total} matches${data.more?'; showing the first '+data.results.length:''}. ${data.method} ${data.scope}`;const box=$('#memory-results');box.replaceChildren();for(const hit of data.results){const row=el('article',undefined,'claim');row.append(el('h3',hit.type==='claim'?hit.subject:hit.external_id),badge(hit.type==='claim'?`${hit.status} · ${hit.kind}`:hit.status,hit.status!=='current'));if(hit.type==='claim')row.append(el('p',hit.value),el('small',hit.project,'fine'));else row.append(el('small',hit.projects.map(p=>p.name).join(' / '),'fine'));row.append(el('blockquote',hit.quote));if(hit.title_match)row.append(el('p','Source-name match; excerpt shown from the beginning.','fine'));const links=hit.type==='source'?hit.projects:[{id:hit.project_id,name:hit.project}];for(const project of links){const open=el('button',`Open source · ${project.name}`,'secondary');open.onclick=()=>busy(open,()=>openRecord(hit.record_id,project.id));row.append(open);}if(hit.status==='pending'){const review=el('button','Review this source','secondary');review.onclick=()=>{reviewFilter=hit.project_id+':'+hit.record_id;render();page('review');};row.append(review);}box.append(row);}if(!data.results.length)box.append(el('p','No literal matches. Try a distinctive phrase or a person’s name.'));});};
$('#memory-close').onclick=()=>{$('#memory-results-panel').hidden=true;};
$('#chat-handoff').onclick=()=>{page('sources');$('#sources').classList.remove('source-focus');$('#evidence-panel').hidden=true;$('#handoff-tools').hidden=false;$('#handoff-read').checked=true;const form=$('#import-form');form.elements.kind.value='chatgpt';form.querySelector('details.advanced').open=true;$('#paste-details').open=true;if(!form.elements.external_id.value)form.elements.external_id.value='Chat handoff · '+chicagoDay();form.elements.content.focus();notify('Choose a project and source type, then paste the conversation or handoff. Import is explicit; nothing is approved automatically.');};

$('#interpret-provider').onchange=e=>{const meta=e.target.value==='meta';$('#interpret-meta-warning').hidden=!meta;$('#interpret-cloud-consent').checked=false;$('#interpret').textContent=meta?'Find updates with Meta Muse':'Find updates with local AI';};

const ideaPanel=document.createElement('details');ideaPanel.id='ideas-panel';
ideaPanel.innerHTML='<summary>Explore an emerging idea</summary><p>Find tentative interests worth exploring. These stay separate from decisions and assignments.</p><label><input id="ideas-consent" type="checkbox"> Share this source, project name and up to 20 reviewed project memories with Meta Muse for this reading</label><button id="find-ideas" class="secondary">Find ideas with Muse</button><div id="idea-results"></div>';
$('#interpret').parentElement.after(ideaPanel);
function renderIdeas(){
 $('#ideas-consent').checked=false;
 const rows=(state.ideas||[]).filter(i=>selectedRecord&&i.record_id===selectedRecord.id&&i.project_id===$('#source-project').value&&i.review!=='dismissed');
 $('#idea-results').replaceChildren();
 for(const idea of rows){
  const block=document.createElement('article');
  const heading=document.createElement('h3');heading.textContent=idea.title+' · '+(idea.review==='kept'?'kept idea':'tentative');block.append(heading);
  for(const text of [idea.description,'Possible relevance: '+idea.why_relevant,'Optional next step: '+idea.next_step]){const p=document.createElement('p');p.textContent=text;block.append(p);}
  const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Evidence and connected memory';detail.append(summary);
  const quote=document.createElement('blockquote');quote.textContent=idea.quote;detail.append(quote);
  const note=document.createElement('p');note.textContent='Speaker identity unconfirmed. Connections reflect reviewed memory at the time of reading.';detail.append(note);
  for(const memory of idea.related_memory){const p=document.createElement('p');p.textContent=memory.subject+': '+memory.value;detail.append(p);}block.append(detail);
  for(const [label,decision] of [['Keep idea','kept'],['Dismiss','dismissed']]){const button=document.createElement('button');button.className='secondary';button.textContent=label;button.disabled=idea.review===decision;button.onclick=()=>busy(button,async()=>{await api('/api/idea-review',{id:idea.id,decision});await refresh();renderIdeas();});block.append(button);}
  $('#idea-results').append(block);
 }
}
$('#find-ideas').onclick=e=>busy(e.target,async()=>{
 if(!$('#ideas-consent').checked)throw new Error('Confirm sharing this source and reviewed project context first.');
 const job=await api('/api/analysis',{project_id:$('#source-project').value,record_id:selectedRecord.id,mode:$('#source-mode').value,provider:'meta',cloud_consent:true,memory_consent:true,purpose:'ideas'});
 await monitorReading(job.id);ideaPanel.open=true;
});
$('#source-project').addEventListener('change',renderIdeas);

function changeView(project){
 const changes=project.changes||[];
 const panel=el('details');panel.append(el('summary',`What changed? (${changes.length})`));
 panel.append(el('p','Reviewed revisions show an explicit replacement. Proposed comparisons leave your current position unchanged. Reference learning and emerging ideas are separate.','fine'));
 if(!changes.length)panel.append(el('p','No proposed work or reviewed revisions yet.'));
 const list=el('div');let shown=0;
 function position(item){
  const box=el('div');box.append(el('p',item.value),el('small',`${item.kind} · ${item.state} · attribution: ${item.attribution} · owner: ${item.owner} · ${item.due_date?item.date_basis+' date: '+item.due_date:'date unconfirmed'}`,'fine'));
  const evidence=el('details');evidence.append(el('summary','Supporting passage'),el('blockquote',item.quote),el('small',item.external_id,'fine'));
  const open=el('button','Open source','secondary');open.onclick=()=>busy(open,()=>openRecord(item.record_id,project.id));evidence.append(open);box.append(evidence);return box;
 }
 function more(){
  for(const row of changes.slice(shown,shown+5)){
   const card=el('article',undefined,'change-item');
   const label=row.status==='reviewed_revision'?'Reviewed revision':row.status==='proposed_comparison'?'Proposed comparison · awaiting review':'New proposal · awaiting review';
   const detail=el('details');detail.append(el('summary',row.after.subject+' · '+label));
   detail.append(el('p',(row.status==='reviewed_revision'?'Reviewed ':'Proposed ')+new Date(row.at).toLocaleString(),'fine'));
   detail.append(el('strong',row.status==='reviewed_revision'?'Previous position':'Current reviewed position'));
   if(!row.before.length)detail.append(el('p','No reviewed position on this topic.'));
   if(row.before.length>1)detail.append(el('p','Multiple reviewed positions conflict; no single position is established.','fine'));
   for(const previous of row.before)detail.append(position(previous));
   detail.append(el('strong',row.status==='reviewed_revision'?'Reviewed replacement':'Proposed interpretation'),position(row.after));
   if(row.status==='reviewed_revision')detail.append(el('p','This was explicitly reviewed as a replacement. Later revisions may also appear here.','fine'));
   else{detail.append(el('p','Matching topics do not establish agreement or a replacement.','fine'));if(row.after.review_block_reason||['ambient','uncertain'].includes(row.after.attribution))detail.append(el('p',row.after.review_block_reason||'Ambient or uncertain speech cannot establish project work.','fine'));const review=el('button','Review suggestion','secondary');review.onclick=()=>{reviewFilter=project.id+':'+row.after.record_id;render();page('review');};detail.append(review);}
   card.append(detail);list.append(card);
  }
  shown+=5;load.hidden=shown>=changes.length;
 }
 const load=el('button','Show more changes','secondary');load.onclick=more;more();panel.append(list,load);return panel;
}

const notionOptions=el('details',undefined,'panel');
notionOptions.innerHTML='<summary>Notion daily review</summary><p>One new dated page each day. Approved notes are appended as snapshots; your edits stay intact. Instructions in a note do not send email or execute other actions.</p><form id="notion-setup"><label>Daily review parent page<input id="notion-parent" required placeholder="https://www.notion.so/your-page"></label><label>Dedicated Lima integration secret<input id="notion-secret" type="password" autocomplete="off" placeholder="Paste locally; never include in a chat"></label><p class="fine">On Windows, the secret is protected for your Windows account, outside database backups. Other platforms use LIMA_NOTION_TOKEN. Stream Cutter credentials are never used.</p><button class="secondary">Connect Lima to Notion</button></form><p id="notion-connection" role="status"></p>';
$('#drafts').prepend(notionOptions);
const notionDelivery=el('details');
notionDelivery.innerHTML='<summary>Send this note to the daily Notion page</summary><p>Approve the local draft first. Preview the exact content and dated destination before publishing.</p><button id="notion-preview" class="secondary">Preview Notion note</button><div id="notion-plan" hidden><p id="notion-destination"></p><pre id="notion-content" class="brief-text"></pre><label><input id="notion-consent" type="checkbox"> Publish exactly this note to the displayed Notion destination</label><button id="notion-publish">Publish approved note</button><button id="notion-check" class="secondary">Check delivery</button><p id="notion-result" role="status"></p><a id="notion-open" target="_blank" rel="noopener noreferrer" hidden>Open daily review in Notion</a></div>';
$('#draft-editor').append(notionDelivery);
async function refreshNotion(){const connection=await api('/api/notion');$('#notion-parent').value=connection.parent_id||'';$('#notion-connection').textContent=connection.configured?'Destination saved. Each publishing preview verifies page access again.':'Connect a dedicated Lima integration to your review parent page.';}
document.querySelector('nav button[data-page="drafts"]').addEventListener('click',()=>{notionPlan=null;$('#notion-plan').hidden=true;refreshNotion().catch(e=>notify(e.message,true));});
$('#notion-setup').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{const secret=$('#notion-secret').value;$('#notion-secret').value='';const result=await api('/api/notion-setup',{parent:$('#notion-parent').value,secret});$('#notion-connection').textContent=`Connected ${result.connection} to ${result.parent_title}.`;notify('Dedicated Notion connection saved. No notes were published.');});};
$('#notion-preview').onclick=e=>busy(e.target,async()=>{unchangedDraft();notionPlan=await api('/api/notion-preview',{draft_id:currentDraft.id,version_id:currentDraft.version_id});$('#notion-plan').hidden=false;$('#notion-consent').checked=false;$('#notion-destination').textContent=notionPlan.parent_title+' → '+notionPlan.daily_title+' · parent '+notionPlan.parent_id;$('#notion-content').textContent=notionPlan.subject+'\n\n'+notionPlan.body;$('#notion-result').textContent='Preview only. Expires in 30 minutes.';$('#notion-open').hidden=true;});
function notionResult(result){notionPlan=result;$('#notion-result').textContent=result.status==='completed'?'Delivery verified. No email or other action was executed.':result.status;$('#notion-open').hidden=!result.url;if(result.url)$('#notion-open').href=result.url;$('#notion-consent').checked=false;}
$('#notion-publish').onclick=e=>busy(e.target,async()=>{unchangedDraft();if(!notionPlan||!$('#notion-consent').checked)throw Error('Review the exact note and destination, then check the publishing confirmation.');if(currentDraft.id!==notionPlan.draft_id||currentDraft.version_id!==notionPlan.version_id)throw Error('The selected draft changed. Prepare a fresh preview.');try{notionResult(await api('/api/notion-publish',{id:notionPlan.id,confirmed:true}));}catch(error){$('#notion-result').textContent=error.message;throw error;}});
$('#notion-check').onclick=e=>busy(e.target,async()=>{if(!notionPlan)throw Error('Prepare a preview first.');notionResult(await api('/api/notion-check',{id:notionPlan.id}));});

const todayFlow=el('div',undefined,'today-flow');$('#home').prepend(todayFlow);
const homeTools=el('div',undefined,'home-tools');todayFlow.after(homeTools);
const memoryDisclosure=el('details');memoryDisclosure.append(el('summary','Find something in your project memory'),$('#memory-search-form'));homeTools.append(memoryDisclosure,$('#brief-panel'),$('#background-panel'));
function renderToday(){
 if(!state)return;
 const pending=state.projects.reduce((sum,p)=>sum+p.pending_count,0);
 todayFlow.replaceChildren();
 const steps=[['01 · Gather',latestBeeReady?'Your day is arriving':'Bring in a conversation',latestBeeReady?`${latestBeeReady} Bee conversations ready to sort`:`${state.records.length} sources in your workspace`,latestBeeReady?'Open inbox':'Add a conversation',()=>{page('sources');$('#back-to-sources').click();if(latestBeeReady)$('#bee-panel').open=true;}],
 ['02 · Make sense',pending?(pending===1?'One thing to review':'A few things to review'):'Your review queue is clear',pending?`${pending} suggestion${pending===1?'':'s'} waiting for your judgment`:'No suggestions waiting for review',pending?'Review suggestions':'View review',()=>page('review')],
 ['03 · Move forward','Put the useful parts to work','Reviewed notes and follow-ups, in your words','Prepare a note',()=>document.querySelector('nav button[data-page="drafts"]').click()]];
 for(const [eyebrow,title,description,label,action] of steps){const box=el('section',undefined,'flow-step');box.append(el('small',eyebrow),el('h2',title),el('p',description));const button=el('button',label);button.onclick=action;box.append(button);todayFlow.append(box);}
}
page('home');

notionOptions.classList.remove('panel');
const draftActivity=el('details');draftActivity.append(el('summary','Preparation details'),$('#draft-batch-status'));
$('#drafts').append(draftActivity,notionOptions);
$('#draft-prepare-all').textContent='Prepare all';
$('#draft-approve').textContent='Mark ready';
$('#draft-kind').options[0].textContent='Follow-up note';
$('#draft-kind').options[1].textContent='Project notes & learning';

const conversationLabel=$('#import-form').elements.external_id.closest('label');
conversationLabel.firstChild.textContent='Conversation name';
$('#import-form').elements.external_id.placeholder='For example: Tuesday class';
$('#import-form').querySelector('details.advanced').before(conversationLabel);

const reconciliationPanel=el('details');
reconciliationPanel.innerHTML='<summary>Compare with this project</summary><p>Ask Muse what may have changed, what needs clarification, and what follow-up could help. Results remain proposals.</p><label class="background-choice"><input id="reconciliation-consent" type="checkbox"> Send this source, project name and up to 20 reviewed memories to Meta Muse for this reconciliation</label><button id="reconcile-source" class="secondary">Reconcile with Muse</button><div id="reconciliation-results"></div>';
$('#ideas-panel').before(reconciliationPanel);
function reconciliationCard(report){
 const box=el('div');
 box.append(el('p',report.stale?'Project context changed. Read this as a historical proposal and rerun before preparing a note.':report.complete?'Proposed comparisons. Your confirmed work is unchanged.':'Partial reading. Complete the missing sections before preparing a note.','fine'));
 if(report.memory_limited)box.append(el('p','Context was limited to the 20 most recently reviewed memories.','fine'));
 const seen=new Set();
 for(const section of report.sections){
  if(section.error)box.append(el('p',section.error,'fine'));
  for(const item of section.items){
   if(seen.has(item.id))continue;seen.add(item.id);
   const card=el('article',undefined,'reconciliation-item');card.append(el('h3',item.title),badge(item.kind.replaceAll('_',' ')),el('p',item.interpretation),el('blockquote',item.quote));
   for(const memory of report.context.filter(c=>item.memory_ids.includes(c.id))){card.append(el('p',(memory.conflicted?'Conflicting reviewed context: ':'Reviewed context: ')+memory.value,'fine'));const claim=state.projects.find(p=>p.id===report.project_id)?.history.find(c=>c.id===memory.id);if(claim){const details=el('details');details.append(el('summary','Earlier evidence'),el('blockquote',claim.quote));const open=el('button','Open earlier source','secondary');open.onclick=()=>busy(open,()=>openRecord(claim.record_id,report.project_id));details.append(open);card.append(details);}}
   if(item.question)card.append(el('p','Question: '+item.question));if(item.follow_up)card.append(el('p','Proposed next step: '+item.follow_up));box.append(card);
  }
 }
 if(!seen.size)box.append(el('p','No supported comparisons found in the completed sections.'));
 const note=el('button','Prepare proposed follow-up note','secondary');note.disabled=report.stale||!report.complete||!seen.size;note.onclick=()=>busy(note,async()=>{const draft=await api('/api/reconciliation-note',{id:report.id});page('drafts');await refreshDrafts();showDraft(draft);notify('Proposed follow-up prepared. Review and edit before marking ready; Notion publishing still needs separate confirmation.');});box.append(note);return box;
}
function renderReconciliation(){
 if(!selectedRecord)return;
 const report=(state.reconciliations||[]).find(r=>r.project_id===$('#source-project').value&&r.record_id===selectedRecord.id);
 $('#reconciliation-results').replaceChildren();if(report)$('#reconciliation-results').append(reconciliationCard(report));
}
function renderReconciliationSummaries(){
 document.querySelectorAll('.reconciliation-summary').forEach(e=>e.remove());
 for(const [index,project] of state.projects.entries()){
  const latest=new Map();for(const report of (state.reconciliations||[]).filter(r=>r.project_id===project.id))if(!latest.has(report.record_id))latest.set(report.record_id,report);const reports=[...latest.values()];
  if(!reports.length)continue;
  const details=el('details',undefined,'reconciliation-summary');details.append(el('summary',`Muse comparisons (${reports.length})`));
  for(const report of reports){const source=state.records.find(r=>r.id===report.record_id);const open=el('button',(source?.external_id||'Conversation')+(report.stale?' · context changed':''),'record-button');open.onclick=()=>busy(open,async()=>{await openRecord(report.record_id,project.id);reconciliationPanel.open=true;});details.append(open);}
  $('#projects').children[index]?.append(details);
 }
}
$('#reconcile-source').onclick=e=>busy(e.target,async()=>{
 if(!$('#reconciliation-consent').checked)throw Error('Confirm sharing this source and reviewed project memory first.');
 const job=await api('/api/analysis',{project_id:$('#source-project').value,record_id:selectedRecord.id,mode:$('#source-mode').value,provider:'meta',purpose:'reconciliation',cloud_consent:true,memory_consent:true});await monitorReading(job.id);reconciliationPanel.open=true;
});
$('#source-project').addEventListener('change',()=>{$('#reconciliation-consent').checked=false;renderReconciliation();});
const beeReconcileLabel=el('label',undefined,'background-choice');beeReconcileLabel.innerHTML='<input id="bee-reconcile" type="checkbox"> After import, use Muse reconciliation instead of local update reading. I allow this transcript, project name and up to 20 reviewed project memories to be sent to Meta.';
$('#bee-import').querySelector('button').before(beeReconcileLabel);
$('#bee-project').addEventListener('change',()=>{$('#bee-reconcile').checked=false;});
