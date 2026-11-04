/* Subject folders are local organization; filing never approves work. */
const subjectPanel=el('details',undefined,'subject-library panel');
subjectPanel.append(el('summary','Subject folders'));
const subjectIntro=el('p','A running view of each subject, with reviewed information, proposed updates and source dates kept distinct.');
const subjectProjectLabel=el('label','Project');const subjectProject=el('select');subjectProject.className='project-select';subjectProjectLabel.append(subjectProject);
const settingNames={class:'Class & learning',meeting:'Meeting',conversation:'Conversation',personal:'Personal',uncertain:'Context uncertain'};
const subjectList=el('div');subjectPanel.append(subjectIntro,subjectProjectLabel,subjectList);$('#home').insertBefore(subjectPanel,$('#projects'));
subjectProject.onchange=()=>renderSubjectFolders();
const refreshSubjects=el('button','Refresh folder overview','secondary');refreshSubjects.onclick=()=>busy(refreshSubjects,refresh);subjectIntro.after(refreshSubjects);
const openSubjects=new Set();let subjectFieldSerial=0;
function renderSubjectFolders(){
 const projects=state.projects;const previous=subjectProject.value;subjectProject.replaceChildren();
 for(const project of projects){const option=el('option',project.name);option.value=project.id;subjectProject.append(option);}if(projects.some(p=>p.id===previous))subjectProject.value=previous;
 const folders=(state.subject_folders||[]).filter(f=>f.project_id===subjectProject.value);subjectList.replaceChildren();
 subjectPanel.querySelector('summary').textContent='Subject folders';
 if(!folders.length)subjectList.append(el('p','Subjects appear here when Lima finds information to file. New subjects get a folder inside this project.'));
 for(const folder of folders){
  const card=el('details',undefined,'subject-folder');card.open=openSubjects.has(folder.id);card.addEventListener('toggle',()=>{if(card.open)openSubjects.add(folder.id);else openSubjects.delete(folder.id);});
  card.append(el('summary',`${folder.name} · ${folder.current.length} reviewed · ${folder.pending.length} pending`));
  const freshness=el('p',folder.freshness+(folder.needs_fresh_check?' · Check for newer information.':''),'fine');card.append(freshness,el('p',folder.contexts.map(c=>settingNames[c]||settingNames.uncertain).join(' · '),'fine'));
  const dates=el('p',`Latest source: ${folder.latest_source_at?new Date(folder.latest_source_at).toLocaleString():'unknown'} · Last reviewed: ${folder.last_reviewed_at?new Date(folder.last_reviewed_at).toLocaleString():'not reviewed'} · ${folder.source_count} sources`,'fine');card.append(dates);
  if(folder.freshness_incomplete)card.append(el('p','Some source dates are unknown; freshness is incomplete.','fine'));
  if(folder.latest_reviewed_source_at)card.append(el('p','Reviewed information comes from sources dated through '+new Date(folder.latest_reviewed_source_at).toLocaleString()+'.','fine'));
  card.append(el('h3','Running overview'));
  if(!folder.current.length)card.append(el('p','No current reviewed information yet. Proposed interpretations remain below.'));
  for(const item of folder.current){const row=el('div',undefined,'subject-entry');row.append(badge(item.kind==='reference'?'Learning':item.kind),badge(settingNames[item.context_category]||settingNames.uncertain),el('strong',item.value));if(item.kind!=='reference')row.append(el('p',`${item.state} · owner: ${item.owner}`,'fine'));sourceControls(row,item,folder,folders);card.append(row);}
  if(folder.conflicts.length){card.append(el('h3','Conflicting reviewed information'));for(const conflict of folder.conflicts){card.append(el('p',`Resolve ${conflict.subject}; both versions remain visible.`));for(const item of conflict.claims){const row=el('div',undefined,'subject-entry');row.append(el('p',item.value));sourceControls(row,item,folder,folders);card.append(row);}}}
  if(folder.pending.length){const proposals=el('details');proposals.append(el('summary',`Proposed updates · ${folder.pending.length}`),el('p','These have not changed the reviewed overview.'));
   for(const item of folder.pending){const row=el('div',undefined,'subject-entry');row.append(el('strong',item.value),badge(item.context_category||'context uncertain'));sourceControls(row,item,folder,folders);const review=el('button','Review in source','secondary');review.onclick=()=>{reviewFilter=folder.project_id+':'+item.record_id;render();page('review');};row.append(review);proposals.append(row);}card.append(proposals);}
  const history=el('details');history.append(el('summary',`Evidence history · ${folder.history.length}`));for(const item of folder.history){const row=el('div',undefined,'subject-entry');row.append(el('p',`${item.review} · ${item.subject}: ${item.value}`));sourceControls(row,item,folder,folders);history.append(row);}card.append(history);subjectList.append(card);
 }
}
function sourceControls(row,item,folder,folders){
 const details=el('details');details.append(el('summary','Evidence & filing'),el('blockquote',item.quote),el('small',`${item.external_id} · ${item.captured_at||'source date unknown'}`,'fine'));
 const source=el('button','Open source','secondary');source.onclick=()=>busy(source,()=>openRecord(item.record_id,folder.project_id));details.append(source);
 const form=el('form');const label=el('label','Subject folder');const input=el('input');input.value=folder.name;input.maxLength=200;input.required=true;const options=el('datalist');options.id='subject-options-'+(++subjectFieldSerial);for(const folderChoice of folders){const option=el('option');option.value=folderChoice.name;options.append(option);}input.setAttribute('list',options.id);label.append(input,options);const move=el('button','File here','secondary');form.append(label,move,el('p','Enter an existing subject name or a new one. Filing does not change the interpretation or its review.','fine'));
 form.onsubmit=e=>{e.preventDefault();busy(move,async()=>{await api('/api/file-subject',{project_id:folder.project_id,claim_id:item.id,name:input.value});await refresh();notify('Subject folder updated. Review status unchanged.');});};details.append(form);row.append(details);
}
if(state)renderSubjectFolders();

