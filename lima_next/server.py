"""Loopback Mission Control. Daily Notion writes require exact-content approval."""

import hmac
import json
import secrets
import sqlite3
import html
import webbrowser
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .interpret import analyze_document
from .analysis_jobs import AnalysisJobs
from .transcription_jobs import TranscriptionJobs, desktop_recordings
from .workspace import Workspace
from .bee_delivery import BeeDelivery
from .briefing import prepare_brief, latest_brief
from .nightly import NightlyWorker
from .context_suggestions import ContextSuggestions
from . import drafts, notion_delivery, muse_reconciliation, review_organization, subject_folders, daily_artifacts
from . import google_connection, outgoing_actions, process_day
from .memory_search import search as search_memory


ASSETS = Path(__file__).parent / "web"


class MissionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path):
        if address[0] != "127.0.0.1":
            raise ValueError("Mission Control must bind to loopback")
        self.db_path = Path(db_path)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.google = google_connection.GoogleOAuth(self.db_path, self.origin)
        self.analysis = AnalysisJobs(self.db_path)
        self.transcriptions = TranscriptionJobs(self.db_path)
        self.bee = BeeDelivery(self.db_path)
        self.context = ContextSuggestions(self.bee.inbox)
        self.nightly = NightlyWorker(self.db_path)
        self.days = process_day.DayJobs(self.db_path)

    def server_close(self):
        if hasattr(self, 'days'):
            self.days.close()
        if hasattr(self, 'context'):
            self.context.close()
        if hasattr(self, 'nightly'):
            self.nightly.close()
        if hasattr(self, 'bee'):
            self.bee.close()
        if hasattr(self, "analysis"):
            self.analysis.close()
        if hasattr(self, "transcriptions"):
            self.transcriptions.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Do not log imported content, payloads, or browser credentials.
        pass

    def reply(self, status, data, mime="application/json; charset=utf-8", download_name=None):
        body = json.dumps(data, ensure_ascii=False).encode() if mime.startswith("application/json") else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self'; connect-src 'self'; img-src 'self'; "
                         "media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {"error": "Unexpected host"})
        routes = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/file-import.js": ("file-import.js", "text/javascript; charset=utf-8"),
                  "/day.js": ("day.js", "text/javascript; charset=utf-8"),
                  "/subjects.js": ("subjects.js", "text/javascript; charset=utf-8"),
                  "/communications.js": ("communications.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path in routes:
            name, mime = routes[self.path]
            return self.reply(200, (ASSETS / name).read_bytes(), mime)
        if self.path == "/api/session":
            # Browsers cannot read this token cross-origin. Cross-site fetches are denied.
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.reply(403, {"error": "Open Mission Control directly"})
            return self.reply(200, {"token": self.server.token})
        if urlparse(self.path).path == '/google/callback':
            ws = Workspace(self.server.db_path)
            try:
                self.server.google.callback(ws, urlparse(self.path).query)
                message = 'Lima is connected to Google. Return to Lima to review proposed actions. No email or event was created.'
                status = 200
            except ValueError as error:
                message, status = str(error), 400
            finally:
                ws.close()
            return self.reply(status, ('<!doctype html><html><head><meta charset="utf-8"><title>Lima Google connection</title></head><body><h1>Google connection</h1><p>'+html.escape(message)+'</p><p><a href="/">Return to Lima</a></p></body></html>').encode(), 'text/html; charset=utf-8')
        if not self.authorized():
            return self.reply(403, {"error": "Refresh Mission Control to reconnect"})
        ws = Workspace(self.server.db_path)
        try:
            if self.path == '/api/google':
                return self.reply(200, google_connection.state(ws))
            if self.path == '/api/google-calendars':
                return self.reply(200, google_connection.Client(ws).calendars())
            if self.path == '/api/outgoing':
                return self.reply(200, outgoing_actions.listing(ws))
            if self.path == '/api/day-jobs':
                return self.reply(200, self.server.days.recent())
            if self.path.startswith('/api/day-jobs/'):
                return self.reply(200, self.server.days.get(self.path.rsplit('/',1)[1]))
            if self.path == '/api/notion':
                return self.reply(200, notion_delivery.state(ws))
            if self.path == '/api/draft-batch':
                return self.reply(200, drafts.latest_batch(ws))
            if self.path == '/api/drafts':
                return self.reply(200, drafts.listing(ws))
            if self.path.startswith('/api/drafts/'):
                return self.reply(200, drafts.get(ws, self.path.split('/')[-1]))
            if self.path == '/api/brief-schedule':
                return self.reply(200, self.server.nightly.schedule.state())
            if self.path == '/api/brief':
                return self.reply(200, latest_brief(ws))
            if self.path == '/api/bee':
                return self.reply(200, self.server.bee.inbox.state())
            if self.path == '/api/bee-rules':
                return self.reply(200, self.server.bee.inbox.routing_rules())
            if self.path.startswith('/api/bee/'):
                return self.reply(200, self.server.bee.inbox.item(self.path.split('/')[-1]))
            if self.path == "/api/state":
                from .ideas import listing
                result = ws.snapshot()
                result['ideas'] = listing(ws)
                result['reconciliations'] = muse_reconciliation.listing(ws)
                from .changes import project_changes
                for project in result['projects']:
                    project['changes'] = project_changes(project['history'])
                return self.reply(200, result)
            if self.path == "/api/backup":
                return self.reply(200, ws.backup_bytes(), "application/octet-stream",
                                  "lima-workspace.sqlite3")
            if self.path == "/api/analysis":
                return self.reply(200, self.server.analysis.recent())
            if self.path == '/api/recordings':
                return self.reply(200, desktop_recordings())
            if self.path == '/api/transcriptions':
                return self.reply(200, self.server.transcriptions.recent())
            if self.path.startswith('/api/transcriptions/'):
                parts = self.path.split('/')
                job_id = parts[3]
                if len(parts) == 4:
                    return self.reply(200, self.server.transcriptions.get(job_id))
                if len(parts) == 5 and parts[4] == 'preview':
                    return self.reply(200, self.server.transcriptions.preview(job_id), 'audio/wav')
                if len(parts) == 5 and parts[4] == 'text':
                    return self.reply(200, {'text': self.server.transcriptions.transcript(job_id)})
                return self.reply(404, {'error': 'Recording draft not found'})
            if self.path.startswith("/api/analysis/"):
                return self.reply(200, self.server.analysis.get(self.path[len("/api/analysis/"):]))
            prefix = "/api/record/"
            if self.path.startswith(prefix):
                return self.reply(200, ws.record(self.path[len(prefix):]))
            return self.reply(404, {"error": "Page not found"})
        except KeyError:
            self.reply(404, {"error": "Record not found"})
        except ValueError as error:
            self.reply(400, {'error': str(error)})
        finally:
            ws.close()

    def authorized(self):
        supplied = self.headers.get("X-Lima-Token", "")
        return hmac.compare_digest(supplied, self.server.token)

    def do_POST(self):
        if (not self.valid_host() or not self.authorized() or
                self.headers.get("Origin") != self.server.origin):
            return self.reply(403, {"error": "Request must come from this Mission Control window"})
        ws = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                return self.reply(413, {"error": "Import is too large"})
            if self.headers.get_content_type() != "application/json":
                return self.reply(415, {"error": "Expected a JSON request"})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            ws = Workspace(self.server.db_path)
            if self.path == '/api/google-client':
                result = google_connection.save_client(ws, data['client_json'])
            elif self.path == '/api/google-connect':
                result = self.server.google.start(ws, include_contacts=data.get("include_contacts",False))
                webbrowser.open(result['url'], new=1)
            elif self.path == '/api/google-events':
                result = google_connection.Client(ws).events(data['calendar_id'], data['start'], data['end'], data.get('timezone','America/Chicago'))
            elif self.path == '/api/outgoing-edit':
                result = outgoing_actions.edit(ws, data['id'], data['version_id'], data['payload'])
            elif self.path in {'/api/day-actions','/api/day-comparisons'}:
                ids = data.get('ids')
                if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) for i in ids):
                    raise ValueError('Request up to 100 explicit saved item IDs at a time.')
                getter = outgoing_actions.get if self.path == '/api/day-actions' else muse_reconciliation.get
                result = {'items':[getter(ws,identity) for identity in ids]}
            elif self.path == '/api/outgoing-dismiss':
                result = outgoing_actions.dismiss(ws, data['id'], data['version_id'])
            elif self.path == '/api/outgoing-preview':
                result = outgoing_actions.preview(ws, data['id'], data['version_id'], data['operation'])
            elif self.path == '/api/outgoing-execute':
                result = outgoing_actions.execute(ws, data['id'], confirmed=data.get('confirmed',False), acknowledge_conflicts=data.get('acknowledge_conflicts',False), acknowledge_prior=data.get('acknowledge_prior',False))
            elif self.path == '/api/meeting-preview':
                result = process_day.preview_meeting(ws, data['project_id'], data['source_type'], data['source_id'], data.get('mode','mixed'))
            elif self.path == '/api/day-note':
                job=self.server.days.get(data['id'])
                if job['status'] in {'queued','running'}:raise ValueError('Let this preparation finish before refreshing its repository note.')
                result = daily_artifacts.prepare(ws,job,cloud_consent=data.get('cloud_consent',False))
                if result:
                    old={r[0] for r in ws.db.execute('SELECT draft_id FROM muse_daily_notes WHERE job_id=?',(job['id'],))}
                    job['draft_ids']=[i for i in job['draft_ids'] if i not in old]+[result['id']]
                    self.server.days._save(job)
            elif self.path == '/api/day-preview':
                result = process_day.preview(ws, data['day'], data['project_id'], data.get('include_bee',False), data.get('mode','mixed'))
            elif self.path == '/api/day-start':
                result = self.server.days.start(data['id'], cloud_consent=data.get('cloud_consent',False))
            elif self.path == '/api/day-resume':
                result = self.server.days.resume(data['id'])
            elif self.path == '/api/day-stop':
                self.server.days.stop(data['id'])
                result = {'ok':True}
            elif self.path == '/api/memory-search':
                result = search_memory(ws, data.get('query'), data.get('project_id'), data.get('limit', 40))
            elif self.path == '/api/reconciliation-note':
                result = muse_reconciliation.prepare_note(ws, data['id'])
            elif self.path == '/api/notion-setup':
                result = notion_delivery.setup(ws, data['parent'], data.get('secret') or None)
            elif self.path == '/api/notion-preview':
                result = notion_delivery.prepare(ws, data['draft_id'], data['version_id'])
            elif self.path == '/api/notion-publish':
                result = notion_delivery.publish(ws, data['id'], confirmed=data.get('confirmed',False))
            elif self.path == '/api/notion-check':
                result = notion_delivery.publish(ws, data['id'], recover_only=True)
            elif self.path == '/api/draft-batch':
                result = drafts.prepare_all(ws, data['as_of'])
            elif self.path == '/api/drafts':
                result = drafts.prepare(ws, data['project_id'], data['kind'], data['as_of'])
            elif self.path == '/api/draft-edit':
                result = drafts.edit(ws, data['draft_id'], data['version_id'], data['subject'], data['body'])
            elif self.path == '/api/draft-review':
                result = drafts.review(ws, data['draft_id'], data['version_id'], data['decision'])
            elif self.path == '/api/bee-context-enable':
                self.server.bee.inbox.context_enabled(data.get('enabled'))
                self.server.context.wake.set()
                result = {'ok': True}
            elif self.path == '/api/bee-context-retry':
                self.server.bee.inbox.retry_context(data['item_id'])
                self.server.context.wake.set()
                result = {'ok': True}
            elif self.path == '/api/bee-speaker':
                self.server.bee.inbox.confirm_speaker(data['item_id'], data.get('speaker'))
                result = {'ok': True}
            elif self.path == '/api/bee-context':
                result = self.server.bee.inbox.review_context(data.get('item_id'), data.get('participation'),
                                                             data.get('relevance'), data.get('notes', ''))
            elif self.path == '/api/brief-schedule':
                self.server.nightly.schedule.configure(data.get('enabled'), data.get('at_time'), data.get('prepare_drafts'))
                self.server.nightly.wake.set()
                result = self.server.nightly.schedule.state()
            elif self.path == '/api/brief':
                result = prepare_brief(ws, data.get('as_of'))
            elif self.path == '/api/bee-rules':
                self.server.bee.inbox.save_rule(data['project_id'], data['phrases'], data.get('mode', 'mixed'))
                result = {'ok': True}
            elif self.path == '/api/bee-enable':
                self.server.bee.inbox.enable(data['enabled'])
                self.server.bee.wake.set()
                result = self.server.bee.inbox.state()
            elif self.path == '/api/bee-import':
                if not isinstance(data.get('analyze', False), bool):
                    raise ValueError('Choose whether to read this transcript')
                if data.get('reconcile') and (data.get('cloud_consent') is not True or data.get('memory_consent') is not True):
                    raise ValueError('Confirm sharing this Bee transcript and selected project memory with Meta first.')
                result = self.server.bee.inbox.import_item(data['item_id'], data['project_id'], data.get('mode', 'mixed'))
                if data.get('reconcile'):
                    try:
                        result['reconciliation_job'] = self.server.analysis.start(data['project_id'], result['record_id'], data.get('mode','mixed'), provider='meta', purpose='reconciliation', cloud_consent=True, memory_consent=True)
                    except ValueError as error:
                        result['analysis_error'] = str(error)
                elif data.get('analyze'):
                    try:
                        result['analysis_job'] = self.server.analysis.start(
                            data['project_id'], result['record_id'], data.get('mode', 'mixed'))
                    except ValueError as error:
                        result['analysis_error'] = str(error)
            elif self.path == "/api/projects":
                result = {"id": ws.create_project(data["name"], data.get("priority", 3))}
            elif self.path == '/api/transcriptions':
                result = self.server.transcriptions.start(data['path'])
            elif self.path == '/api/transcription-stop':
                self.server.transcriptions.stop(data['id'])
                result = {'ok': True}
            elif self.path == '/api/transcription-resume':
                result = self.server.transcriptions.resume(data['id'])
            elif self.path == '/api/transcription-import':
                result = {'id': self.server.transcriptions.import_transcript(data['id'], data['project_id'], data['mode'], data.get('reviewed_text'))}
            elif self.path == "/api/priority":
                ws.set_priority(data["project_id"], data["priority"])
                result = {"ok": True}
            elif self.path == "/api/import":
                result = {"id": ws.import_text(**data)}
            elif self.path == "/api/claims":
                result = {"id": ws.propose_claim(**data)}
            elif self.path == "/api/review":
                ws.review_claim(actor="local-user", **data)
                result = {"ok": True}
            elif self.path == "/api/file-subject":
                result = subject_folders.file_claim(ws, data["project_id"], data["claim_id"], data["name"])
            elif self.path == "/api/keep-learning-group":
                result = review_organization.keep_learning(ws, data.get("ids"))
            elif self.path == "/api/keep-reference":
                result = {"id": ws.keep_as_reference(actor="local-user", **data)}
            elif self.path == "/api/source-mode":
                result = {"mode": ws.source_mode(**data)}
            elif self.path == "/api/reconcile":
                result = ws.reconcile()
            elif self.path == "/api/dependencies":
                result = {"id": ws.set_dependency(actor="local-user", **data)}
            elif self.path == "/api/dependency-remove":
                ws.remove_dependency(actor="local-user", **data)
                result = {"ok": True}
            elif self.path == "/api/work-update":
                result = {"id": ws.update_work(actor="local-user", **data)}
            elif self.path == '/api/idea-review':
                from .ideas import review
                review(ws, data['id'], data['decision'])
                result = {'ok':True}
            elif self.path == "/api/analysis-cancel":
                self.server.analysis.cancel(data["id"])
                result = {"ok": True}
            elif self.path in {"/api/interpret", "/api/analysis"}:
                record = ws.record(data["record_id"])
                if not ws.db.execute("SELECT 1 FROM project_records WHERE project_id=? AND record_id=?",
                                     (data["project_id"], record["id"])).fetchone():
                    raise ValueError("Associate this source with the project first")
                project = ws.db.execute("SELECT name FROM projects WHERE id=?",
                                        (data["project_id"],)).fetchone()
                mode = ws.source_mode(data["project_id"], record["id"], data.get("mode"))
                provider = data.get('provider', 'ollama')
                if provider not in {'ollama', 'meta'}:
                    raise ValueError('Choose a supported interpretation provider')
                options = {'provider': 'meta', 'cloud_consent': data.get('cloud_consent', False)} if provider == 'meta' else {}
                if self.path == '/api/analysis' and data.get('purpose') in {'ideas','reconciliation'}:
                    options.update(purpose=data['purpose'],memory_consent=data.get('memory_consent',False))
                if self.path == "/api/analysis":
                    result = self.server.analysis.start(data["project_id"], record["id"], mode, **options)
                else:
                    result = analyze_document(ws, data["project_id"], record["id"], mode=mode, **options)
            elif self.path == "/api/demo":
                result = load_demo(ws)
            else:
                return self.reply(404, {"error": "Action not found"})
            self.reply(200, result)
        except (ValueError, TypeError, KeyError, sqlite3.IntegrityError) as error:
            self.reply(400, {"error": str(error)})
        except Exception:
            self.reply(500, {"error": "Lima could not finish this request. Existing records are preserved."})
        finally:
            if ws:
                ws.close()


