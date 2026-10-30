"""Public invoice corpora used to measure extraction on documents we did not create.

Files are downloaded at pinned commits and verified against SHA-256 digests in `datasets.lock.json`,
so results are reproducible. Nothing from these corpora is committed to this repository.

Splits: the parser was developed against the `dev` documents only. `test` documents come from
different producers and were held out, so their score is the honest estimate for unseen layouts.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
LOCK = HERE / "datasets.lock.json"

INVOICE2DATA = {
    "repo": "invoice-x/invoice2data",
    "commit": "643eec75dfaa15d7fbbcf7f93017f213d1c3e9fa",
    "license": "MIT",
    "files": [
        "AmazonWebServices",
        "AzureInterior",
        "FlipkartInvoice",
        "NetpresseInvoice",
        "QualityHosting",
        "SammyMaystoneLinesTest",
        "coolblue1",
        "coolblue2",
        "free_fiber",
        "oyo",
        "saeco",
    ],
}
ZUGFERD = {
    "repo": "ZUGFeRD/corpus",
    "commit": "82e886fb21369e3e83c1e97170a4ff406deceee7",
    "license": "Apache-2.0",
    "prefixes": ["ZUGFeRDv2/correct/", "XML-Rechnung/"],
}
# Producers whose documents were never looked at while developing the parser.
HELD_OUT_PRODUCERS = {"symtrax", "FNFE-factur-x-examples", "Mustangproject", "PHP_@gpFacturX"}


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    corpus: str
    producer: str
    split: str
    url: str
    sha256: str
    truth_url: str | None = None
    truth_sha256: str | None = None

    @property
    def path(self) -> Path:
        return CACHE / self.corpus / f"{self.id}.pdf"

    @property
    def truth_path(self) -> Path:
        return CACHE / self.corpus / f"{self.id}.json"


def _raw(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.parse.quote(path)}"


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return bytes(response.read())


def _producer(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "XML-Rechnung":
        return "XML-Rechnung"
    return parts[2]  # ZUGFeRDv2/correct/<producer>/...


def build_lock() -> list[Document]:
    """Resolve the document list from the pinned commits and record digests (maintainers only)."""
    documents: list[Document] = []
    for name in INVOICE2DATA["files"]:
        pdf_url = _raw(INVOICE2DATA["repo"], INVOICE2DATA["commit"], f"tests/compare/{name}.pdf")
        json_url = _raw(INVOICE2DATA["repo"], INVOICE2DATA["commit"], f"tests/compare/{name}.json")
        documents.append(
            Document(
                id=name,
                corpus="invoice2data",
                producer=name,
                split="dev",
                url=pdf_url,
                sha256=hashlib.sha256(_download(pdf_url)).hexdigest(),
                truth_url=json_url,
                truth_sha256=hashlib.sha256(_download(json_url)).hexdigest(),
            )
        )
    tree_url = f"https://api.github.com/repos/{ZUGFERD['repo']}/git/trees/{ZUGFERD['commit']}?recursive=1"
    tree = json.loads(_download(tree_url))["tree"]
    paths = sorted(
        item["path"]
        for item in tree
        if item["path"].lower().endswith(".pdf") and item["path"].startswith(tuple(ZUGFERD["prefixes"]))
    )

    def lock(index_path: tuple[int, str]) -> Document:
        index, path = index_path
        url = _raw(ZUGFERD["repo"], ZUGFERD["commit"], path)
        producer = _producer(path)
        return Document(
            id=f"z{index:03d}",
            corpus="zugferd",
            producer=producer,
            split="test" if producer in HELD_OUT_PRODUCERS else "dev",
            url=url,
            sha256=hashlib.sha256(_download(url)).hexdigest(),
        )

    with ThreadPoolExecutor(8) as pool:
        documents += list(pool.map(lock, enumerate(paths)))
    LOCK.write_text(json.dumps([asdict(d) for d in documents], indent=1) + "\n", encoding="utf-8")
    return documents


def load() -> list[Document]:
    return [Document(**raw) for raw in json.loads(LOCK.read_text(encoding="utf-8"))]


def fetch(documents: list[Document]) -> None:
    """Download anything missing from the cache and verify every digest."""

    def one(document: Document) -> None:
        for url, digest, path in (
            (document.url, document.sha256, document.path),
            (document.truth_url, document.truth_sha256, document.truth_path),
        ):
            if url is None or digest is None:
                continue
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                data = _download(url)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise RuntimeError(f"checksum mismatch for {url}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, documents))