/* A single daily path. Existing version/destination approval controls stay intact. */
const learningPage=el('section');learningPage.id='library';learningPage.className='page';learningPage.hidden=true;document.querySelector('main').append(learningPage);
const studyList=el('div');const studyViewer=el('section',undefined,'study-view');studyViewer.hidden=true;learningPage.append(studyViewer);learningPage.append(el('h2','Class lessons'),el('p','Saved here for study. You can come back before an exam.'),studyList);
const libraryNav=el('button','▱ Saved learning');libraryNav.dataset.page='library';libraryNav.onclick=()=>openLearning();document.querySelector('nav').append(libraryNav);
async function openLearning(){
 page('library');learningPage.classList.remove('reading-lesson');studyViewer.hidden=true;studyList.hidden=false;studyList.replaceChildren(el('p','Loading lessons…','fine'));
 const summaries=await api('/api/drafts');const notes=await Promise.all(summaries.filter(d=>d.kind==='notes').map(d=>api('/api/drafts/'+d.id)));
 studyList.replaceChildren();let found=0;
 for(const d of notes.filter(d=>/class lesson/i.test(d.subject)||d.evidence.length&&d.evidence.every(e=>e.context_category==='class'))){found++;const row=el('button',undefined,'record-button');const label=/Daily class lesson$/i.test(d.subject)?'Class lesson: '+(d.evidence[0]?.subject||d.subject):d.subject;row.append(el('strong',label),el('span',d.as_of,'fine'));row.onclick=()=>openStudy(d);studyList.append(row);}
 for(const project of state.projects){const records=new Set(project.history.filter(c=>lessonLearning(c)&&c.review==='pending').map(c=>c.record_id));for(const id of records){found++;const b=el('button',`Class lesson awaiting review · ${project.name}`,'record-button');b.onclick=()=>{reviewFilter=project.id+':'+id;render();page('review');};studyList.append(b);}}
 if(!found)studyList.append(el('p','No class lessons saved yet. They will appear here after a day is processed.','fine'));
}
// Move management surfaces off Today; preserve their controls and saved state.
const management=el('details',undefined,'library-management');management.append(el('summary','Projects & memory'));
const projectHeading=$('#add-project').closest('.section-title');if(projectHeading)management.append(projectHeading);
for(const id of ['project-form','collisions','projects','empty'])management.append($('#'+id));learningPage.append(management);
const folderLink=el('button','Subject folders','secondary');folderLink.onclick=()=>{subjectPanel.open=!subjectPanel.open;};learningPage.append(folderLink,subjectPanel);subjectPanel.hidden=true;folderLink.onclick=()=>{subjectPanel.hidden=!subjectPanel.hidden;subjectPanel.open=!subjectPanel.hidden;};
const tools=el('details');tools.append(el('summary','More tools'),homeTools);learningPage.append(tools,$('#memory-results-panel'));
const links=el('div',undefined,'actions');for(const [label,target] of [['Sources','sources'],['Evidence review','review'],['All notes','drafts']]){const b=el('button',label,'secondary');b.onclick=()=>{page(target);if(target==='drafts')refreshDrafts().catch(e=>notify(e.message,true));};links.append(b);}learningPage.append(links);
todayFlow.hidden=true;$('#metrics').hidden=true;const quick=$('#home .quick-workspace-actions');if(quick)quick.hidden=true;
// Leave only day and processing on the main surface; retain advanced inclusion choices.
const processOptions=el('details',undefined,'process-options');processOptions.append(el('summary','Options'));
const processForm=$('#process-day-form');const projectField=$('#day-project').closest('label');processOptions.append(projectField,scopeLabel,meetingLabel);
for(const detail of [...processForm.querySelectorAll(':scope > details')])processOptions.append(detail);
processForm.insertBefore(processOptions,$('#day-scope'));$('#day-cloud-consent').closest('label').lastChild.textContent=' Let Muse prepare these transcripts and saved context. I review before anything is sent.';
$('#day-open-latest').textContent='Continue my review';dayHome.querySelector('h2').textContent='Process my day';dayHome.querySelector('.section-title p').textContent='Come back to a summary and the few things that need your attention.';
const studyShortcut=el('button','Saved learning','secondary');studyShortcut.onclick=openLearning;dayHome.append(studyShortcut);
// Present the same saved day as a summary and a ready-to-edit action queue.
const originalDayReview=loadDayReview;
loadDayReview=async function(id){await originalDayReview(id);if(!$('#day-results').children.length)return;await simplifyDailyReview(id);};
async function simplifyDailyReview(id){
 const job=await api('/api/day-jobs/'+id);const box=$('#day-results');if(visibleDayJob!==id||['queued','running'].includes(job.status))return;
 $('#day-report-status').classList.add('compact-day-status');
 const children=[...box.children];const technical=el('details',undefined,'daily-details');technical.append(el('summary','Sources and processing details'));const rawStatus=$('#day-report-status');technical.append(el('p',rawStatus.textContent,'fine'));rawStatus.textContent=job.day+' · '+(job.errors.length?'Some items need attention':'Ready to review');const policy=$('#day-review > p.fine');if(policy)policy.hidden=true;
 const summary=el('section',undefined,'panel day-summary');summary.append(el('h2','Your day in brief'));
 let note=null;
 for(const draftId of [...job.draft_ids].reverse()){const d=await api('/api/drafts/'+draftId);if(/^Daily review/.test(d.subject)){note=d;break;}}
 const project=state.projects.find(p=>p.id===job.project_id);for(const record of Object.values(job.records)){const topics=[...new Set((project?.history||[]).filter(c=>c.record_id===record&&c.context_category==='class'&&c.review!=='rejected').map(c=>c.subject))];if(topics.length)summary.append(el('p',`Class lesson: ${topics.slice(0,3).join(', ')}. Saved for study.`,'fine'));}
 if(note){const main=note.body.split('Follow-up queue')[0].split('Proposed / uncertain')[0];const lines=main.split('\n').filter(l=>l.startsWith('- ')&&!/evidence points;/.test(l));const list=el('ul');for(const line of lines.slice(0,2))list.append(el('li',line.slice(2).replace(/\s*\[E[\d, E]*\]/g,'')));summary.append(list);if(note.stale)technical.append(el('p','The stored daily note needs a refresh after recent evidence reviews.','fine'));}
 else summary.append(el('p','Processing finished. Review the follow-ups below.'));
 const actions=children.find(e=>e.querySelector('h2')?.textContent==='Muse follow-ups for review');
 if(actions){
  const recent=await api('/api/day-jobs');const own=new Set(job.action_ids);const earlier=[...new Set(recent.filter(j=>j.id!==id).flatMap(j=>j.action_ids||[]))].filter(a=>!own.has(a));const carry=[];
  for(let i=0;i<earlier.length;i+=100){const response=await api('/api/day-actions',{ids:earlier.slice(i,i+100)});carry.push(...response.items.filter(a=>!a.dismissed&&!a.receipts.some(r=>r.status==='completed')));}
  if(carry.length){actions.append(el('h3','Still unfinished from earlier days'));for(const item of carry)actions.append(outgoingCard(item));}
  actions.classList.add('daily-action-queue');actions.querySelector('h2').textContent='Follow-ups';actions.prepend(el('p','Fill what you know. Unfinished items stay here. Preview and approve each ready action.','fine'));}
 const study=el('section',undefined,'study-away');const saveStudy=el('button','Class lessons · saved for later','secondary');saveStudy.onclick=openLearning;study.append(saveStudy);
 box.replaceChildren(summary,study);if(actions)box.append(actions);
 const notes=children.find(e=>e.querySelector('h2')?.textContent==='Notes for review and Notion');if(notes){const noteDetails=el('details');noteDetails.append(el('summary','Daily note & Notion'),notes);box.append(noteDetails);}
 for(const child of children)if(child!==actions&&child!==notes)technical.append(child);box.append(technical);
}

function openStudy(note){
 learningPage.classList.add('reading-lesson');studyList.hidden=true;studyViewer.hidden=false;studyViewer.replaceChildren();const back=el('button','Back to lessons','secondary');back.onclick=openLearning;
 studyViewer.append(back,el('h2',note.subject),el('p',note.as_of,'fine'),el('pre',note.body.split('Supporting transcript passages')[0],'study-text'));
 const evidence=el('details');evidence.append(el('summary','Original passages'));for(const e of note.evidence)evidence.append(el('blockquote',e.quote));studyViewer.append(evidence);
 const edit=el('button','Edit this lesson','secondary');edit.onclick=()=>{page('drafts');showDraft(note);};studyViewer.append(edit);
}
