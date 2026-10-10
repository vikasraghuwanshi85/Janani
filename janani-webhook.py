"""
JANANI FLEET - V78 - FIXED FUEL NOT PUSHING + DEBUG MODE
- New fuel entry not pushing? V78 shows WHY
- Added --force flag to force push even if in history
- Added detailed fuel debug logging
- Fixed fuel parsing edge cases

Usage:
python janani-webhook.py --check-webhook
python janani-webhook.py --days 7 --debug-fuel
python janani-webhook.py --days 1 --force --debug-fuel

Bills always respect push history, including with --force. Bill dates come from
the caption or WhatsApp metadata; undated bills and invalid odometers are skipped.
"""

import os, re, time, requests, json, hashlib, sys, io, platform, base64, tempfile, shutil
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse


class WebhookProtocolError(RuntimeError):
    """The deployment did not return the JSON contract required for uploads."""


class WebhookPageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def webhook_json(response):
    text = response.text.lstrip('\ufeff').strip()
    if text.startswith('<'):
        page = WebhookPageText()
        page.feed(text)
        detail = re.sub(r'\s+', ' ', ' '.join(page.parts)).strip()[:600]
        host = urlparse(getattr(response, 'url', '') or '').hostname or 'webhook'
        raise WebhookProtocolError(
            f'Google returned HTML from {host}: {detail or "no readable error"}. '
            'Deploy the complete apps_script/Janani.gs as a new web-app version; '
            'check its /exec URL and access settings. History was not updated.')
    response.raise_for_status()
    try:
        result = json.loads(text)
    except ValueError:
        raise WebhookProtocolError('Webhook returned invalid JSON; history was not updated.')
    if not isinstance(result, dict):
        raise WebhookProtocolError('Webhook returned a non-object JSON response; history was not updated.')
    return result


def check_webhook():
    """Read-only deployment check; never sends report or image data."""
    parsed_url = urlparse(WEBHOOK_URL)
    if parsed_url.scheme != 'https' or parsed_url.hostname != 'script.google.com' or not parsed_url.path.endswith('/exec'):
        raise WebhookProtocolError('Set webhook_url to the deployed https://script.google.com/macros/s/.../exec URL, not /dev or an editor URL.')
    response = requests.get(WEBHOOK_URL, params={'action': 'test_date', 'date': '09/10/26'}, timeout=30)
    result = webhook_json(response)
    if result.get('success') is False:
        raise WebhookProtocolError('Deployment check failed: ' + str(result.get('error', 'unknown Apps Script error')))
    version = re.match(r'^V(\d+)\b', str(result.get('v', '')))
    if not version or int(version.group(1)) < 82 or result.get('folderFull') != '09-10-2026':
        raise WebhookProtocolError('The URL is not serving the complete V82 (or newer) script with full-year date folders. Save Janani.gs, then Deploy > Manage deployments > Edit > New version > Deploy.')
    print('[CHECK] Webhook ' + str(result['v']) + ': JSON response and date-folder check passed')
    return result

def detect_windows():
    info = {"is_windows": platform.system() == "Windows", "is_win8_family": False,
            "is_legacy": False, "is_unsupported": False}
    if not info["is_windows"]:
        return info
    try:
        version = sys.getwindowsversion()
        major, minor = version.major, version.minor
    except AttributeError:
        match = re.match(r"(\d+)\.(\d+)", platform.version())
        major, minor = map(int, match.groups()) if match else (10, 0)
    info["is_win8_family"] = (major, minor) in [(6, 2), (6, 3)]
    info["is_legacy"] = major < 10
    info["is_unsupported"] = (major, minor) < (6, 1)
    return info

WIN_INFO = detect_windows()
IS_WIN8_FAMILY = WIN_INFO["is_win8_family"]

# Reconfigure the existing streams without taking ownership of their buffers.
for stream in (sys.stdout, sys.stderr):
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def local_path(path):
    return os.path.abspath(os.path.join(BASE_DIR, os.path.expandvars(os.path.expanduser(path))))


try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

GROUP_NAME = "Janani AI Reporting"
GROUP_ALIASES = ["Janani AI Reporting", "Janani Reporting", "Janani AI", "Janani"]
CHAT_DB_PATH = local_path("whatsapp_session_janani")
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxv1nErWrIV55nPz0NjXjvc71HMxnaeekujImRkl3y7cz0ptSpsUd3yVJS5jCAuqU4/exec"
HISTORY_FILE = local_path("pushed_history.json")
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

DEFAULT_DAYS = 10
DAYS_TO_SCAN = DEFAULT_DAYS
DEBUG_MODE = "--debug" in sys.argv
DEBUG_FUEL = "--debug-fuel" in sys.argv
FORCE_PUSH = "--force" in sys.argv

has_all_flag = "--all" in sys.argv
days_from_arg = None
group_from_arg = None

for i, arg in enumerate(sys.argv):
    if arg == "--days" and i+1 < len(sys.argv):
        try: days_from_arg = int(sys.argv[i+1])
        except: pass
    if arg.startswith("--days="):
        try: days_from_arg = int(arg.split("=")[1])
        except: pass
    if arg == "--group" and i+1 < len(sys.argv):
        group_from_arg = sys.argv[i+1]

if group_from_arg:
    GROUP_NAME = group_from_arg
    GROUP_ALIASES = [GROUP_NAME] + [g for g in GROUP_ALIASES if g != GROUP_NAME]

if has_all_flag: DAYS_TO_SCAN = 3650
elif days_from_arg is not None: DAYS_TO_SCAN = days_from_arg

CONFIG_FILE = local_path("sheet_config.json")
BROWSER_BINARY = os.environ.get("JANANI_CHROME_BINARY", "")
DRIVER_PATH = os.environ.get("JANANI_CHROMEDRIVER", "")
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, encoding="utf-8") as stream:
            cfg = json.load(stream)
        BROWSER_BINARY = BROWSER_BINARY or cfg.get("chrome_binary", "")
        DRIVER_PATH = DRIVER_PATH or cfg.get("chromedriver_path", "")
        if cfg.get("webhook_url"): WEBHOOK_URL = cfg["webhook_url"]
        if cfg.get("group_name"):
            GROUP_NAME = cfg["group_name"]
            GROUP_ALIASES = [GROUP_NAME] + [g for g in GROUP_ALIASES if g != GROUP_NAME]
        if cfg.get("days"): DAYS_TO_SCAN = int(cfg["days"])
    except: pass

ALL_KEYS_PATTERN = r"(?:Date|Location|Vehicle\s*no|Present\s*odo|Previous\s*odo|Diesel\s*amount|Diseal\s*amount|Diesel\s*liter|Diseal\s*liter|Average|Bill\s*amount|Work\s*details|Pilot\s*name|Pump\s*Name)\s*-\s*"

