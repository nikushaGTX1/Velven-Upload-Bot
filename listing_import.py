import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"myhome.ge", "www.myhome.ge", "home.ss.ge", "ss.ge", "www.ss.ge"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


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


def _match(text, patterns):
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found:
            return found.group(1).strip()
    return ""


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
        "district": _find(objects, ["district", "districtName", "district_name", "subdistrictName"]) or _match(combined, [r"(საბურთალო|ვაკე|ისანი|სამგორი|გლდანი|დიდუბე|ჩუღურეთი|ნაძალადევი|მთაწმინდა|კრწანისი)"]),
        "size": _find(objects, ["area", "totalArea", "total_area", "space"]) or _match(combined, [r"([\d.,]+)\s*(?:მ²|m²|sq\.?\s*m)"]),
        "floor": _find(objects, ["floor", "floorNumber", "floor_number"]),
        "building": _find(objects, ["buildingStatus", "building_status", "condition"]),
        "rooms": _find(objects, ["rooms", "roomCount", "roomsCount", "room_count"]) or _match(combined, [r"(\d+)\s*(?:ოთახიანი|ოთახი)"]),
        "bedrooms": _find(objects, ["bedrooms", "bedroomCount", "bedroomsCount", "bedroom_count"]),
        "elevator": _find(objects, ["elevators", "elevatorCount", "elevator_count"]),
        "price": _find(objects, ["price", "priceUsd", "price_usd"]),
        "pets": _find(objects, ["pets", "petsAllowed", "pets_allowed"]),
    }
    total_floors = _find(objects, ["totalFloors", "floors", "total_floors"])
    if values["floor"] and total_floors and "/" not in values["floor"]:
        values["floor"] += f"/{total_floors}"
    images = []
    for tag in soup.select('meta[property="og:image"], meta[name="twitter:image"], img'):
        source = tag.get("content") or tag.get("src") or tag.get("data-src")
        if source and source.startswith("http") and source not in images:
            images.append(source)
    for obj in objects:
        for key, value in obj.items():
            if any(word in key.casefold() for word in ("image", "photo")):
                candidates = value if isinstance(value, list) else [value]
                for candidate in candidates:
                    if isinstance(candidate, str) and candidate.startswith("http") and candidate not in images:
                        images.append(candidate)
                    elif isinstance(candidate, dict):
                        source = candidate.get("url") or candidate.get("src")
                        if isinstance(source, str) and source.startswith("http") and source not in images:
                            images.append(source)
    return values, images[:10]


def download_images(urls: list[str], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, url in enumerate(urls, 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                continue
            path = folder / f"imported-{number}.jpg"
            path.write_bytes(response.content)
            paths.append(path)
        except requests.RequestException:
            continue
    return paths
