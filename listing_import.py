import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

ALLOWED_HOSTS = {"myhome.ge", "www.myhome.ge", "home.ss.ge", "ss.ge", "www.ss.ge"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

DISTRICTS_IN_URL = {
    "saburtalo": "saburtalo", "saburtaloze": "saburtalo",
    "vake": "vake", "vakeshi": "vake",
    "isani": "isani", "isanshi": "isani",
    "samgori": "samgori", "samgorshi": "samgori",
    "gldani": "gldani", "gldanshi": "gldani",
    "didube": "didube", "didubeshi": "didube",
    "chugureti": "chugureti", "chuguretshi": "chugureti",
    "nadzaladevi": "nadzaladevi", "nadzaladevshi": "nadzaladevi",
    "mtatsminda": "mtatsminda", "mtatsmindaze": "mtatsminda",
    "krtsanisi": "krtsanisi", "krtsanisshi": "krtsanisi",
}


def supported_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>()]+", text or "")
    if not match:
        return None
    url = match.group(0).rstrip(".,])")
    return url if urlparse(url).hostname in ALLOWED_HOSTS else None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _find(objects, names):
    names = {name.casefold() for name in names}
    for obj in objects:
        for key, value in obj.items():
            if key.casefold() in names and isinstance(value, (str, int, float)) and str(value).strip():
                return str(value).strip()
    return ""


def _find_number(objects, names):
    value = _find(objects, names)
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return match.group(0) if match else ""


def _match(text, patterns):
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found:
            return found.group(1).strip()
    return ""


def _district_from_url(url: str) -> str:
    slug = urlparse(url).path.casefold()
    parts = set(filter(None, re.split(r"[^a-z]+", slug)))
    for token, district in DISTRICTS_IN_URL.items():
        if token in parts:
            return district
    return ""


def _rooms_from_url(url: str) -> str:
    match = re.search(r"/(?:[^/?#]*-)?(\d+)-otaxiani(?:-|/|$)", urlparse(url).path.casefold())
    return match.group(1) if match else ""


def _image_candidates(value, preferred=False):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _image_candidates(child, preferred or any(word in key.casefold() for word in ("image", "photo", "gallery")))
    elif isinstance(value, list):
        for child in value:
            yield from _image_candidates(child, preferred)
    elif preferred and isinstance(value, str):
        for candidate in re.findall(r"https?://[^\s\"'<>]+", value.replace("\\/", "/")):
            yield candidate


def _add_image(images: list[str], source: str | None, page_url: str):
    if not source:
        return
    source = source.strip().replace("\\/", "/")
    source = source.split()[0]
    absolute = urljoin(page_url, source)
    lowered = absolute.casefold()
    if urlparse(absolute).scheme not in {"http", "https"}:
        return
    if any(word in lowered for word in ("logo", "icon", "avatar", "banner", "marker", "placeholder", ".svg")):
        return
    if absolute not in images:
        images.append(absolute)


def scrape_listing(url: str) -> tuple[dict[str, str], list[str]]:
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    if urlparse(response.url).hostname not in ALLOWED_HOSTS:
        raise ValueError("Listing redirected to an unsupported website")
    soup = BeautifulSoup(response.text, "html.parser")
    objects = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip().startswith(("{", "[")):
            continue
        try:
            objects.extend(_walk(json.loads(raw)))
        except (ValueError, TypeError):
            continue
    text = " ".join(soup.stripped_strings)
    title = (soup.title.string if soup.title and soup.title.string else "")
    combined = f"{title} {text}"
    values = {
        "city": _find(objects, ["city", "cityName", "city_name"]) or _match(combined, [r"(თბილისი|ბათუმი|ქუთაისი|რუსთავი|Tbilisi|Batumi|Kutaisi|Rustavi)"]),
        "district": _district_from_url(url) or _match(combined, [r"(საბურთალო|ვაკე|ისანი|სამგორი|გლდანი|დიდუბე|ჩუღურეთი|ნაძალადევი|მთაწმინდა|კრწანისი)"]) or _find(objects, ["districtName", "district_name", "subdistrictName"]),
        "size": _find_number(objects, ["area", "totalArea", "total_area", "space"]) or _match(combined, [r"([\d.,]+)\s*(?:მ²|m²|sq\.?\s*m)"]),
        "floor": _find_number(objects, ["floor", "floorNumber", "floor_number"]),
        "building": _find(objects, ["buildingStatus", "building_status", "condition"]),
        "rooms": _rooms_from_url(url) or _find_number(objects, ["rooms", "roomCount", "roomsCount", "room_count"]) or _match(combined, [r"(\d+)\s*(?:ოთახიანი|ოთახი|ოთახები)", r"(?:ოთახები|ოთახი)\s*[:\-]?\s*(\d+)"]),
        "bedrooms": _find_number(objects, ["bedrooms", "bedroomCount", "bedroomsCount", "bedroom_count"]) or _match(combined, [r"(\d+)\s*(?:საძინებელი|საძინებლები)", r"(?:საძინებლები|საძინებელი)\s*[:\-]?\s*(\d+)"]),
        "elevator": _find_number(objects, ["elevators", "elevatorCount", "elevator_count"]),
        "price": _find_number(objects, ["price", "priceUsd", "price_usd"]),
        "pets": _find(objects, ["pets", "petsAllowed", "pets_allowed"]),
    }
    total_floors = _find_number(objects, ["totalFloors", "floors", "total_floors"])
    if values["floor"] and total_floors and "/" not in values["floor"]:
        values["floor"] += f"/{total_floors}"
    images = []
    # Gallery data is normally embedded in the sites' application JSON and
    # contains the complete set, unlike og:image which contains only one.
    for candidate in _image_candidates(objects):
        _add_image(images, candidate, response.url)
    for tag in soup.select('meta[property="og:image"], meta[name="twitter:image"], img'):
        for attribute in ("content", "data-src", "data-lazy-src", "src"):
            _add_image(images, tag.get(attribute), response.url)
        srcset = tag.get("srcset") or tag.get("data-srcset")
        if srcset:
            for item in srcset.split(","):
                _add_image(images, item.strip().split()[0], response.url)
    return values, images


def _image_fingerprint(image: Image.Image) -> int:
    """Create a fingerprint that is stable across resized copies of a photo."""
    normalized = ImageOps.exif_transpose(image).convert("L").resize((17, 16))
    pixels = list(normalized.getdata())
    fingerprint = 0
    for row in range(16):
        offset = row * 17
        for column in range(16):
            fingerprint = (fingerprint << 1) | (
                pixels[offset + column] > pixels[offset + column + 1]
            )
    return fingerprint


def download_images(urls: list[str], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    fingerprints = []
    for url in urls:
        if len(paths) >= 10:
            break
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                continue
            image = Image.open(BytesIO(response.content))
            if image.width < 300 or image.height < 200:
                continue
            fingerprint = _image_fingerprint(image)
            if any((fingerprint ^ existing).bit_count() <= 8 for existing in fingerprints):
                continue
            fingerprints.append(fingerprint)
            path = folder / f"imported-{len(paths) + 1}.jpg"
            path.write_bytes(response.content)
            paths.append(path)
        except (requests.RequestException, OSError):
            continue
    return paths