FIELD_ALIASES = {
    "Date": ["Date"],
    "Location": ["Location", "Loc"],
    "Vehicle no": ["Vehicle No (Full)", "Vehicle No Full", "Vehicle Number", "Vehicle ID",
                   "Vehicle no", "Vehicle No.", "Vehicle", "Veh No", "Veh.No", "V No",
                   "Registration Number", "Registration No", "Reg No"],
    "Present odo": ["Present odo", "Present Odo", "Present ODO", "PRESENT ODO", "PRESENTODO", "Presentodo", "Present Odo Reading", "Present odo reading", "Present Reading", "Present Km", "Present KM"],
    "Previous odo": ["Previous odo", "Previous Odo", "Previous ODO", "PREVIOUS ODO", "PREVIOUSODO", "Previousodo", "Prev odo", "Prev Odo", "Prev ODO", "PREV ODO", "PREVODO", "Previous Reading", "Prev Reading"],
    "Diesel amount": ["Diesel amount", "Diseal amount", "Diesel Amount", "Diesel Amt", "Diseal Amt", "Diesel Amount", "Amount", "DieselAmount", "Diesel amt", "Diseal Amount", "Diesel Amount", "Diseal Aur Amount"],
    "Diesel liter": ["Diesel liter", "Diseal liter", "Diesel Liter", "Diesel Ltr", "Diseal Ltr", "Liter", "Ltr", "DieselLiter", "Diesel Litre", "Diesel Ltr", "Ltr", "Litre"],
    "Average": ["Average", "Avg", "Mileage", "Average ", "AVG"], 
    "Bill amount": ["Bill amount", "Bill Amount", "Bill Amt"],
    "Work details": ["Work details", "Work Details", "Work", "Details"],
    "Pilot name": ["Pilot name", "Pilot Name", "Pilot", "Driver name", "Driver Name", "Driver", "Pilot Name"], 
    "Pump Name": ["Pump Name", "Pump name", "Pump", "Petrol Pump", "Petrol pump", "PumpName", "Pump Name"],
    "Total KM": ["Total KM", "Total km", "Total Km", "KM", "Km", "Total", "Distance"],
}

# Include long aliases and colon separators when finding the next field.
ALL_KEYS_PATTERN = (r"(?<!\w)(?:" + "|".join(
    re.escape(alias) for alias in sorted(
        {alias for aliases in FIELD_ALIASES.values() for alias in aliases}, key=len, reverse=True)
) + r")(?!\w)\s*[-:]\s*")

def clean_text_for_parsing(text):
    if not text: return text
    return text

def get_field(key, text):
    cleaned = clean_text_for_parsing(text)
    aliases = sorted(FIELD_ALIASES.get(key, [key]), key=len, reverse=True)
    for alias in aliases:
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)\s*[-:]*\s*"
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            start = m.end()
            next_m = re.search(ALL_KEYS_PATTERN, cleaned[start:], re.IGNORECASE)
            if next_m: val = cleaned[start:start+next_m.start()].strip()
            else:
                val = cleaned[start:].strip().split("\n")[0].strip()
                if key not in ("Present odo", "Previous odo"):
                    val = val.split(",")[0].strip()
            if val and val != "-" and val.lower() != "null" and val.lower() != "presentodo" and val.lower() != "fuel":
                if key == "Location":
                    vm = re.search(r"\bVehicle\s*no\b", val, re.I)
                    if vm: val = val[:vm.start()].strip()
                    # Also clean if location contains PRESENTODO
                    vm2 = re.search(r"\bPRESENTO?DO\b", val, re.I)
                    if vm2: val = val[:vm2.start()].strip()
                # Skip if value is just another field name
                if val.upper() in ["PRESENTODO", "FUEL", "VEHICLE NO", "PUMP NAME"]:
                    continue
                return val
    # Fallback: try without dash, like "Present odo: 12345" or "Present odo 12345"
    for alias in aliases:
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)\s*[:\-]?\s*([A-Za-z0-9\.\s\/]+)"
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            val = m.group(1).strip().split("\n")[0][:40]
            if val and val.lower() not in ["null", "-", "", "presentodo", "fuel", "vehicle no"]:
                # Check if val is not another field name
                if len(val) > 2 and not re.match(r'^(PRESENT|PREVIOUS|DIESEL|VEHICLE|PUMP|PILOT|LOCATION|DATE)', val, re.I):
                    return val
    return ""

def parse_odometer(value):
    # Read one number, never concatenate a timestamp or the next field's digits.
    match = re.match(r"\s*(\d{1,3}(?:[,.]\s*\d{3})+|\d{1,2}(?:,\s*\d{2})+,\s*\d{3}|\d+)(?![\d,.])", value)
    if not match:
        return ""
    number = re.sub(r"[,.\s]", "", match.group(1))
    return number if len(number) <= 7 else ""


def bill_history_keys(entry):
    keys = {entry["unique_key"]}
    if entry.get("has_image"):
        if entry.get("message_id"):
            keys.add("bill_message_" + entry["message_id"])
        data = entry["payload"]["image_data"]
        legacy_hash = hashlib.md5(data.encode("utf-8", errors="ignore")).hexdigest()[:20]
        keys.add("bill_" + legacy_hash)
        if entry.get("legacy_image_hash"):
            keys.add("bill_" + entry["legacy_image_hash"])
    return keys


def already_pushed(entry, history):
    keys = bill_history_keys(entry)
    if keys & history:
        return True
    if entry.get("has_image"):
        # Recognize history written by earlier versions, independent of date.
        legacy_hashes = {k[5:] for k in keys if k.startswith("bill_") and len(k) == 25}
        return any(k.endswith("_" + old_hash + "_bill") for k in history for old_hash in legacy_hashes)
    return False


def select_entries_to_push(entries, history, force=False):
    selected, seen = [], set()
    for entry in entries:
        keys = bill_history_keys(entry)
        if keys & seen:
            continue
        seen.update(keys)
        if already_pushed(entry, history) and (entry.get("has_image") or not force):
            continue
        selected.append(entry)
    return selected


