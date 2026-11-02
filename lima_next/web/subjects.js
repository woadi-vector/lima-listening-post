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
 subjectPanel.querySelector('summary').textContent=`Subject folders · ${folders.length}`;
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
