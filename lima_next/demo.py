"""Repeatable synthetic showcase and optional, explicitly consented live Meta check."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .workspace import Workspace
from . import drafts

EARLIER = '''SYNTHETIC DEMO — scripted example, not a real meeting.
USER: We decided to use slides for the campus demonstration.
USER: I will prepare the demonstration video.
TV: I will book the venue and pay the deposit tomorrow.
'''
LATER = '''SYNTHETIC DEMO — scripted example, not a real meeting.
USER: We have agreed to replace the slides with a live demonstration.
USER: I will prepare the demonstration video by 2026-11-04.
Alex: We should probably launch next month, but nobody has agreed yet.
USER: I keep thinking a small audio notebook might connect the experiments. This is only an idea, not an agreed task.
LECTURER: Successful teams should always prepare a risk management plan.
'''


def build(path):
    path=Path(path)
    if path.exists():raise ValueError('Choose a new demo workspace path; existing files are never reset.')
    path.parent.mkdir(parents=True,exist_ok=True)
    ws=Workspace(path)
    try:
        project=ws.create_project('Synthetic demo — campus project',2)
        first=ws.import_text([project],kind='chatgpt',external_id='Synthetic earlier planning chat',content=EARLIER)
        second=ws.import_text([project],kind='transcript',external_id='Synthetic later campus conversation',content=LATER)
        def claim(record,text,quote,kind,subject,value,accepted=False,supersedes=None,**options):
            start=text.index(quote)
            identity=ws.propose_claim(project,record,start=start,end=start+len(quote),kind=kind,
                subject=subject,value=value,attribution='user',owner='user',proposer='synthetic-fixture',**options)
            if accepted:ws.review_claim(identity,decision='accepted',actor='synthetic-fixture',supersedes=supersedes)
            return identity
        old=claim(first,EARLIER,'USER: We decided to use slides for the campus demonstration.',
                  'decision','Presentation format','Use slides',True)
        claim(second,LATER,'USER: We have agreed to replace the slides with a live demonstration.',
              'decision','Presentation format','Use a live demonstration',True,old)
        video=claim(first,EARLIER,'USER: I will prepare the demonstration video.',
                    'deliverable','Demonstration video','Prepare the demonstration video',True)
        claim(second,LATER,'USER: I will prepare the demonstration video by 2026-11-04.',
              'deliverable','Demonstration video','Prepare the demonstration video',False,
              due_date='2026-11-04',date_basis='verified')
        prepared=drafts.prepare(ws,project,'update',date.today().isoformat())
        # This draft is intentionally unapproved; the demonstrator reviews it in the UI.
        return {'project_id':project,'earlier_record':first,'later_record':second,'draft_id':prepared['id'],
                'prior_video_claim':video,'mode':'scripted synthetic fixture; not live model output'}
    finally:ws.close()


def evaluate(path, *, cloud_consent=False):
    if cloud_consent is not True:raise ValueError('Explicit consent is required for synthetic Meta evaluation.')
    path=Path(path)
    if path.exists():raise ValueError('Choose a new evaluation database; existing workspaces are never reset.')
    path.parent.mkdir(parents=True,exist_ok=True)
    from .interpret import analyze_document
    scenarios=[
        ('explicit_commitment','USER: I will prepare the demonstration video.',True),
        ('unagreed_proposal','Alex: We should probably launch next month, but nobody agreed or accepted ownership.',False),
        ('background_first_person','TV: I will book the venue tomorrow. The wearer is only watching this television programme.',False),
        ('conditional','USER: If the grant is approved, I might prepare a proposal. No approval or commitment has been made.',False),
        ('missing_date','USER: I will prepare the demonstration video soon.',True),
    ]
    ws=Workspace(path);results=[]
    try:
        for name,text,expect_work in scenarios:
            project=ws.create_project('Synthetic evaluation — '+name)
            record=ws.import_text([project],kind='transcript',external_id=name,content=text)
            result=analyze_document(ws,project,record,provider='meta',cloud_consent=True)
            candidates=ws.claims(project)
            actionable=[c for c in candidates if c['kind'] in {'commitment','deliverable'} and not c['review_block_reason'] and c['attribution'] not in {'ambient','uncertain'}]
            no_invented_date=all(c['due_date'] is None for c in candidates)
            passed=bool(actionable)==expect_work and no_invented_date and not result['section_errors']
            results.append({'scenario':name,'passed':passed,'expected_actionable_candidate':expect_work,
                            'actionable_candidates':len(actionable),'no_invented_date':no_invented_date,
                            'all_pending':all(c['review']=='pending' for c in candidates),
                            'claims':candidates,'reading':result})
        return {'mode':'live Meta on synthetic text only','results':results,
                'limitations':'Small smoke evaluation, not a real-world accuracy benchmark. Retain failures and inspect quotes.'}
    finally:ws.close()


def build_day(path):
    """Sources only: the actual day button performs live inference after consent."""
    path=Path(path)
    if path.exists():raise ValueError('Choose a new demo workspace; existing files are never reset.')
    path.parent.mkdir(parents=True,exist_ok=True)
    ws=Workspace(path)
    try:
        from .process_day import ZONE
        now=datetime.now(timezone.utc);tomorrow=(now.astimezone(ZONE).date()+timedelta(days=1)).isoformat()
        project=ws.create_project('SYNTHETIC daily review - campus example')
        earlier='SCRIPTED SYNTHETIC FIXTURE. USER: We agreed to demonstrate the prototype on campus.'
        record=ws.import_text([project],kind='text',external_id='Synthetic prior agreement',content=earlier,captured_at=(now-timedelta(days=1)).isoformat())
        claim=ws.propose_claim(project,record,start=0,end=len(earlier),kind='decision',subject='Demonstration plan',value='Demonstrate on campus',attribution='user',proposer='synthetic-fixture')
        ws.review_claim(claim,decision='accepted',actor='synthetic-fixture')
        text=('SCRIPTED SYNTHETIC FIXTURE. USER: Please draft an email to alex@example.com asking whether the campus demonstration is confirmed. '
              f'USER: Prepare a personal calendar block on {tomorrow} from 14:00 to 15:00 America/Chicago for preparing the demonstration. '
              'Alex Rivera: My contact details are Alex Rivera, alex@example.com, +15551234567. Please save my contact information. '
              'USER: Draft a text to Alex Rivera at +15551234567 asking whether the campus demonstration is confirmed. '
              'These are requests to prepare drafts for review, not permission to send or schedule anything.')
        ws.import_text([project],kind='transcript',external_id='Synthetic day conversation',content=text,captured_at=now.isoformat())
        return {'project_id':project,'day':now.astimezone(ZONE).date().isoformat(),'mode':'scripted sources; no model calls or outward actions have run'}
    finally:ws.close()


def build_showcase(path):
    """Offline replay of recorded Muse output on scripted sources, never account writes."""
    from . import process_day,outgoing_actions,daily_artifacts
    from .briefing import evidence
    from .store import _now
    from .workspace import fingerprint
    import uuid
    path=Path(path)
    if path.exists():raise ValueError('Choose a new demo path; existing files are never reset.')
    path.parent.mkdir(parents=True,exist_ok=True)
    capture=json.loads((Path(__file__).parent/'demo_assets'/'muse_showcase.json').read_text(encoding='utf-8'))
    if capture.get('synthetic') is not True:raise ValueError('Only clearly synthetic showcase data may be replayed.')
    ws=Workspace(path)
    try:
        with ws.db:
            ws.db.execute('CREATE TABLE demo_provenance (description TEXT NOT NULL)')
            ws.db.execute('INSERT INTO demo_provenance VALUES (?)',(capture['provenance'],))
        project=ws.create_project('SYNTHETIC DEMO — recorded Muse outputs')
        prior=capture['prior'];old=ws.import_text([project],kind='transcript',external_id='Synthetic prior decision',content=prior['content'],captured_at='2026-11-01T15:00:00+00:00')
        claim=ws.propose_claim(project,old,start=0,end=len(prior['content']),kind='decision',subject=prior['subject'],value=prior['value'],attribution='user',proposer='synthetic-fixture')
        ws.review_claim(claim,decision='accepted',actor='synthetic-fixture')
        record=ws.import_text([project],kind='transcript',external_id='Synthetic end-of-meeting follow-ups',content=capture['source'],captured_at='2026-11-02T15:00:00+00:00')
        snapshot=process_day.preview(ws,capture['day'],project)
        ids=[outgoing_actions.propose(ws,project,record,candidate)['id'] for candidate in capture['actions']]
        action_map={candidate['original_id']:identity for candidate,identity in zip(capture['actions'],ids)}
        job={**snapshot,'id':uuid.uuid4().hex,'status':'completed','stage':'Recorded Muse replay on scripted data. No live model call or outward action in this session.',
             'processed':2,'total':2,'records':{record:record},'outcomes':{},'errors':[],'action_ids':ids,'draft_ids':[],'report_ids':[],
             'cloud_consent':False,'pipeline_version':process_day.PIPELINE_VERSION,'final_context_stamp':drafts.project_stamp(ws,project),'replay':True}
        with ws.db:ws.db.execute('INSERT INTO day_jobs VALUES (?,?)',(job['id'],json.dumps(job)))
        daily_artifacts.schema(ws);stamp=drafts.project_stamp(ws,project);identity=fingerprint(['showcase-note',job['id']])
        body='RECORDED REPLAY of an actual Muse-generated draft on scripted data. Local evidence IDs are remapped. No action has been delivered.\n\n'+capture['daily_note']['body'].replace(prior['original_id'],claim)
        for old_id,new_id in action_map.items():body=body.replace(old_id,new_id)
        original=next(c for c in ws.claims(project) if c['id']==claim);now=_now()
        with ws.db:
            ws.db.execute('INSERT INTO local_drafts VALUES (?,?,?,?,?,?,?)',(identity,project,'notes',capture['day'],stamp,json.dumps([evidence(original)]),now))
            ws.db.execute('INSERT INTO local_draft_versions VALUES (?,?,?,?,?)',(uuid.uuid4().hex,identity,'Daily review — recorded synthetic Muse run',body,now))
            ws.db.execute('INSERT INTO muse_daily_notes VALUES (?,?,?,?)',(identity,job['id'],daily_artifacts.artifact_hash(ws,job),'muse-spark-1.3 recorded replay'))
            job['draft_ids']=[identity];ws.db.execute('UPDATE day_jobs SET payload=? WHERE id=?',(json.dumps(job),job['id']))
        return {'project_id':project,'job_id':job['id'],'draft_id':identity,'day':capture['day'],'mode':capture['provenance']}
    finally:ws.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True,help='A new isolated database path')
    parser.add_argument('--evaluate-meta',action='store_true')
    parser.add_argument('--consent-synthetic-meta',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--day-workflow',action='store_true',help='Seed only synthetic sources for the real Process my day workflow')
    parser.add_argument('--showcase',action='store_true',help='Replay recorded Muse outputs on scripted data, offline and without account writes')
    args=parser.parse_args()
    if sum((args.showcase,args.day_workflow,args.evaluate_meta))>1:parser.error("Choose one demo mode: showcase, day-workflow or evaluate-meta.")
    if args.evaluate_meta:
        if not args.output or args.output.exists():parser.error('Choose a new --output JSON file')
        result=evaluate(args.db,cloud_consent=args.consent_synthetic_meta)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        print('Live synthetic evaluation saved. Inspect successes and failures in the report.')
    else:
        result=build_showcase(args.db) if args.showcase else build_day(args.db) if args.day_workflow else build(args.db)
        print('Created isolated recorded-Muse replay. No new model call or external write occurred.' if args.showcase else 'Created isolated scripted synthetic demo. No model call or external write occurred.')
        print('Start with: python -m lima_next serve --db "'+str(args.db)+'" --port 8766')


if __name__=='__main__':main()