def is_target_message(text):
    if not text: return False
    if text in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]']: return True
    check_text = clean_text_for_parsing(text)
    tl = check_text.lower()
    # Filter out template/header rows that are just field names without values (like "Vehicle no PRESENTODO FUEL")
    # These rows have field names but no actual numbers after dash
    if re.search(r'^\s*Vehicle\s*no\s+PRESENTODO', check_text, re.I):
        return False
    if len(re.findall(r'-\s*\d', check_text)) < 1 and "present" in tl and len(check_text) < 50:
        # If message is just headers without values like "Vehicle no PRESENTODO FUEL"
        if "vehicle no" in tl and "presentodo" in tl and "fuel" in tl:
            if "location" not in tl or check_text.count("-") < 2:
                return False
    
    if "present" in tl and "odo" in tl: 
        # Must have a number after present odo to be valid fuel entry
        m = re.search(r'present\s*odo[^\d]*\d{3,}', tl, re.I) or re.search(r'presentodo[^\d]*\d{3,}', tl, re.I)
        if m:
            return True
        # If it has present odo keyword but no number, it's likely a header - skip
        if len(re.findall(r'\d{4,}', check_text)) < 2:
            return False
        return True
    if "prev" in tl and "odo" in tl: return True
    if "diesel" in tl and ("amount" in tl or "liter" in tl or "ltr" in tl): return True
    if "bill" in tl or "forwarded" in tl: return True
    if "vehicle" in tl and re.search(r'vehicle\s*no[^a-z]{0,5}[A-Z0-9]{2,}', check_text, re.I):
        return True
    if re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", check_text):
        if "vehicle" in tl or "location" in tl or "odo" in tl: return True
    return False

def normalize_vehicle_raw(raw):
    if not raw: return ""
    raw = re.sub(r"PRESENTODO.*|PREVIOUSODO.*|DISEAL.*|BILL.*|WORK.*|LOCATION.*|DATE.*", "", raw, flags=re.I)
    cleaned = re.sub(r"[\s\-]+", "", raw.strip().upper())
    # Remove non-alphanumeric except underscore
    cleaned = re.sub(r"[^A-Z0-9_]", "", cleaned)
    return cleaned

def extract_vehicle_id(text):
    """Use the actual message ID, preserving full registrations or four-digit IDs."""
    # WhatsApp formatting and directional marks are not part of a registration.
    text = re.sub(r"[*~_\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", text)
    labels = [re.escape(alias).replace(r"\ ", r"\s+")
              for alias in sorted(FIELD_ALIASES["Vehicle no"], key=len, reverse=True)]
    pattern = r"(?<!\w)(?:" + "|".join(labels) + r")(?!\w)[ \t]*[-:=]?[ \t]*"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    candidates = set()
    for match in matches:
        value = text[match.end():].split("\n", 1)[0].strip()
        # Also support a single-line report with fields lacking ':' or '-'.
        next_field = re.search(r"(?<!\w)(?:" + "|".join(
            re.escape(alias).replace(r"\ ", r"\s+")
            for aliases in FIELD_ALIASES.values() for alias in aliases
        ) + r")(?!\w)", value, re.IGNORECASE)
        if next_field:
            value = value[:next_field.start()].strip()
        value = value.rstrip(",;.").strip()
        normalized = re.sub(r"[ \t-]+", "", value).upper()
        if re.fullmatch(r"\d{4}|[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}", normalized):
            candidates.add(normalized)
    if matches:
        return next(iter(candidates)) if len(candidates) == 1 else ""
    # A full registration without a label is usable; an arbitrary number is not.
    registrations = re.findall(r"(?<!\w)[A-Z]{2}[ -]*\d{1,2}[ -]*[A-Z]{1,3}[ -]*\d{1,4}(?!\w)", text, re.IGNORECASE)
    candidates = {re.sub(r"[ -]+", "", item).upper() for item in registrations}
    return next(iter(candidates)) if len(candidates) == 1 else ""


def capitalize_name(name):
    if not name: return ""
    name = re.sub(r'^[^A-Za-z0-9]+', '', name)
    return " ".join(word.capitalize() for word in name.lower().split())

def parse_date_strict_ddmmyyyy(date_str):
    date_str = date_str.strip()
    if not date_str or date_str in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]']:
        now = datetime.now()
        return now.strftime("%d/%m/%y"), now, MONTHS[now.month-1]
    normalized = re.sub(r'[\-]', '/', date_str)
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(normalized, fmt)
            if d.year < 100: d = d.replace(year=2000 + d.year)
            return d.strftime("%d/%m/%y"), d, MONTHS[d.month-1]
        except: continue
    try:
        parts = re.split(r'[/\-]', date_str.strip())
        if len(parts) == 3:
            day, mon, yr = int(parts[0]), int(parts[1]), int(parts[2])
            if yr < 100: yr += 2000
            if 1 <= mon <= 12 and 1 <= day <= 31:
                d = datetime(yr, mon, day)
                return d.strftime("%d/%m/%y"), d, MONTHS[mon-1]
    except: pass
    now = datetime.now()
    return now.strftime("%d/%m/%y"), now, MONTHS[now.month-1]

