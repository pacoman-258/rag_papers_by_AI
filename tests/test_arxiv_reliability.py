import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import requests

from backend import paper_reader_service as prs
from local_paper_db.app import external_sources as ext


class ArxivReliabilityTest(unittest.TestCase):
    def tearDown(self):
        ext._CACHE.clear()

    def test_pdf_download_retries_with_alternate_urls_after_ssl_eof(self):
        calls = []

        class Response:
            status_code = 200
            headers = {"content-type": "application/pdf"}
            content = b"%PDF-1.4\n%ok\n%%EOF\n"

            def raise_for_status(self):
                return None

        original_get = prs.requests.get
        original_sleep = prs.time.sleep
        try:
            def fake_get(url, **kwargs):
                calls.append(url)
                if len(calls) == 1:
                    raise requests.exceptions.SSLError(
                        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
                    )
                return Response()

            prs.requests.get = fake_get
            prs.time.sleep = lambda seconds: None

            with tempfile.TemporaryDirectory(prefix="arxiv-retry-test-") as temp_dir:
                pdf_path = prs._download_arxiv_pdf("2606.24020", Path(temp_dir), timeout=5)
                pdf_bytes = pdf_path.read_bytes()
        finally:
            prs.requests.get = original_get
            prs.time.sleep = original_sleep

        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(calls[0].endswith("/pdf/2606.24020.pdf"))
        self.assertTrue(calls[1].endswith("/pdf/2606.24020"))
        self.assertEqual(pdf_bytes, b"%PDF-1.4\n%ok\n%%EOF\n")

    def test_pdf_download_reports_rate_limit_as_actionable_error(self):
        class Response:
            status_code = 429
            headers = {"retry-after": "120", "content-type": "text/plain"}
            content = b"Too Many Requests"
            text = "Too Many Requests"

            def raise_for_status(self):
                error = requests.HTTPError("429 Client Error: Too Many Requests")
                error.response = self
                raise error

        original_get = prs.requests.get
        original_sleep = prs.time.sleep
        try:
            prs.requests.get = lambda url, **kwargs: Response()
            prs.time.sleep = lambda seconds: None
            with tempfile.TemporaryDirectory(prefix="arxiv-429-test-") as temp_dir:
                with self.assertRaisesRegex(RuntimeError, "rate limiting.*try again"):
                    prs._download_arxiv_pdf("2606.24020", Path(temp_dir), timeout=5)
        finally:
            prs.requests.get = original_get
            prs.time.sleep = original_sleep

    def test_resolve_arxiv_candidates_caches_title_queries(self):
        calls = []

        class FakeSearch:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class FakeAuthor:
            name = "A. Author"

        class FakeResult:
            title = "You Don't Need to Run Every Eval"
            summary = "Evaluation selection for language models."
            authors = [FakeAuthor()]
            published = None
            primary_category = "cs.CL"
            entry_id = "https://arxiv.org/abs/2606.24020"

            def get_short_id(self):
                return "2606.24020v1"

        class FakeClient:
            def results(self, search):
                calls.append(search)
                return [FakeResult()]

        original_arxiv = ext.arxiv
        original_client = ext._arxiv_client
        try:
            ext.arxiv = SimpleNamespace(Search=FakeSearch)
            ext._arxiv_client = lambda: FakeClient()

            first = ext.resolve_arxiv_candidates("You Don't Need to Run Every Eval", limit=15)
            second = ext.resolve_arxiv_candidates("You Don't Need to Run Every Eval", limit=15)
        finally:
            ext.arxiv = original_arxiv
            ext._arxiv_client = original_client

        self.assertEqual(len(calls), 1)
        self.assertEqual(first[0].arxiv_id, "2606.24020v1")
        self.assertEqual(second[0].arxiv_id, "2606.24020v1")


if __name__ == "__main__":
    unittest.main()
