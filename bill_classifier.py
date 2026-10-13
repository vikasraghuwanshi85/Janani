"""Read bill images, then recognize Aadeshwar Fuels in Hindi or English.

Only image pixels are evidence. An OCR/setup failure is UNKNOWN and retryable;
it must never silently route a potentially unreadable fuel receipt as maintenance.
This module does not extract dates, odometers, quantities, or monetary amounts.
"""

import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata


CLASSIFIER_VERSION = "aadeshwar-image-v1"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
EXACT_CONFIDENCE = 50.0
FUZZY_CONFIDENCE = 80.0
NAME_VARIANTS = (
    "आदेश्वर", "आदेशवर", "आदेश्वार", "आदेस्वर", "आदेष्वर",
    "आदिश्वर", "आदीश्वर", "आदेश्वेर", "aadeshwar", "aadeswar", "adeshwar", "adeswar",
)
FUEL_VARIANTS = ("फ्यूल्स", "फ्यूल", "फ्यूलस", "फ्युल्स", "फ्युल", "fuels", "fuel")


def _normalise_word(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", value)
    # Preserve Devanagari combining vowel signs: removing all marks changes names.
    return "".join(ch for ch in value if ch.isalpha() or unicodedata.category(ch).startswith("M"))


_NAMES = frozenset(_normalise_word(word) for word in NAME_VARIANTS)
_FUELS = frozenset(_normalise_word(word) for word in FUEL_VARIANTS)


def _one_edit_apart(left, right):
    """True for at most one insertion, deletion, or replacement; no substring match."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    if len(left) > len(right):
        left, right = right, left
    i = j = edits = 0
    while i < len(left) and j < len(right):
        if left[i] != right[j]:
            edits += 1
            j += 1
            if edits > 1:
                return False
        else:
            i += 1
            j += 1
    return True


def _word_kind(word, variants):
    if word in variants:
        return "exact"
    if len(word) >= 5 and any(_one_edit_apart(word, candidate) for candidate in variants):
        return "fuzzy"
    return ""


def _confidence(value):
    try:
        number = float(value)
        return max(0.0, min(100.0, number)) if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _records(tokens):
    result = []
    for token in tokens:
        text = str(token.get("text", "")).strip()
        if not text:
            continue
        confidence = _confidence(token.get("confidence", token.get("conf", 0)))
        # Vision and test adapters may provide a phrase rather than one TSV word.
        for word in re.findall(r"[^\s,;:/|()\[\]{}]+", text):
            normal = _normalise_word(word)
            if normal:
                result.append({
                    "text": normal, "confidence": confidence,
                    "block": token.get("block", token.get("block_num", "")),
                    "paragraph": token.get("paragraph", token.get("par_num", "")),
                    "line": token.get("line", token.get("line_num", "")),
                })
    return result


def match_bill_tokens(tokens):
    """Classify OCR word records conservatively, with confidence-aware phrase matching."""
    words = _records(tokens)
    suspicious = False
    best_match = 0.0
    for i, name in enumerate(words):
        # Recognize a joined heading only when both parts match the complete token.
        for candidate in _NAMES:
            for fuel in _FUELS:
                if name["text"] == candidate + fuel:
                    if name["confidence"] >= EXACT_CONFIDENCE:
                        best_match = max(best_match, name["confidence"])
                    else:
                        suspicious = True
        name_kind = _word_kind(name["text"], _NAMES)
        if not name_kind:
            continue
        for j in range(max(0, i - 4), min(len(words), i + 5)):
            if i == j:
                continue
            fuel = words[j]
            fuel_kind = _word_kind(fuel["text"], _FUELS)
            if not fuel_kind:
                continue
            # Do not associate unrelated merchant names and product lines in other blocks.
            if name["block"] and fuel["block"] and name["block"] != fuel["block"]:
                continue
            if name["paragraph"] and fuel["paragraph"] and name["paragraph"] != fuel["paragraph"]:
                continue
            score = min(name["confidence"], fuel["confidence"])
            required = FUZZY_CONFIDENCE if "fuzzy" in (name_kind, fuel_kind) else EXACT_CONFIDENCE
            if score >= required:
                best_match = max(best_match, score)
            else:
                suspicious = True
    if best_match:
        return {"bill_category": "FUEL", "confidence": round(best_match, 2),
                "reason": "Aadeshwar Fuels merchant heading recognized in the image", "review_required": False}
    if suspicious:
        return {"bill_category": "UNKNOWN", "confidence": 0.0,
                "reason": "Possible Aadeshwar Fuels heading has low OCR confidence; review the image", "review_required": True}
    legible = [word for word in words if len(word["text"]) >= 2 and word["confidence"] >= 40]
    chars = sum(len(word["text"]) for word in legible)
    average = sum(word["confidence"] * len(word["text"]) for word in legible) / max(1, chars)
    if len(legible) >= 4 and chars >= 16 and average >= 55:
        return {"bill_category": "MAINTENANCE", "confidence": round(average, 2),
                "reason": "Readable image text contains no recognized Aadeshwar Fuels heading", "review_required": False}
    return {"bill_category": "UNKNOWN", "confidence": round(average, 2),
            "reason": "Image text is empty or too uncertain to classify; review or resend a clearer image", "review_required": True}


def _image_bytes(image_data):
    if isinstance(image_data, bytes):
        data = image_data
    else:
        value = str(image_data or "").strip()
        if value.startswith("data:"):
            if ";base64," not in value[:100]:
                raise ValueError("Bill image must be base64 encoded")
            value = value.split(",", 1)[1]
        if len(value) > (MAX_IMAGE_BYTES * 4 // 3) + 4:
            raise ValueError("Bill image is larger than 20 MB")
        data = base64.b64decode(value, validate=True)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Bill image is empty or larger than 20 MB")
    return data


def _result(category="UNKNOWN", reason="", **fields):
    result = {"bill_category": category, "reason": reason, "ocr_engine": "",
              "confidence": 0.0, "review_required": category == "UNKNOWN",
              "classifier_version": CLASSIFIER_VERSION, "cache_hit": False}
    result.update(fields)
    return result


def _load_cache(path, key):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            entry = json.load(handle).get(key)
        if isinstance(entry, dict) and entry.get("bill_category") in ("FUEL", "MAINTENANCE"):
            return dict(entry, cache_hit=True)
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _save_cache(path, key, result):
    if not path:
        return
    temporary = ""
    try:
        try:
            with open(path, encoding="utf-8") as handle:
                cached = json.load(handle)
            if not isinstance(cached, dict):
                cached = {}
        except (OSError, ValueError):
            cached = {}
        cached[key] = dict(result)
        cached = dict(list(cached.items())[-4000:])
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, delete=False) as handle:
            temporary = handle.name
            json.dump(cached, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    except OSError:
        # A cache failure must not change classification or acknowledge an upload.
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _tesseract_executable(config):
    configured = str(config.get("bill_ocr_tesseract", "") or os.environ.get("JANANI_TESSERACT", "")).strip()
    if configured:
        expanded = os.path.expanduser(os.path.expandvars(configured))
        found = expanded if os.path.isfile(expanded) else shutil.which(expanded)
        if not found:
            raise RuntimeError("Configured Tesseract executable was not found")
        return found
    found = shutil.which("tesseract")
    if found:
        return found
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable, "")
        candidate = os.path.join(root, "Tesseract-OCR", "tesseract.exe") if root else ""
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError("Tesseract is not installed; install Tesseract with Hindi and English languages or configure bill_ocr_tesseract")


def _tesseract_environment(config):
    environment = os.environ.copy()
    tessdata = str(config.get("bill_ocr_tessdata_dir", "")).strip()
    if tessdata:
        environment["TESSDATA_PREFIX"] = os.path.expanduser(os.path.expandvars(tessdata))
    return environment


def _tesseract_tokens(executable, image_path, psm, environment, timeout):
    completed = subprocess.run(
        [executable, image_path, "stdout", "-l", "hin+eng", "--psm", str(psm), "-c", "tessedit_create_tsv=1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise RuntimeError("Tesseract could not read this image (exit %s)" % completed.returncode)
    tokens = []
    for row in csv.DictReader(io.StringIO(completed.stdout), delimiter="\t"):
        if row.get("level") == "5" and row.get("text", "").strip():
            tokens.append(row)
    return tokens


def _tesseract_image(data, config):
    try:
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    except ImportError as error:
        raise RuntimeError("Pillow is missing; install the project's requirements.txt") from error
    executable = _tesseract_executable(config)
    environment = _tesseract_environment(config)
    timeout = min(60.0, max(5.0, float(config.get("bill_ocr_timeout", 20))))
    installed = subprocess.run([executable, "--list-langs"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=environment,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    languages = set(installed.stdout.splitlines())
    if installed.returncode or not {"hin", "eng"}.issubset(languages):
        raise RuntimeError("Tesseract requires both hin.traineddata and eng.traineddata; English-only OCR cannot classify Hindi fuel headings")
    try:
        with Image.open(io.BytesIO(data)) as loaded:
            if loaded.width * loaded.height > MAX_IMAGE_PIXELS:
                raise ValueError("Bill image dimensions exceed the 32 MP limit")
            image = ImageOps.exif_transpose(loaded).convert("RGB")
    except (OSError, ValueError) as error:
        raise RuntimeError("Bill bytes are not a readable image: %s" % error) from error
    if min(image.size) < 40:
        raise RuntimeError("Bill image is too small for reliable OCR")
    # Preserve a native-size pass: interpolation can turn Devanagari conjuncts
    # into shapes the mixed Hindi/English recognizer mistakes for Latin letters.
    native = ImageOps.grayscale(image)
    if max(native.size) > 3000:
        native.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
    scale = min(2.5, 2400.0 / max(image.size))
    if scale != 1:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    grayscale = ImageOps.grayscale(image)
    enhanced = ImageEnhance.Contrast(ImageOps.autocontrast(grayscale)).enhance(1.5).filter(ImageFilter.UnsharpMask(radius=1, percent=120))
    heading = enhanced.crop((0, 0, enhanced.width, max(40, round(enhanced.height * .45))))
    candidates = [(native, 3), (heading, 6), (enhanced, 11)]
    results = []
    failed = []
    with tempfile.TemporaryDirectory(prefix="janani-ocr-") as directory:
        def read_candidate(candidate, psm, index):
            path = os.path.join(directory, "pass-%s.png" % index)
            candidate.save(path)
            return match_bill_tokens(_tesseract_tokens(executable, path, psm, environment, timeout))
        for index, (candidate, psm) in enumerate(candidates):
            try:
                result = read_candidate(candidate, psm, index)
                results.append(result)
                if result["bill_category"] == "FUEL":
                    return result
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                failed.append(type(error).__name__)
        # Rotation is useful when the whole receipt is unreadable. Avoid multiplying
        # work for ordinary receipts that already have legible text in three passes.
        if not any(result["bill_category"] == "MAINTENANCE" for result in results):
            for index, angle in enumerate((90, 270, 180), start=3):
                try:
                    result = read_candidate(native.rotate(angle, expand=True), 11, index)
                    results.append(result)
                    if result["bill_category"] == "FUEL":
                        return result
                except (RuntimeError, subprocess.TimeoutExpired) as error:
                    failed.append(type(error).__name__)
    if any("Possible Aadeshwar" in result["reason"] for result in results):
        return _result(reason="Possible Aadeshwar Fuels heading remains uncertain after OCR passes", review_required=True)
    maintenance = [result for result in results if result["bill_category"] == "MAINTENANCE"]
    if maintenance and not failed:
        return max(maintenance, key=lambda result: result["confidence"])
    if failed:
        return _result(reason="At least one OCR pass failed or timed out; retry or review this image")
    return _result(reason="Image remained unreadable after contrast, header, and rotation OCR passes; resend a clearer image")


def _google_vision_image(data, config):
    """Optional paid cloud OCR; image transfer happens only when explicitly selected."""
    key = str(config.get("bill_ocr_google_api_key", "") or os.environ.get("JANANI_GOOGLE_VISION_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("Google Vision was selected but no bill_ocr_google_api_key is configured")
    import requests
    response = requests.post("https://vision.googleapis.com/v1/images:annotate", params={"key": key},
                             json={"requests": [{"image": {"content": base64.b64encode(data).decode("ascii")},
                                   "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                                   "imageContext": {"languageHints": ["hi", "en"]}}]}, timeout=60)
    if response.status_code != 200:
        raise RuntimeError("Google Vision OCR failed (HTTP %s); check the enabled API, billing, and credentials" % response.status_code)
    payload = response.json()
    answers = payload.get("responses", [])
    if not answers or "error" in answers[0]:
        raise RuntimeError("Google Vision returned an OCR error; check the API configuration")
    tokens = []
    for page_index, page in enumerate(answers[0].get("fullTextAnnotation", {}).get("pages", [])):
        for block_index, block in enumerate(page.get("blocks", [])):
            for para_index, paragraph in enumerate(block.get("paragraphs", [])):
                for word in paragraph.get("words", []):
                    text = "".join(symbol.get("text", "") for symbol in word.get("symbols", []))
                    tokens.append({"text": text, "confidence": _confidence(word.get("confidence", 0) * 100),
                                   "block": "%s:%s" % (page_index, block_index), "paragraph": para_index + 1})
    return match_bill_tokens(tokens)


def classify_bill_image(image_data, config=None, cache_path=None):
    """Classify one image; never throw or mistake an OCR failure for MAINTENANCE.

    Config keys: bill_ocr_engine ('tesseract', default, or 'google_vision'),
    bill_ocr_tesseract, bill_ocr_tessdata_dir, bill_ocr_timeout,
    bill_ocr_google_api_key. A Google Vision image request requires explicit selection.
    UNKNOWN is never cached or acknowledged and can be retried next run.
    """
    config = config or {}
    engine = str(config.get("bill_ocr_engine", "tesseract")).strip().lower()
    try:
        data = _image_bytes(image_data)
    except (ValueError, TypeError) as error:
        return _result(reason="Invalid bill image data: %s" % error, ocr_engine=engine)
    digest = hashlib.sha256(data).hexdigest()
    fingerprint = hashlib.sha256(json.dumps({key: str(config.get(key, "")) for key in (
        "bill_ocr_engine", "bill_ocr_tesseract", "bill_ocr_tessdata_dir"
    )}, sort_keys=True).encode()).hexdigest()[:12]
    key = CLASSIFIER_VERSION + ":" + fingerprint + ":" + digest
    cached = _load_cache(cache_path, key)
    if cached:
        return cached
    try:
        if engine == "tesseract":
            classified = _tesseract_image(data, config)
        elif engine == "google_vision":
            classified = _google_vision_image(data, config)
        else:
            raise RuntimeError("Unsupported bill_ocr_engine; choose tesseract or google_vision")
        result = _result()
        result.update(classified)
        result.update(ocr_engine=engine, image_hash=digest)
    except Exception as error:
        # Do not expose API keys, request URLs, or raw OCR text in diagnostics.
        if isinstance(error, (RuntimeError, ValueError, subprocess.TimeoutExpired)):
            reason = str(error) if not isinstance(error, subprocess.TimeoutExpired) else "OCR engine timed out; retry this image"
        else:
            reason = "OCR failed (%s); retry or review this image" % type(error).__name__
        result = _result(reason=reason, ocr_engine=engine, image_hash=digest)
    if result["bill_category"] in ("FUEL", "MAINTENANCE"):
        _save_cache(cache_path, key, result)
    return result
