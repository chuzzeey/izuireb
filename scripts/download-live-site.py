from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import json
import mimetypes
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_ROOT = ROOT / "public" / "site-capture"
RAW_PAGES = CAPTURE_ROOT / "raw-pages"
PAGES_DIR = CAPTURE_ROOT / "pages"
ASSETS_DIR = CAPTURE_ROOT / "assets"
BASE_URL = "https://www.hotcshop.com"
ALLOWED_HOSTS = {"www.hotcshop.com", "hotcshop.com"}
USER_AGENT = "Mozilla/5.0 (compatible; Izuire local catalog archive)"
PAGE_DELAY = 0.2
ASSET_DELAY = 0.1
PAGE_WORKERS = 4
ASSET_WORKERS = 4
MAX_PAGES = 10000

BLOCKED_PREFIXES = (
    "/account",
    "/admin",
    "/api",
    "/cart",
    "/checkout",
    "/login",
    "/logout",
    "/orders",
    "/password",
    "/payment",
    "/profile",
    "/register",
    "/wishlist",
)
STATIC_SUFFIXES = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}
TOKEN_INPUT = re.compile(r"<input\b[^>]*\bname\s*=\s*(['\"])_token\1[^>]*>", re.I)
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
CSS_IMPORT = re.compile(r"@import\s+(['\"])(.*?)\1", re.I)


def canonical_url(value: str, base: str) -> str | None:
    absolute = urljoin(base, value.strip())
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"} or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        return None

    path = re.sub(r"/+$", "", parts.path or "/") or "/"
    query = sorted(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit(("https", "www.hotcshop.com", path, urlencode(query, doseq=True), ""))


def route_key(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def is_public_page(url: str) -> bool:
    parts = urlsplit(url)
    path = parts.path.lower()
    if Path(path).suffix.lower() in STATIC_SUFFIXES:
        return False
    return not any(path == prefix or path.startswith(prefix + "/") for prefix in BLOCKED_PREFIXES)


def public_variants(url: str) -> list[str]:
    parts = urlsplit(url)
    if "page" in dict(parse_qsl(parts.query, keep_blank_values=True)):
        return [url]
    if parts.path not in {"/", "/shop"} and not parts.path.startswith("/category/"):
        return [url]

    other_params = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "availability"]
    variants = [url]
    for availability in ("all", "available", "oversea"):
        params = sorted([*other_params, ("availability", availability)])
        variant = urlunsplit(
            ("https", "www.hotcshop.com", parts.path, urlencode(params, doseq=True), "")
        )
        if variant not in variants:
            variants.append(variant)
    return variants


def css_urls(css: str, base_url: str) -> set[str]:
    found = set()
    for match in CSS_URL.finditer(css):
        candidate = canonical_url(match.group(2), base_url)
        if candidate:
            found.add(candidate)
    for match in CSS_IMPORT.finditer(css):
        candidate = canonical_url(match.group(2), base_url)
        if candidate:
            found.add(candidate)
    return found


def srcset_urls(value: str, base_url: str) -> set[str]:
    found = set()
    for candidate in value.split(","):
        fields = candidate.strip().split()
        if fields:
            normalized = canonical_url(fields[0], base_url)
            if normalized:
                found.add(normalized)
    return found


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.page_links: set[str] = set()
        self.assets: set[str] = set()
        self.title_parts: list[str] = []
        self.in_title = False
        self.in_style = False

    def add_page_link(self, value: str | None) -> None:
        if not value:
            return
        normalized = canonical_url(value, self.base_url)
        if normalized and is_public_page(normalized):
            self.page_links.update(public_variants(normalized))

    def add_asset(self, value: str | None) -> None:
        if not value:
            return
        normalized = canonical_url(value, self.base_url)
        if normalized:
            self.assets.add(normalized)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "style":
            self.in_style = True
        if tag == "a":
            self.add_page_link(values.get("href"))
        if tag == "form":
            self.add_page_link(values.get("action"))

        if tag == "link":
            rel = set((values.get("rel") or "").lower().split())
            if rel.intersection({"stylesheet", "icon", "apple-touch-icon", "mask-icon", "preload", "modulepreload"}):
                self.add_asset(values.get("href"))
        if tag in {"img", "script", "source", "video", "audio", "track", "input"}:
            self.add_asset(values.get("src"))
        if tag == "video":
            self.add_asset(values.get("poster"))
        if tag == "meta" and (values.get("property", "").lower() in {"og:image", "og:image:url"} or values.get("name", "").lower() == "twitter:image"):
            self.add_asset(values.get("content"))

        self.assets.update(srcset_urls(values.get("srcset", ""), self.base_url))
        for attr in ("data-src", "data-lazy-src", "data-original", "data-image", "data-background"):
            self.add_asset(values.get(attr))
        self.assets.update(css_urls(values.get("style", ""), self.base_url))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "title":
            self.in_title = False
        if tag == "style":
            self.in_style = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_style:
            self.assets.update(css_urls(data, self.base_url))


def request_bytes(url: str, delay: float) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last_error: Exception | None = None
    for attempt in range(3):
        time.sleep(delay)
        try:
            with urlopen(request, timeout=35) as response:
                final_url = response.geturl()
                if (urlsplit(final_url).hostname or "").lower() not in ALLOWED_HOSTS:
                    raise RuntimeError(f"Redirected outside the live shop: {final_url}")
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read(), content_type, charset
        except HTTPError as error:
            last_error = error
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError) as error:
            last_error = error
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Request failed: {url}") from last_error