def load_demo(ws):
    """Only synthetic records, visibly labeled; repeat loading does not duplicate them."""
    project = ws.create_project("Sample · Research demo", 2)
    text1 = ("USER: The app is complete.\nUSER: I will prepare the demo video.\n"
             "USER: Use slides for the presentation.\nTV: I am moving to Chicago next month.")
    text2 = ("USER: Replace the slides plan with a live demo.\n"
             "USER: I still need to upload the final submission.\n"
             "USER: The demo video deadline might be November 4; I need to confirm it.")
    first = ws.import_text([project], kind="transcript", external_id="sample-chat-1", content=text1)
    second = ws.import_text([project], kind="chatgpt", external_id="sample-chat-2", content=text2)
    def claim(record, text, quote, **values):
        start = text.index(quote)
        return ws.propose_claim(project, record, start=start, end=start + len(quote), **values)
    accepted = {c["id"] for c in ws.claims() if c["review"] != "pending"}
    def accept_once(cid, supersedes=None):
        if cid not in accepted:
            ws.review_claim(cid, decision="accepted", actor="synthetic-demo", supersedes=supersedes)
    app = claim(first, text1, "USER: The app is complete.", kind="deliverable", subject="Application",
                value="Application complete", attribution="user", owner="user", state="done")
    accept_once(app)
    video = claim(first, text1, "USER: I will prepare the demo video.", kind="deliverable",
                  subject="Demo video", value="Prepare the demo video", attribution="user", owner="user")
    accept_once(video)
    old = claim(first, text1, "USER: Use slides for the presentation.", kind="decision",
                subject="Presentation format", value="Use slides", attribution="user", owner="user")
    accept_once(old)
    new = claim(second, text2, "USER: Replace the slides plan with a live demo.", kind="decision",
                subject="Presentation format", value="Use a live demo", attribution="user", owner="user")
    accept_once(new, old)
    claim(first, text1, "TV: I am moving to Chicago next month.", kind="commitment", subject="Move",
          value="Move to Chicago", attribution="ambient", owner="unknown")
    claim(second, text2, "USER: I still need to upload the final submission.", kind="deliverable",
          subject="Final submission", value="Upload final submission", attribution="user", owner="user")
    claim(second, text2, "USER: The demo video deadline might be November 4; I need to confirm it.",
          kind="question", subject="Demo deadline", value="Confirm November 4 and its year",
          attribution="user", owner="user")
    return {"project_id": project}
