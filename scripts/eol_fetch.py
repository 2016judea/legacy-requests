"""Fetch an OEM notice URL once, keep its text layer under data/eol/cache/<sha1>.txt.
PDFs go through pdftotext; HTML is stripped to text. Cached forever, like data/cache."""
import hashlib, html, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/eol/cache"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>|</div>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def fetch(url: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if out.exists() and out.stat().st_size > 200:
        return out.read_text(errors="replace")
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tmp = tf.name
    code = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", UA, "-o", tmp, "-w", "%{http_code}", url],
                          capture_output=True, text=True).stdout
    data = Path(tmp).read_bytes()
    if data[:5] == b"%PDF-":
        text = subprocess.run(["pdftotext", tmp, "-"], capture_output=True, text=True).stdout
    else:
        text = html_text(data.decode("utf-8", "replace"))
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    if code.startswith("2") and len(text.strip()) > 200:
        out.write_text(text)
    return text


if __name__ == "__main__":
    for u in sys.argv[1:]:
        t = fetch(u)
        print(f"== {len(t):7} {u}")
