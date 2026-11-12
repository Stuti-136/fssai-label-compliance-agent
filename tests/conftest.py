import os, sys, tempfile
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp()
os.environ.update(REDIS_URL="fakeredis://", EMBEDDING_BACKEND="hash", INDEX_DIR=_tmp + "/idx", CORPUS_DIR=str(ROOT / "corpus/raw"),
                  ALLOW_FAULT_INJECTION="true", RATE_LIMIT_PER_MIN="1000", LLM_MAX_RETRIES="0")
os.environ.pop("LLM_BASE_URL", None)


@pytest.fixture(scope="session")
def index():
    from app.rag.ingest import run_ingest
    from app.rag.store import CorpusIndex
    run_ingest()
    return CorpusIndex()


@pytest.fixture
def redis():
    from app.redis_client import get_redis
    r = get_redis()
    r.flushall()
    return r
