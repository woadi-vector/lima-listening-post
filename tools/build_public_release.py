"""Build an allowlisted public candidate; never publish or copy workspace data."""
import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

DOCS=['DEMO_RUNBOOK.md','TUESDAY_FIELD_TEST.md','NOTION_DAILY_REVIEW.md','EMERGING_IDEAS.md','CHANGE_VIEW.md','MUSE_RECONCILIATION.md','GOOGLE_CONNECTION.md','PROCESS_MY_DAY.md','PHONE_ACCESS.md','REVIEW_ORGANIZATION.md','SUBJECT_FOLDERS.md','MUSE_OUTPUTS.md']


def build(source, destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new candidate directory; existing outputs are never overwritten.')
    files=[]
    for directory in ('lima_next','tests_next'):
        files.extend(p for p in (source/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and
                     (p.suffix=='.py' or directory=='lima_next' and p.parent.name=='web' and p.suffix in {'.html','.js','.css'}))
    files.append(source/'lima_next'/'demo_assets'/'muse_showcase.json')
    files.extend(source/'docs'/name for name in DOCS)
    files.append(source/'tools'/'build_public_release.py')
    files.append(source/'tools'/'phone_access.py')
    files.append(source/'Open Lima on phone.cmd')
    assets=source/'release_assets'
    if not assets.is_dir():assets=source
    files.extend(assets/name for name in ('README.md','pyproject.toml','.gitignore','.env.example','CONTRIBUTIONS.md','SECURITY.md','VALIDATION.md'))
    for extra in ('LICENSE','THIRD_PARTY_NOTICES.md','.github/workflows/tests.yml'):
        if (assets/extra).is_file():files.append(assets/extra)
    violations=[];manifest=[]
    known_secrets=[os.environ.get(k,'') for k in ('MODEL_API_KEY','LIMA_NOTION_TOKEN','NOTION_TOKEN','OPENAI_API_KEY')]
    for path in files:
        text=path.read_text(encoding='utf-8')
        relative=path.relative_to(assets) if path.is_relative_to(assets) else path.relative_to(source)
        if any(secret and len(secret)>=16 and secret in text for secret in known_secrets):violations.append(str(relative)+': credential match')
        if re.search(r'(?i)C:[/\\]Users[/\\](?!example|your)',text):violations.append(str(relative)+': private Windows path')
        if re.search(r'(?i)\b(?:secret_|ntn_|sk-proj-)[A-Za-z0-9_-]{20,}',text):violations.append(str(relative)+': possible embedded credential')
        manifest.append({'path':relative.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    if violations:raise ValueError('Release scan failed: '+ '; '.join(violations))
    destination.mkdir(parents=True)
    for path,item in zip(files,manifest):
        target=destination/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    report={'files':sorted(manifest,key=lambda x:x['path']),'scan':'allowlist + known environment credential match + obvious token/private path patterns',
            'scan_findings':[], 'limitations':'Automated scanning is not a complete secret or ownership audit. Review before publishing.',
            'excluded':['legacy lima/','recordings','databases','DPAPI credential files','.env files','private handoffs','research PDFs','work/','.venv/','historical planning docs'],
            'publication':'Local candidate only. Nothing pushed or published. License not selected.'}
    (destination/'RELEASE_MANIFEST.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    archive=destination.with_suffix('.zip')
    if archive.exists():raise ValueError('Archive already exists; choose a new candidate name.')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(destination.rglob('*')):
            if path.is_file():bundle.write(path,path.relative_to(destination))
    return {'directory':str(destination),'archive':str(archive),'files':len(manifest),'scan_findings':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(Path(__file__).resolve().parents[1],args.output)))