def page_filename(url: str) -> str:
    return f"{sha256(url.encode('utf-8')).hexdigest()}.html"


def asset_suffix(url: str, content_type: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix:
        return suffix
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/svg+xml":
        return ".svg"
    return mimetypes.guess_extension(content_type) or ".bin"


def asset_filename(url: str, content_type: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()
    return f"{digest}{asset_suffix(url, content_type)}"


def fetch_asset(url: str) -> tuple[str, bytes | None, str | None, str | None]:
    try:
        data, content_type, _ = request_bytes(url, ASSET_DELAY)
        destination = ASSETS_DIR / asset_filename(url, content_type)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        css_text = data.decode("utf-8", "replace") if content_type == "text/css" or urlsplit(url).path.lower().endswith(".css") else None
        return url, data if css_text is not None else None, content_type, None
    except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
        return url, None, None, str(error)


def token_input_without_value(match: re.Match[str]) -> str:
    return re.sub(r"\bvalue\s*=\s*(['\"])[^'\"]*\1", 'value=""', match.group(0), flags=re.I)


def asset_local_path(url: str, asset_types: dict[str, str]) -> str | None:
    content_type = asset_types.get(url)
    if not content_type:
        return None
    return f"/site-capture/assets/{asset_filename(url, content_type)}"


def local_or_live_url(
    value: str,
    current_url: str,
    page_routes: set[str],
    asset_types: dict[str, str],
    kind: str,
) -> str:
    original = value.strip()
    if not original or original.startswith(("#", "data:", "javascript:", "mailto:", "tel:")):
        return value

    absolute = urljoin(current_url, original)
    parts = urlsplit(absolute)
    if (parts.hostname or "").lower() == "fonts.bunny.net" and parts.path == "/css":
        return "/assets/fonts-local.css"

    normalized = canonical_url(original, current_url)
    if not normalized:
        return value

    fragment = f"#{parts.fragment}" if parts.fragment else ""
    if kind == "asset":
        local_path = asset_local_path(normalized, asset_types)
        return f"{local_path}{fragment}" if local_path else f"{normalized}{fragment}"

    key = route_key(normalized)
    if key in page_routes:
        return f"{key}{fragment}"
    return f"{normalized}{fragment}"


def rewrite_srcset(
    value: str,
    current_url: str,
    page_routes: set[str],
    asset_types: dict[str, str],
) -> str:
    if value.strip().lower().startswith("data:"):
        return value
    candidates = []
    for candidate in value.split(","):
        fields = candidate.strip().split()
        if fields:
            fields[0] = local_or_live_url(fields[0], current_url, page_routes, asset_types, "asset")
            candidates.append(" ".join(fields))
    return ", ".join(candidates)


def rewrite_css(
    css: str,
    current_url: str,
    page_routes: set[str],
    asset_types: dict[str, str],
) -> str:
    def replace_url(match: re.Match[str]) -> str:
        quote = match.group(1)
        value = match.group(2)
        rewritten = local_or_live_url(value, current_url, page_routes, asset_types, "asset")
        return f"url({quote}{rewritten}{quote})"

    css = CSS_URL.sub(replace_url, css)
    return CSS_IMPORT.sub(
        lambda match: f"@import {match.group(1)}{local_or_live_url(match.group(2), current_url, page_routes, asset_types, 'asset')}{match.group(1)}",
        css,
    )


class SnapshotRewriter(HTMLParser):
    def __init__(self, current_url: str, page_routes: set[str], asset_types: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.current_url = current_url
        self.page_routes = page_routes
        self.asset_types = asset_types
        self.output: list[str] = []
        self.in_style = False

    def rewrite_tag(self, tag: str, attrs: list[tuple[str, str | None]], raw: str) -> None:
        values = dict(attrs)
        if tag == "link":
            rel = set((values.get("rel") or "").lower().split())
            href = values.get("href") or ""
            if "preconnect" in rel and "fonts.bunny.net" in href:
                return

        for name, value in attrs:
            if value is None:
                continue
            lowered = name.lower()
            if lowered in {"src", "poster", "data-src", "data-lazy-src", "data-original", "data-image", "data-background"}:
                rewritten = local_or_live_url(value, self.current_url, self.page_routes, self.asset_types, "asset")
            elif lowered == "srcset":
                rewritten = rewrite_srcset(value, self.current_url, self.page_routes, self.asset_types)
            elif lowered == "style":
                rewritten = rewrite_css(value, self.current_url, self.page_routes, self.asset_types)
            elif lowered == "href":
                if tag == "link":
                    rewritten = local_or_live_url(value, self.current_url, self.page_routes, self.asset_types, "asset")
                elif tag == "a" or tag == "area":
                    rewritten = local_or_live_url(value, self.current_url, self.page_routes, self.asset_types, "page")
                else:
                    rewritten = value
            elif lowered in {"action", "formaction"}:
                normalized = canonical_url(value, self.current_url)
                fragment = urlsplit(value).fragment
                rewritten = f"{normalized}#{fragment}" if normalized and fragment else normalized or value
            elif lowered == "content" and (
                values.get("property", "").lower() in {"og:image", "og:image:url"}
                or values.get("name", "").lower() == "twitter:image"
            ):
                rewritten = local_or_live_url(value, self.current_url, self.page_routes, self.asset_types, "asset")
            else:
                rewritten = value

            if rewritten == value:
                continue
            pattern = re.compile(r"(\b" + re.escape(name) + r"\s*=\s*)(['\"])(.*?)\2", re.I | re.S)
            raw, count = pattern.subn(
                lambda match: match.group(1) + match.group(2) + escape(rewritten, quote=True) + match.group(2),
                raw,
                count=1,
            )
            if count == 0:
                raise RuntimeError(f"Could not rewrite {name} attribute in {tag}")
        if tag == "form" or (
            tag == "a"
            and values.get("href")
            and not values["href"].strip().startswith(("#", "javascript:"))
            and values.get("target") in {None, "_self"}
        ):
            target_pattern = re.compile(r"(\btarget\s*=\s*)(['\"])(.*?)\2", re.I | re.S)
            if "target" in values:
                raw, count = target_pattern.subn(r'\1\2_top\2', raw, count=1)
                if count == 0:
                    raise RuntimeError(f"Could not update target attribute in {tag}")
            else:
                raw = re.sub(r"/?>$", lambda match: ' target="_top"' + match.group(0), raw)
        self.output.append(raw)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.rewrite_tag(tag, attrs, self.get_starttag_text())
        if tag == "style":
            self.in_style = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.rewrite_tag(tag, attrs, self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        self.output.append(f"</{tag}>")
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        self.output.append(
            rewrite_css(data, self.current_url, self.page_routes, self.asset_types)
            if self.in_style
            else data
        )

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.output.append(f"<!{decl}>")

    def unknown_decl(self, data: str) -> None:
        self.output.append(f"<![{data}]>")


def fetch_page(url: str) -> tuple[str, str, str] | tuple[str, None, str]:
    try:
        data, content_type, charset = request_bytes(url, PAGE_DELAY)
        if content_type != "text/html":
            return url, None, f"Unexpected page content type: {content_type}"
        return url, data.decode(charset, "replace"), ""
    except HTTPError as error:
        return url, None, f"HTTP {error.code}"
    except (URLError, TimeoutError, RuntimeError) as error:
        return url, None, str(error)


def main() -> None:
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    RAW_PAGES.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    seeds = [
        f"{BASE_URL}/",
        f"{BASE_URL}/shop",
        f"{BASE_URL}/category/accessories?availability=all",
        f"{BASE_URL}/product/2016year-toyota-corolla-16l",
    ]
    queue = list(dict.fromkeys(url for seed in seeds for url in public_variants(canonical_url(seed, BASE_URL) or seed)))
    queued = set(queue)
    page_titles: dict[str, str] = {}
    page_assets: set[str] = set()
    failures: list[str] = []
    cursor = 0

    while cursor < len(queue):
        if len(page_titles) >= MAX_PAGES:
            raise RuntimeError(f"Stopped at the safety limit of {MAX_PAGES} pages; increase MAX_PAGES to continue.")
        batch = queue[cursor : cursor + PAGE_WORKERS]
        cursor += len(batch)
        with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
            results = list(pool.map(fetch_page, batch))

        for page_url, html, error in results:
            if html is None:
                failures.append(f"page {page_url}: {error}")
                print(f"Skipped {page_url}: {error}", file=sys.stderr, flush=True)
                continue

            parser = PageParser(page_url)
            parser.feed(html)
            parser.close()
            title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
            page_titles[page_url] = title or urlsplit(page_url).path.rsplit("/", 1)[-1].replace("-", " ").title() or "Izuire Shop"
            page_assets.update(parser.assets)
            (RAW_PAGES / page_filename(page_url)).write_text(html, encoding="utf-8")

            for link in parser.page_links:
                for candidate in public_variants(link):
                    if candidate not in queued:
                        queued.add(candidate)
                        queue.append(candidate)

            if len(page_titles) % 20 == 0:
                print(f"Captured {len(page_titles)} pages; queued {len(queue) - cursor} more", flush=True)

    asset_queue = list(page_assets)
    downloaded_assets: dict[str, str] = {}
    css_contents: dict[str, str] = {}
    while asset_queue:
        batch, asset_queue = asset_queue[:1000], asset_queue[1000:]
        with ThreadPoolExecutor(max_workers=ASSET_WORKERS) as pool:
            futures = [pool.submit(fetch_asset, url) for url in batch]
            for future in as_completed(futures):
                url, css_text, content_type, error = future.result()
                if error:
                    failures.append(f"asset {url}: {error}")
                    print(f"Skipped asset {url}: {error}", file=sys.stderr)
                    continue
                assert content_type is not None
                downloaded_assets[url] = content_type
                if css_text is not None:
                    css_contents[url] = css_text.decode("utf-8", "replace") if isinstance(css_text, bytes) else css_text
                    for child in css_urls(css_contents[url], url):
                        if child not in downloaded_assets and child not in asset_queue:
                            asset_queue.append(child)
        if len(downloaded_assets) and len(downloaded_assets) % 50 < len(batch):
            print(f"Downloaded {len(downloaded_assets)} assets")

    page_routes = {route_key(url) for url in page_titles}
    for url, css in css_contents.items():
        path = ASSETS_DIR / asset_filename(url, downloaded_assets[url])
        path.write_text(rewrite_css(css, url, page_routes, downloaded_assets), encoding="utf-8")

    manifest_pages: dict[str, dict[str, str]] = {}
    for url, title in page_titles.items():
        html = (RAW_PAGES / page_filename(url)).read_text(encoding="utf-8")
        html = TOKEN_INPUT.sub(token_input_without_value, html)
        html = re.sub(
            r'(<meta\b[^>]*\bname\s*=\s*["\']csrf-token["\'][^>]*\bcontent\s*=\s*["\'])[^"\']*(["\'][^>]*>)',
            r'\1\2',
            html,
            flags=re.I,
        )
        rewriter = SnapshotRewriter(url, page_routes, downloaded_assets)
        rewriter.feed(html)
        rewriter.close()
        filename = page_filename(url)
        (PAGES_DIR / filename).write_text("".join(rewriter.output), encoding="utf-8")
        manifest_pages[route_key(url)] = {
            "file": f"/site-capture/pages/{filename}",
            "title": title,
        }
        (RAW_PAGES / filename).unlink(missing_ok=True)

    RAW_PAGES.rmdir()
    manifest = {"source": BASE_URL, "pages": manifest_pages}
    (CAPTURE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    categories = sum(1 for url in page_titles if urlsplit(url).path.startswith("/category/"))
    products = sum(1 for url in page_titles if urlsplit(url).path.startswith("/product/"))
    print(f"Complete: {len(page_titles)} pages ({categories} category, {products} product), {len(downloaded_assets)} assets.")
    if failures:
        print(f"Warning: {len(failures)} page/asset requests failed; see messages above.", file=sys.stderr)
    print(f"Manifest: {CAPTURE_ROOT / 'manifest.json'}")


if __name__ == "__main__":
    main()
