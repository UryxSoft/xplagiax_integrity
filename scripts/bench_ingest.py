"""Peak RSS and latency of one API process ingesting a synthetic document.

DESTRUCTIVE for the target database: it downgrades to base before and after.
Use a disposable database only.

    python scripts/bench_ingest.py mysql+pymysql://user:pass@127.0.0.1:3306/scratch_db 100000

Results for several sizes are recorded in docs/PERFORMANCE.md §1.2.
"""
import json, random, sys, time, resource
from alembic import command
from alembic.config import Config
URL = sys.argv[1]; WORDS = int(sys.argv[2])
cfg = Config(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic.ini")); cfg.set_main_option("sqlalchemy.url", URL); cfg.attributes["configure_logger"] = False
command.downgrade(cfg, "base"); command.upgrade(cfg, "head")
from integrity.app import create_app
from integrity.config import Settings
from integrity.domain.enums import ClientScope
from integrity.infrastructure.db.models import Organization, ServiceClient
from integrity.infrastructure.db.session import session_scope
from integrity.security.api_keys import generate_key
P = "p" * 40
app = create_app(Settings(env="production", database_url=URL, api_key_pepper=P, log_level="ERROR"))
k = generate_key(P)
with session_scope(app) as s:
    s.add(Organization(external_ref="user:1", name="u")); s.add(ServiceClient(name="c", key_prefix=k.prefix, key_hash=k.digest, scope=ClientScope.PLATFORM))
c = app.test_client(); c.get("/api/v1/health/ready")
rss = lambda: int([l for l in open('/proc/self/status') if l.startswith('VmRSS')][0].split()[1]) // 1024
random.seed(1)
vocab = [''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(random.randint(3, 10))) for _ in range(20000)]
words = [random.choice(vocab) for _ in range(WORDS)]
paragraphs, page = [], 1
for i in range(0, WORDS, 120):
    paragraphs.append([page, (i // 120) % 8 + 1, " ".join(words[i:i+120])])
    if (i // 120) % 8 == 7: page += 1
text = "\n".join(p[2] for p in paragraphs)
body = json.dumps({"schema": "xplagiax.document/v1", "source": {"producer": "xplagiax_appcli2"}, "text": text,
                   "paragraphs": paragraphs, "language": "en", "extraction": {"status": "complete", "pages_total": page}})
base = rss()
t = time.perf_counter()
r = c.post("/api/v1/documents", data=body, content_type="application/json",
           headers={"Authorization": f"Bearer {k.plaintext}", "X-Integrity-Org": "user:1", "Idempotency-Key": "mem-key-00001"})
dt = time.perf_counter() - t
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
from integrity.infrastructure.db.models import DocumentContent
with session_scope(app) as s:
    row = s.query(DocumentContent).one_or_none(); blob = row.payload_bytes if row else 0
print(json.dumps({"err": (r.get_json() or {}).get("error", {}).get("details", [None])[:1] if r.status_code >= 400 else None, "words": WORDS, "pages": page, "body_mb": round(len(body)/1e6, 2), "status": r.status_code,
                  "rss_before_mb": base, "peak_rss_mb": peak, "delta_mb": peak - base,
                  "ingest_s": round(dt, 2), "stored_mb": round(blob/1e6, 2)}))
command.downgrade(cfg, "base")