def parse_message_debug(text, image_data="", original_text_for_vehicle="", debug=False, message_date=""):
    """V78 with debug reason why fuel not parsed"""
    check_text = original_text_for_vehicle or text
    if text in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]']:
        check_text = original_text_for_vehicle or ""
    
    debug_info = []
    
    if not is_target_message(text) and not is_target_message(check_text):
        if not image_data:
            if debug and ("odo" in text.lower() or "diesel" in text.lower() or "vehicle" in text.lower()):
                debug_info.append(f"is_target_message=False for: {text[:100]}")
            return None, debug_info
    
    cleaned = clean_text_for_parsing(text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
    date_str = get_field("Date", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
    # A labelled date may be followed by WhatsApp's time/status text on the same line.
    date_prefix = re.match(r"\s*(\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2}))(?!\d)", date_str)
    if date_prefix:
        date_str = date_prefix.group(1)
    if not date_str:
        m = re.search(r"^\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", cleaned)
        if m: date_str = m.group(1)
    if not date_str:
        m = re.search(r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", check_text)
        if m: date_str = m.group(1)
        else: date_str = message_date or ("" if image_data else datetime.now().strftime("%d/%m/%y"))
    
    if image_data:
        try:
            normalized_date = date_str.strip().replace("-", "/")
            date_value = None
            for fmt in ("%d/%m/%Y", "%d/%m/%y"):
                try:
                    date_value = datetime.strptime(normalized_date, fmt)
                    break
                except ValueError:
                    pass
            if date_value is None:
                raise ValueError("missing or invalid bill date")
        except ValueError as exc:
            return None, [str(exc) + ": bill skipped to avoid the wrong Drive folder"]
    date_folder, d, month_name = parse_date_strict_ddmmyyyy(date_str)
    
    vehicle_text = text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text
    vehicle_raw = extract_vehicle_id(vehicle_text)
    source_vehicle_id = vehicle_raw
    if not vehicle_raw and not image_data:
        return None, ["Missing, invalid or conflicting vehicle ID in WhatsApp message; report skipped"]

    if not vehicle_raw and image_data:
        text_hash = hashlib.md5(check_text.encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
        m = re.search(r"\b(\d{4,10})\b", check_text)
        if m: vehicle_raw = f"BILL_{m.group(1)}"
        else: vehicle_raw = f"BILL_{text_hash}"
    
    if not vehicle_raw or len(vehicle_raw) > 15:
        if image_data: 
            if image_data:
                img_hash_temp = hashlib.md5(image_data[:1000].encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
                vehicle_raw = f"BILL_{img_hash_temp}"
            else:
                txt_hash = hashlib.md5(check_text.encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
                vehicle_raw = f"BILL_{txt_hash}"
        else: 
            if debug:
                debug_info.append(f"Vehicle parse failed: source normalized='{vehicle_raw}' len>{15 if vehicle_raw and len(vehicle_raw)>15 else 'empty'} for text: {check_text[:100]}")
            return None, debug_info
    
    tl = (text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text).lower()
    
    if image_data: msg_type = "MAINTENANCE"
    elif "present" in tl and "odo" in tl: msg_type = "FUEL"
    elif "prev" in tl and "odo" in tl: msg_type = "FUEL"
    elif "diesel" in tl and ("amount" in tl or "liter" in tl): msg_type = "FUEL"
    else: msg_type = "MAINTENANCE"
    
    present = prev = total_km = diesel_amt_clean = diesel_ltr_clean = average_val = rate_val = bill_amount = work_details = ""
    
    if msg_type == "FUEL":
        present_raw = get_field("Present odo", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        prev_raw = get_field("Previous odo", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        diesel_amt_raw = get_field("Diesel amount", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        diesel_ltr_raw = get_field("Diesel liter", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        avg_raw = get_field("Average", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        
        if debug and (not present_raw or not prev_raw):
            debug_info.append(f"Fuel field parse: Present='{present_raw}' Prev='{prev_raw}' DieselAmt='{diesel_amt_raw}' Ltr='{diesel_ltr_raw}' from: {check_text[:150]}")
        
        present = parse_odometer(present_raw)
        prev = parse_odometer(prev_raw)
        if (present_raw and not present) or (prev_raw and not prev):
            return None, ["Invalid odometer reading; correct the source message before retrying"]
        if present and prev and (int(present) < int(prev) or abs(len(present) - len(prev)) > 1):
            return None, [f"Suspicious odometer readings: present={present}, previous={prev}; correct the source message"]
        diesel_amt_clean = re.sub(r"[^\d.]", "", diesel_amt_raw)[:10]
        diesel_ltr_clean = re.sub(r"[^\d.]", "", diesel_ltr_raw)[:10]
        average_val = re.sub(r"[^\d.]", "", avg_raw)[:10]
        rate_val = ""
        try:
            if diesel_amt_clean and diesel_ltr_clean:
                amt = float(diesel_amt_clean)
                ltr = float(diesel_ltr_clean)
                if ltr != 0:
                    rate_val = f"{amt/ltr:.2f}"
        except: pass
        
        if not present and not prev and debug:
            debug_info.append(f"Fuel present/prev empty after cleaning: present_raw='{present_raw}' -> '{present}', prev_raw='{prev_raw}' -> '{prev}'")
        
        try:
            if present and prev: total_km = str(int(present) - int(prev))
        except: pass
    else:
        bill_raw = get_field("Bill amount", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        if bill_raw:
            m = re.search(r"(\d+\.?\d*)", bill_raw)
            if m: bill_amount = m.group(1)
        work_details = get_field("Work details", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        if not bill_amount and not work_details:
            if image_data:
                work_details = f"Bill image - {check_text[:50] if check_text else 'Bill from group'}"
                bill_amount = "0"
    
    target_sheet = "Bill log" if msg_type == "MAINTENANCE" and image_data else month_name
    
    image_hash_for_payload = ""
    file_name_for_payload = ""
    original_date_for_payload = date_folder
    
    if image_data:
        try:
            encoded = image_data.split(",", 1)[-1]
            image_bytes = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
            if not image_bytes:
                raise ValueError("empty image")
        except (ValueError, base64.binascii.Error):
            return None, ["Invalid bill image data; skipped"]
        full_hash = hashlib.sha256(image_bytes).hexdigest()
        image_hash_for_payload = full_hash
        mime_match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,", image_data)
        image_mime = mime_match.group(1) if mime_match else "image/jpeg"
        extension = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(image_mime, "jpg")
        file_name_for_payload = f"{vehicle_raw}_{date_folder.replace('/','')}_{full_hash[:12]}.{extension}"
        original_date_for_payload = date_folder
    
    payload = {
        "action": "insert",
        "date": date_folder,
        "location": capitalize_name(get_field("Location", text)),
        "vehicle": vehicle_raw,
        "vehicle_id": source_vehicle_id,
        "vehicle_no": source_vehicle_id,
        "type": msg_type,
        "present_odo": present,
        "previous_odo": prev,
        "total_km": total_km,
        "diesel_amount": diesel_amt_clean,
        "diesel_liter": diesel_ltr_clean,
        "rate": rate_val,
        "average": average_val,
        "bill_amount": bill_amount,
        "work_details": get_field("Work details", text),
        "pilot": capitalize_name(get_field("Pilot name", text)),
        "pump": capitalize_name(get_field("Pump Name", text)),
        "source": "Janani Reporting",
        "month": month_name,
        "has_image": bool(image_data),
        "image_data": image_data,
        "mimeType": image_mime if image_data else "",
        "image_url": "",
        "image_hash": image_hash_for_payload,
        "idempotency_key": "bill_" + image_hash_for_payload if image_data else "",
        "file_name": file_name_for_payload,
        "original_date": original_date_for_payload,
        "date_folder": d.strftime("%d-%m-%Y"),
        "target_sheet": target_sheet
    }
    
    if image_data:
        img_hash = image_hash_for_payload
        simple_key = f"bill_{img_hash}"
    else:
        if msg_type == "FUEL":
            simple_key = f"{date_folder}_{vehicle_raw}_{present}_{prev}_FUEL".lower()
        else:
            simple_key = f"{date_folder}_{vehicle_raw}_{bill_amount}_{work_details[:30]}_MAINT".lower()
    
    return {"month": month_name, "date_folder": date_folder, "unique_key": simple_key, "payload": payload, "date_obj": d, "type": msg_type, "present": present, "has_image": bool(image_data)}, debug_info

def parse_message(text, image_data="", original_text_for_vehicle="", message_date=""):
    result, _ = parse_message_debug(text, image_data, original_text_for_vehicle, debug=False, message_date=message_date)
    return result

def acquire_push_lock():
    # Keep the handle open for the entire run; OS releases it on exit/crash.
    lock = open(HISTORY_FILE + ".lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError("Another Janani sync is running; refusing concurrent uploads")
    return lock


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as stream:
                values = json.load(stream)
            if not isinstance(values, list) or not all(isinstance(key, str) for key in values):
                raise ValueError("invalid push history format")
            return set(values)
        except (OSError, ValueError) as exc:
            raise RuntimeError('Cannot read push history safely; refusing to risk duplicate uploads') from exc
    return set()

def save_history(s):
    directory = os.path.dirname(os.path.abspath(HISTORY_FILE))
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".push-history-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(sorted(s), stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, HISTORY_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def get_chrome_options_universal():
    from selenium.webdriver.chrome.options import Options
    options = Options()
    if platform.system() != "Windows":
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    if BROWSER_BINARY:
        binary = local_path(BROWSER_BINARY)
        if not os.path.isfile(binary):
            raise RuntimeError("Configured Chrome binary does not exist: " + binary)
        options.binary_location = binary
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    session_path = os.path.abspath(CHAT_DB_PATH)
    os.makedirs(session_path, exist_ok=True)
    # Never delete profile locks; a running browser may own this session.
    options.add_argument(f"--user-data-dir={session_path}")
    options.add_argument("--profile-directory=Default")
    options.add_experimental_option("excludeSwitches", ["enable-automation","enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option("prefs", {"profile.default_content_setting_values.notifications": 2})
    return options

def create_driver_universal():
    print("="*60)
    print(f"JANANI V78 FIXED FUEL NOT PUSHING - {DAYS_TO_SCAN} Days")
    print("Feature: Debug fuel parsing + --force flag")
    print("="*60)
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    info = detect_windows()
    if info["is_unsupported"]:
        raise RuntimeError("Windows XP/Vista are unsupported by the required Python/browser stack. Use Windows 10/11.")
    options = get_chrome_options_universal()
    configured_driver = local_path(DRIVER_PATH) if DRIVER_PATH else ""
    if configured_driver and not os.path.isfile(configured_driver):
        raise RuntimeError("Configured ChromeDriver does not exist: " + configured_driver)
    driver_path = configured_driver or shutil.which("chromedriver")
    if info["is_legacy"] and not driver_path:
        raise RuntimeError(
            "Windows 7/8/8.1 requires a manually installed Chrome and matching ChromeDriver "
            "(Chrome 109 was the last supported release). Set JANANI_CHROMEDRIVER or "
            "chromedriver_path in sheet_config.json. WhatsApp may reject this obsolete browser; "
            "Windows 10/11 is recommended."
        )
    try:
        if driver_path:
            driver = webdriver.Chrome(service=Service(driver_path), options=options)
        else:
            # Selenium Manager selects the driver for the installed Chrome on modern systems.
            driver = webdriver.Chrome(options=options)
        driver.set_script_timeout(30)
        return driver
    except Exception as exc:
        raise RuntimeError(
            "Could not start Chrome. Install Chrome, use a ChromeDriver matching its major version, "
            "and close any Chrome using whatsapp_session_janani. For offline/custom installations, "
            "set JANANI_CHROME_BINARY and JANANI_CHROMEDRIVER. Details: " + str(exc)
        ) from exc

def wait_for_whatsapp_login(driver, timeout=180):
    print(f'[LOGIN] Waiting up to {timeout}s. Scan the QR code in the Chrome window opened by Janani.')
    for elapsed in range(timeout):
        sidebar = driver.find_elements(By.CSS_SELECTOR, '#side, #pane-side')
        if any(element.is_displayed() for element in sidebar):
            print(f'[OK] WhatsApp chat sidebar ready after {elapsed}s')
            return True
        if elapsed and elapsed % 30 == 0:
            print(f'[LOGIN] Still waiting ({elapsed}s): complete QR login and let chats finish loading.')
        time.sleep(1)
    print('[FAIL] WhatsApp login did not complete or the chat sidebar did not load. '
          'Check the Chrome window, internet connection, and QR login; group search was not attempted.')
    return False


def find_whatsapp_search(driver, timeout=30):
    # WhatsApp sometimes renders the search above #side, or as an input.
    # Never fall back to an arbitrary editable node (which may be a composer).
    selector = (
        '#side [contenteditable="true"], #side input[type="text"], #side input[type="search"], '
        '[data-testid="chat-list-search"] [contenteditable="true"], '
        '[data-testid="chat-list-search"] input, '
        '[contenteditable="true"][data-tab="3"], '
        '[role="search"] [contenteditable="true"], [role="search"] input, '
        'input[aria-label*="Search"], input[placeholder*="Search"], '
        '[contenteditable="true"][aria-label*="Search"]')
    for elapsed in range(timeout):
        for box in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if (box.is_displayed() and box.is_enabled()
                        and not driver.execute_script("return !!arguments[0].closest('#main');", box)):
                    return box
            except Exception:
                continue  # The UI may replace nodes while chats load.
        if elapsed == 0:
            print('[INFO] Waiting for WhatsApp chat search to load (up to 30s).')
        time.sleep(1)
    print('[FAIL] No visible chat-search field was found after waiting. '
          'Check whether WhatsApp has finished loading its chat list. '
          'The search layout may have changed; message composer was not used.')
    return None


def find_group(driver, group_name):
    search_box = find_whatsapp_search(driver)
    if search_box is None:
        return False
    aliases = GROUP_ALIASES if group_name == GROUP_NAME else [group_name] + GROUP_ALIASES
    for attempt_name in aliases:
        try:
            print(f"[INFO] Searching for group: {attempt_name}")
            try:
                search_box.click()
                time.sleep(0.5)
                search_box.send_keys(Keys.CONTROL + "a")
                search_box.send_keys(Keys.BACKSPACE)
                time.sleep(0.5)
                search_box.send_keys(attempt_name)
                time.sleep(2)
            except Exception as exc:
                print(f'[WARN] Could not use the WhatsApp chat search: {type(exc).__name__}: {exc}')
                search_box = find_whatsapp_search(driver)
                if search_box is None:
                    return False
                continue
            elems = driver.find_elements(By.CSS_SELECTOR, '#pane-side [title], #side [role="listitem"] [title], [data-testid="chat-list"] [title], [role="grid"] [title]')
            for elem in elems:
                try:
                    title = (elem.get_attribute("title") or elem.text or "").strip()
                    if not elem.is_displayed(): continue
                    if driver.execute_script("return !!arguments[0].closest('#main');", elem): continue
                    if ' '.join(title.split()).casefold() == ' '.join(attempt_name.split()).casefold():
                        try:
                            elem.click()
                            time.sleep(4)
                            return True
                        except:
                            driver.execute_script("arguments[0].click();", elem)
                            time.sleep(4)
                            return True
                except: continue
        except Exception as e:
            print(f"[WARN] Search failed for {attempt_name}: {e}")
            continue
    return False

def scroll_and_collect_with_image_fix(driver, days=30):
    max_scrolls = max(200, days * 12)
    if days >= 3650: max_scrolls = 3000
    print(f"[INFO] Collecting - {days} days, max scrolls {max_scrolls}")
    collected = {}
    
    for i in range(max_scrolls):
        try:
            messages = driver.execute_script(r"""
                function calendarDate(day, month, year) {
                    if(year < 100) year += 2000;
                    let date = new Date(year, month - 1, day);
                    if(date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return '';
                    return String(day).padStart(2, '0') + '/' + String(month).padStart(2, '0') + '/' + year;
                }
                function messageDateText(value) {
                    let text = String(value || '').replace(/[\u200e\u200f]/g, '').trim();
                    let match = text.match(/(?:^|[^\d])(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4}|\d{2})(?!\d)/);
                    if(match) return calendarDate(Number(match[1]), Number(match[2]), Number(match[3]));
                    match = text.match(/(?:^|[^\d])(\d{4})-(\d{2})-(\d{2})(?!\d)/);
                    if(match) return calendarDate(Number(match[3]), Number(match[2]), Number(match[1]));
                    let now = new Date(), lower = text.toLowerCase();
                    if(lower === 'today' || lower === 'yesterday') {
                        if(lower === 'yesterday') now.setDate(now.getDate() - 1);
                        return calendarDate(now.getDate(), now.getMonth() + 1, now.getFullYear());
                    }
                    let weekdays = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
                    if(weekdays.includes(lower)) {
                        let difference = (now.getDay() - weekdays.indexOf(lower) + 7) % 7;
                        now.setDate(now.getDate() - (difference || 7));
                        return calendarDate(now.getDate(), now.getMonth() + 1, now.getFullYear());
                    }
                    match = text.match(/^(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s*,?\s*(\d{4}))?$/i);
                    if(match) {
                        let months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                        return calendarDate(Number(match[1]), months.indexOf(match[2].slice(0,3).toLowerCase()) + 1, Number(match[3] || now.getFullYear()));
                    }
                    return '';
                }
                function dateForMessage(node, idNode) {
                    let scope = idNode || node;
                    let metadataNodes = [node, scope, node.closest('[data-pre-plain-text]'), ...scope.querySelectorAll('[data-pre-plain-text]')].filter(Boolean);
                    for(let item of metadataNodes) {
                        let date = messageDateText(item.getAttribute('data-pre-plain-text'));
                        if(date) return date;
                    }
                    for(let item of [scope, ...scope.querySelectorAll('[title], [aria-label], [data-tooltip-text]')]) {
                        for(let name of ['title','aria-label','data-tooltip-text']) {
                            // Timestamp attributes must contain an actual calendar date, not just a time.
                            let value = item.getAttribute(name) || '';
                            if(!/\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}-\d{2}-\d{2}/.test(value)) continue;
                            let date = messageDateText(value);
                            if(date) return date;
                        }
                    }
                    let conversation = scope.closest('#main, [data-testid="conversation-panel-messages"]') || document.querySelector('#main') || scope.parentElement;
                    let nearest = '';
                    if(conversation) {
                        for(let heading of conversation.querySelectorAll('div, span')) {
                            // Never borrow a date written inside another message or a future separator.
                            if(heading.closest('[data-id], [data-testid="msg-container"], .message-in, .message-out')) continue;
                            if(heading.contains(scope) || heading.querySelector('[data-id], [data-testid="msg-container"], .message-in, .message-out')) continue;
                            if(!(heading.compareDocumentPosition(scope) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
                            let text = (heading.innerText || heading.textContent || '').trim();
                            if(text.length > 40) continue;
                            if(!/^(?:\d{1,2}[\/\-]\d{1,2}[\/\-](?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2}|today|yesterday|sunday|monday|tuesday|wednesday|thursday|friday|saturday|\d{1,2}\s+[a-z]+(?:\s*,?\s*\d{4})?)$/i.test(text)) continue;
                            let date = messageDateText(text);
                            if(date) nearest = date;
                        }
                    }
                    return nearest;
                }
                let result = [];
                const selectors = [
                    'div[data-testid="msg-container"]',
                    'div[data-id]',
                    'div.message-in',
                    'div.message-out',
                    'div._1-FMR',
                    'div._2sOZp',
                    'div[data-testid="conversation-panel-messages"] div[data-id]',
                    'div[role="row"]',
                    'div.copyable-area div[data-id]',
                    'div#main div[data-id]'
                ];
                let nodes = [];
                for(let sel of selectors){
                    let found = document.querySelectorAll(sel);
                    if(found.length > nodes.length) nodes = found;
                }
                if(nodes.length == 0){
                    let allDivs = document.querySelectorAll('div');
                    for(let div of allDivs){
                        let txt = div.innerText || '';
                        if(txt.length > 20 && txt.length < 1000){
                            if((txt.includes('Vehicle') || txt.includes('Date')) && (txt.includes('/') || txt.includes('-'))){
                                if(txt.includes('Present') || txt.includes('Bill') || txt.includes('Location')){
                                    nodes = Array.from(allDivs).filter(d => {
                                        let t = d.innerText || '';
                                        return t.length > 20 && t.length < 1000 && t.includes('Vehicle');
                                    });
                                    break;
                                }
                            }
                        }
                    }
                }
                nodes.forEach((n, idx)=>{
                    let text = '';
                    try{ text = n.innerText || n.textContent || ''; }catch(e){ text = ''; }
                    text = text.trim();
                    if(text.length > 3000 || (text.length < 10 && !n.querySelector('img'))) return;
                    let tl = text.toLowerCase();
                    if(!(tl.includes('vehicle') || tl.includes('date') || tl.includes('bill') || tl.includes('location') || tl.includes('present') || tl.includes('odo') || n.querySelector('img'))) return;
                    let innerHTML = n.innerHTML || '';
                    let isForwarded = innerHTML.includes('Forwarded') || text.includes('Forwarded');
                    let hasImage = false; let imgCount = 0;
                    let imgs = n.querySelectorAll('img');
                    imgs.forEach((img)=>{
                        let w = img.naturalWidth || img.width || 0;
                        let h = img.naturalHeight || img.height || 0;
                        let src = img.src || '';
                        let isProfile = src.includes('avatar') || src.includes('pps') || src.includes('sticker') || src.includes('emoji');
                        let isSmallIcon = (w > 0 && w < 60) && (h > 0 && h < 60);
                        if(!isProfile && !isSmallIcon && (w >= 80 || src.includes('blob:'))){
                            if(w * h >= 100*100 || src.includes('blob:')){ imgCount++; hasImage = true; }
                        }
                    });
                    if(n.querySelector('[data-testid="image-thumb"]')){ hasImage = true; imgCount = Math.max(imgCount, 1); }
                    let idNode = n.closest('[data-id]') || n.querySelector('[data-id]');
                    let messageId = idNode ? idNode.getAttribute('data-id') : '';
                    let messageDate = dateForMessage(n, idNode);
                    result.push({messageId: messageId, messageDate: messageDate, idx: idx, text: text || (isForwarded ? '[FORWARDED_BILL_IMAGE]' : '[IMAGE_ONLY_BILL]'), hasImage: hasImage, imgCount: imgCount, isForwarded: isForwarded, textLength: text.length});
                });
                return result;
            """)
            
            found_in_this_scroll = 0
            if messages:
                for msg in messages:
                    if not isinstance(msg, dict): continue
                    txt = msg.get('text', '')
                    has_img = msg.get('hasImage', False)
                    if not has_img and len(txt) < 10: continue
                    h = msg.get("messageId") or hashlib.sha256((txt + msg.get("messageDate", "")).encode("utf-8")).hexdigest()
                    if h in collected and not collected[h].get("message_date") and msg.get("messageDate"):
                        collected[h]["message_date"] = msg["messageDate"]
                    if h not in collected or (has_img and not collected[h].get("image_data")):
                        image_data = ""
                        legacy_image_hash = ""
                        if has_img:
                            try:
                                b64 = driver.execute_async_script("""
                                    const callback = arguments[arguments.length - 1];
                                    const searchText = arguments[0];
                                    const messageId = arguments[2];
                                    (async () => {
                                        try {
                                            const selectors = ['div[data-testid="msg-container"]','div[data-id]','div.message-in','div.message-out','div[role="row"]'];
                                            let nodes = [];
                                            for(let sel of selectors){ let found = document.querySelectorAll(sel); if(found.length > nodes.length) nodes = found; }
                                            let targetNode = null;
                                            if(messageId){
                                                targetNode = Array.from(document.querySelectorAll('[data-id]')).find(n => n.getAttribute('data-id') === messageId);
                                            } else {
                                                let matches = Array.from(nodes).filter(n => (n.innerText || '').trim() === searchText);
                                                if(matches.length === 1) targetNode = matches[0];
                                            }
                                            if(targetNode){
                                                targetNode.scrollIntoView({behavior: 'smooth', block: 'center'});
                                                await new Promise(r => setTimeout(r, 800));
                                                let imgs = Array.from(targetNode.querySelectorAll('img'));
                                                let sorted = imgs.filter(img => {
                                                    let src = img.src || '';
                                                    return !(src.includes('avatar') || src.includes('pps') || src.includes('sticker'));
                                                }).sort((a,b) => (b.naturalWidth*b.naturalHeight) - (a.naturalWidth*a.naturalHeight));
                                                for(let img of sorted){
                                                    let src = img.src || '';
                                                    if(src.startsWith('blob:') || src.startsWith('data:image/')){
                                                        try{
                                                            let resp = await fetch(src);
                                                            if(!resp.ok) continue;
                                                            let blob = await resp.blob();
                                                            let reader = new FileReader();
                                                            reader.onloadend = () => {
                                                                let legacyData = '';
                                                                try {
                                                                    let canvas = document.createElement('canvas');
                                                                    canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
                                                                    canvas.getContext('2d').drawImage(img, 0, 0);
                                                                    legacyData = canvas.toDataURL('image/jpeg', 0.8);
                                                                } catch(e) {}
                                                                callback({image_data: reader.result, legacy_image_data: legacyData});
                                                            };
                                                            reader.readAsDataURL(blob);
                                                            return;
                                                        }catch(e){}
                                                    }
                                                }
                                                for(let img of sorted){
                                                    if(img.naturalWidth >= 100 && img.naturalHeight >= 100){
                                                        try{
                                                            let canvas = document.createElement('canvas');
                                                            let ctx = canvas.getContext('2d');
                                                            canvas.width = img.naturalWidth;
                                                            canvas.height = img.naturalHeight;
                                                            ctx.drawImage(img, 0, 0);
                                                            let data = canvas.toDataURL('image/jpeg', 0.8);
                                                            if(data && data.length > 5000){ callback(data); return; }
                                                        }catch(e){}
                                                    }
                                                }
                                            }
                                            callback("");
                                        } catch(e){ callback(""); }
                                    })();
                                """, txt, msg.get('isForwarded', False), msg.get('messageId', ''))
                                if isinstance(b64, dict):
                                    legacy_data = b64.get("legacy_image_data", "")
                                    if legacy_data:
                                        legacy_image_hash = hashlib.md5(legacy_data.encode("utf-8")).hexdigest()[:20]
                                    b64 = b64.get("image_data", "")
                                if b64: image_data = b64
                            except: pass
                        collected[h] = {"text": txt, "image_data": image_data, "message_date": msg.get("messageDate", ""), "message_id": msg.get("messageId", ""), "legacy_image_hash": legacy_image_hash}
                        found_in_this_scroll += 1
            
            print(f"  Scroll {i}: Found {found_in_this_scroll} new messages (total {len(collected)})")
            
            try:
                driver.execute_script("""
                    const scrollSelectors = ['div[data-testid="conversation-panel-messages"]','div#main','div[data-testid="chat"]','div._1c_mC','div.copyable-area'];
                    for(let sel of scrollSelectors){
                        let el = document.querySelector(sel);
                        if(el){ el.scrollTop = 0; return; }
                    }
                    window.scrollTo(0,0);
                """)
                time.sleep(2.5 if IS_WIN8_FAMILY else 1.5)
            except:
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_UP)
                    time.sleep(1)
                except: pass
            
            if i > 5 and found_in_this_scroll == 0 and len(collected) > 10:
                break
                
        except Exception as e:
            print(f"  Scroll error {i}: {e}")
            time.sleep(1)
            continue
    
    print(f"[INFO] Collected {len(collected)} messages")
    return collected

def read_last_n_days(days=30):
    if not SELENIUM_AVAILABLE:
        print("[ERROR] Selenium not installed")
        return [], set()
    print(f"Platform: {platform.platform()} | Scanning {days} days - V78")
    cutoff_date = datetime.now() - timedelta(days=days) if days < 3650 else datetime(2000, 1, 1)
    print(f"[INFO] Cutoff: {cutoff_date.strftime('%d/%m/%y')}")
    try:
        driver = create_driver_universal()
    except Exception as e:
        print(f"[FAIL] Driver: {e}")
        return [], set()
    try:
        driver.get("https://web.whatsapp.com")
        if not wait_for_whatsapp_login(driver):
            driver.quit()
            return [], set()
        time.sleep(8 if IS_WIN8_FAMILY else 5)
        if not find_group(driver, GROUP_NAME):
            print(f"[FAIL] Group {GROUP_NAME} not found")
            print('[HINT] Confirm this group is visible in the logged-in WhatsApp account. '
                  'Set group_name in sheet_config.json to its exact name, including any emoji.')
            driver.quit()
            return [], set()
        time.sleep(6 if IS_WIN8_FAMILY else 4)
        
        collected_dict = scroll_and_collect_with_image_fix(driver, days=days)
        history = load_history()
        parsed = []
        skipped_debug = []
        
        for h, item in collected_dict.items():
            txt = item["text"].strip()
            img_data = item.get("image_data", "")
            if not txt and not img_data: continue
            if len(txt) < 3 and not img_data: continue
            
            result, debug_info = parse_message_debug(txt, image_data=img_data, original_text_for_vehicle=txt, debug=DEBUG_FUEL, message_date=item.get("message_date", ""))
            if result:
                result["message_id"] = item.get("message_id", "")
                result["legacy_image_hash"] = item.get("legacy_image_hash", "")
                if result.get('date_obj') and result['date_obj'] < cutoff_date and not result.get('has_image'):
                    if DEBUG_FUEL and result.get('type') == 'FUEL':
                        print(f"  [FILTERED BY DATE] Fuel {result['payload']['vehicle']} {result['date_folder']} < cutoff {cutoff_date.strftime('%d/%m/%y')}")
                    continue
                parsed.append(result)
            else:
                if debug_info:
                    print("[SKIP] " + "; ".join(debug_info))
                if DEBUG_FUEL and debug_info:
                    # Only show fuel-related debug
                    if "odo" in txt.lower() or "diesel" in txt.lower() or "present" in txt.lower():
                        skipped_debug.append((txt[:200], debug_info))
        
        if DEBUG_FUEL and skipped_debug:
            print(f"\n[DEBUG FUEL] Skipped {len(skipped_debug)} potential fuel messages (why parsing failed):")
            for txt, infos in skipped_debug[:10]:
                print(f"  Text: {txt}")
                for info in infos:
                    print(f"    -> {info}")
                print()
        
        parsed.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
        fuel = sum(1 for e in parsed if e.get('type') == 'FUEL')
        maint = sum(1 for e in parsed if e.get('type') == 'MAINTENANCE')
        print(f"[INFO] V78 - Fuel: {fuel}, Bills: {maint}, History: {len(history)}")
        
        deduped = {}
        for entry in parsed:
            key = entry["unique_key"]
            if key not in deduped:
                deduped[key] = entry
        parsed = list(deduped.values())
        parsed.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
        driver.quit()
        return parsed, history
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        try: driver.quit()
        except: pass
        return [], set()

if __name__ == "__main__":
    try:
        check_webhook()
    except Exception as ex:
        print(f'[FAIL] Webhook check: {ex}')
        sys.exit(2)
    if '--check-webhook' in sys.argv:
        sys.exit(0)
    print("="*60)
    print(f"JANANI V78 FIXED FUEL NOT PUSHING - {DAYS_TO_SCAN} Days")
    print(f"Force: {FORCE_PUSH} | Debug Fuel: {DEBUG_FUEL}")
    print("="*60)
    push_lock = acquire_push_lock()
    entries, history = read_last_n_days(days=DAYS_TO_SCAN)
    entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
    print(f"\nTotal found: {len(entries)} (after dedup within run)")
    print(f"History: {len(history)} entries")
    if not entries:
        print("[FAIL] No messages")
        print("[HINT] Try: python janani-webhook.py --days 1 --debug-fuel")
        sys.exit(1)
    else:
        fuel_entries = [e for e in entries if e.get('type') == 'FUEL']
        print(f"\nFuel entries found: {len(fuel_entries)}")
        for e in fuel_entries[:10]:
            p = e['payload']
            in_hist = "IN HISTORY (will skip unless --force)" if e['unique_key'] in history else "NEW"
            print(f"  {e['date_folder']} ⛽ {p['vehicle']} | Present:{p['present_odo']} Prev:{p['previous_odo']} | {p['diesel_amount']}L | {in_hist} | key={e['unique_key'][:40]}")
        
        if FORCE_PUSH:
            to_push = select_entries_to_push(entries, history, force=True)
            print(f"\n[FORCE] Pushing {len(to_push)} entries (bill history always respected)")
        else:
            to_push = select_entries_to_push(entries, history)
            print(f"\nNew to push: {len(to_push)} (Fuel: {sum(1 for e in to_push if e['payload'].get('type')=='FUEL')} + Bills: {sum(1 for e in to_push if e['payload'].get('has_image'))})")
            print(f"Will SKIP {len(entries) - len(to_push)} already in history")
            if len(to_push) == 0:
                print("\n⚠️ No new entries! If you have new fuel entry but it's not pushing:")
                print("  1. It might already be in pushed_history.json with same key")
                print("  2. Check the original message and debug output; preserve push history")
                print("  3. For an intentional fuel replay only: python janani-webhook.py --days 1 --force")
                print("  4. Or run with --debug-fuel to see why fuel parsing failed")
        
        push_list = to_push
        confirmed_pushes = 0
        failed_pushes = 0
        attempted_pushes = 0
        
        for idx, e in enumerate(push_list):
            payload = e['payload']
            has_img = "📷 BILL" if payload.get('has_image') else "⛽ FUEL"
            size = len(payload.get('image_data',''))/1024 if payload.get('image_data') else 0
            target = payload.get('target_sheet', 'unknown')
            print(f"[{idx+1}/{len(push_list)}] {has_img} {payload['vehicle']} {payload['date']} {payload['type']} | {size:.1f}KB -> {target}")
            
            try:
                attempted_pushes += 1
                r = requests.post(WEBHOOK_URL, json=payload, timeout=90)
                j = webhook_json(r)
                print(f"  -> {json.dumps(j, ensure_ascii=False)[:800]}")
                if j.get("success") is True or j.get("duplicate") is True:
                    history.update(bill_history_keys(e))
                    save_history(history)
                    confirmed_pushes += 1
                    if j.get("sheet"):
                        print(f"  -> Inserted into: {j['sheet']}")
                    if j.get("duplicate"):
                        print("  -> Already present; recorded in local history")
                else:
                    failed_pushes += 1
                    print("  -> Webhook did not confirm success; history not updated")
                time.sleep(2)
            except WebhookProtocolError as ex:
                failed_pushes += 1
                print(f'  -> [FAIL] {ex}')
                print('[STOP] Remaining reports were not sent; fix the deployment before retrying.')
                break
            except Exception as ex:
                failed_pushes += 1
                print(f"  Push failed: {ex}")
        
        print(f'\n[RESULT] Confirmed: {confirmed_pushes}; failed: {failed_pushes}; not attempted: {len(push_list) - attempted_pushes}')
        if failed_pushes:
            sys.exit(1)
        print("[DONE] Janani sync")
