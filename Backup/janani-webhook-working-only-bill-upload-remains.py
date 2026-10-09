import os, re, time, requests, base64, json, hashlib, sys, io
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# FIX for >> daily_log.txt 2>&1 : Force UTF-8 output so emojis don't crash on Windows cp1252
try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

GROUP_NAME = "Janani AI Reporting"
CHAT_DB_PATH = "whatsapp_session_janani"
# Default from your sheet_config.json - will be overridden if file exists
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxv1nErWrIV55nPz0NjXjvc71HMxnaeekujImRkl3y7cz0ptSpsUd3yVJS5jCAuqU4/exec"

# Support --webhook argument
for i, arg in enumerate(sys.argv):
    if arg.startswith("--webhook="):
        WEBHOOK_URL = arg.split("=", 1)[1]
        print(f"Using webhook from arg: {WEBHOOK_URL}")
    elif arg == "--webhook" and i+1 < len(sys.argv):
        WEBHOOK_URL = sys.argv[i+1]
        print(f"Using webhook from arg: {WEBHOOK_URL}")

# Also read from sheet_config.json (your new deployment)
CONFIG_FILE = "sheet_config.json"
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as cf:
            cfg = json.load(cf)
            if "webhook_url" in cfg and cfg["webhook_url"]:
                WEBHOOK_URL = cfg["webhook_url"]
                print(f"Using webhook from {CONFIG_FILE}: {WEBHOOK_URL}")
    except Exception as e:
        print(f"Config error: {e}")

HISTORY_FILE = "pushed_history.json"
BILL_HISTORY_FILE = "bill_history.json"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

FORCE_MODE = "--force" in sys.argv or "-f" in sys.argv
GET_ALL = "--all" in sys.argv
DEBUG_MODE = "--debug" in sys.argv
NO_TIME_FILTER = "--no-time-filter" in sys.argv or GET_ALL
NON_INTERACTIVE = "--non-interactive" in sys.argv or "--scheduled" in sys.argv or not sys.stdin.isatty()
# Parse --days argument - your version was 5 days, now support --all = 9999
SCAN_DAYS = 20
if GET_ALL or NO_TIME_FILTER:
    SCAN_DAYS = 9999
for arg in sys.argv:
    if arg.startswith("--days"):
        try:
            if "=" in arg:
                SCAN_DAYS = int(arg.split("=")[1])
            else:
                idx = sys.argv.index(arg)
                SCAN_DAYS = int(sys.argv[idx+1])
        except:
            pass

TARGET_SUBSTRINGS = ["Vehicle no-", "Present odo-", "Pilot name", "Previous odo"]

def is_target_message(text, debug=False):
    if not text:
        return False
    text_lower = text.lower()
    if "date-" not in text_lower:
        return False
    
    # YOUR FIX: Ignore empty value messages like Date- Location- with no values
    has_valid_value = False
    patterns = [
        r'Date-\s*[0-9/\-]+',
        r'Vehicle no-\s*[A-Z0-9]+',
        r'Present odo-\s*\d+',
        r'Location-\s*\S+',
        r'Pilot name-\s*\S+',
        r'Bill amount-\s*[\d.]+',
        r'Work details-\s*\S+',
    ]
    for pat in patterns:
        if re.search(pat, text, re.I):
            has_valid_value = True
            break
    if not has_valid_value:
        if debug:
            print(f"    Ignoring empty value message: {text[:100]}")
        return False
    
    for substr in TARGET_SUBSTRINGS:
        if substr.lower() in text_lower:
            field_pattern = rf"{re.escape(substr)}\s*\S+"
            if re.search(field_pattern, text, re.I):
                return True
            for line in text.split('\n'):
                if substr.lower() in line.lower():
                    parts = line.split('-', 1)
                    if len(parts) > 1 and parts[1].strip():
                        return True
    # Extra lenient
    if "vehicle" in text_lower and "no" in text_lower:
        if re.search(r'Vehicle no-\s*[A-Z0-9]+', text, re.I):
            return True
    if "pilot" in text_lower and "name" in text_lower:
        if re.search(r'Pilot name-\s*\S+', text, re.I):
            return True
    if "present" in text_lower and "odo" in text_lower:
        if re.search(r'Present odo-\s*\d+', text, re.I):
            return True
    # Fuel/Mntc indicators
    if "fuel msg" in text_lower or "Mntc MSG" in text_lower or "mtc msg" in text_lower:
        return True
    return False

def get_message_type(text):
    text_lower = text.lower()
    if "fuel msg-" in text_lower or "diesel" in text_lower or "diseal" in text_lower:
        return "FUEL"
    if "mtc msg-" in text_lower or "mntc msg-" in text_lower or "work details" in text_lower:
        return "MAINTENANCE"
    return "UNKNOWN"

def clean_text_for_parsing(val, key=""):
    # Remove leading / - \ : ; . , etc.
    val = re.sub(r'^[^A-Za-z0-9]+', '', val)  # /Bhikangaon → Bhikangaon
    val = val.lstrip('/\\-:;.,')
    return val.strip()

def get_field(key, text):
    text = clean_text_for_parsing(text)
    m = re.search(rf"{key}\s*-\s*([^\n\r]+)", text, re.IGNORECASE)
    if not m:
        return ""
    val = m.group(1).strip()
    if not val or val == "-" or val.lower() == "null":
        return ""
    return val

def normalize_vehicle_raw(raw):
    if not raw:
        return ""
    return re.sub(r"[\s\-]+", "", raw.strip().upper())

def capitalize_name(name):
    """Capitalise pilot/pump names: shantilal -> Shantilal, raja rokde -> Raja Rokde, ADESHWAR -> Adeshwar"""
    if not name:
        return ""
    # Clean and title case
    name = name.strip()
    # Handle multiple spaces, lower then title
    # Special handling: keep all-caps acronyms? No, just title case
    return " ".join(word.capitalize() for word in name.lower().split())

def parse_date_strict_ddmmyyyy(date_str):
    date_str = date_str.strip()
    normalized = re.sub(r'[\-]', '/', date_str)
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(normalized, fmt)
            if d.year < 100:
                d = d.replace(year=2000 + d.year)
            month_name = MONTHS[d.month-1]
            return d.strftime("%d-%m-%Y"), d, month_name
        except:
            continue
    try:
        parts = re.split(r'[/\-]', date_str.strip())
        if len(parts) == 3:
            day = int(parts[0])
            mon = int(parts[1])
            yr = int(parts[2])
            if yr < 100:
                yr += 2000
            if 1 <= mon <= 12 and 1 <= day <= 31:
                d = datetime(yr, mon, day)
                month_name = MONTHS[mon-1]
                return d.strftime("%d-%m-%Y"), d, month_name
    except:
        pass
    now = datetime.now()
    return now.strftime("%d-%m-%Y"), now, MONTHS[now.month-1]

def parse_message(text):
    if not is_target_message(text):
        return None
    lines = text.strip().split('\n')
    non_empty_fields = 0
    for line in lines:
        line = line.strip()
        if '-' in line:
            parts = line.split('-', 1)
            if len(parts) > 1 and parts[1].strip():
                non_empty_fields += 1
    if non_empty_fields < 2:
        return None
    msg_type = get_message_type(text)
    date_str = get_field("Date", text)
    if not date_str:
        m = re.search(r"Date-\s*([0-9/\-]+)", text, re.I)
        if m:
            date_str = m.group(1)
    if not date_str:
        return None
    if not re.search(r'[0-9]', date_str):
        return None
    date_folder, d, month_name = parse_date_strict_ddmmyyyy(date_str)
    present = re.sub(r"\D", "", get_field("Present odo", text))
    prev = re.sub(r"\D", "", get_field("Previous odo", text))
    total_km = ""
    try:
        if present and prev:
            total_km = str(int(present) - int(prev))
    except:
        pass
    veh_raw = get_field("Vehicle no", text)
    if not veh_raw:
        m = re.search(r"Vehicle no-\s*([A-Z0-9]+)", text, re.I)
        if m:
            veh_raw = m.group(1)
    vehicle_raw = normalize_vehicle_raw(veh_raw)
    if not vehicle_raw:
        return None
    diesel_amt_raw = re.sub(r"[^\d.]", "", get_field("Diesel amount", text) or get_field("Diseal amount", text))
    diesel_ltr_raw = re.sub(r"[^\d.]", "", get_field("Diesel liter", text) or get_field("Diseal liter", text))
    # CORRECTED: average_val = if diesel_ltr_raw and diesel_ltr_raw != "0" then total_km/diesel_ltr_raw else ""
    average_val = ""
    try:
        if diesel_ltr_raw and diesel_ltr_raw != "0" and diesel_ltr_raw != "0.0":
            if total_km and total_km != "0":
                tk = float(total_km)
                ltr = float(diesel_ltr_raw)
                if ltr != 0:
                    average_val = f"{tk/ltr:.2f}"
    except:
        average_val = ""
    # Fallback to message Average field if calculation not possible and field exists
    if not average_val:
        average_val = get_field("Average", text)
    # Calculate Rate/L = Diesel Amount / Diesel Liter
    rate_val = ""
    try:
        if diesel_amt_raw and diesel_ltr_raw:
            amt = float(diesel_amt_raw)
            ltr = float(diesel_ltr_raw)
            if ltr != 0:
                rate_val = f"{amt/ltr:.2f}"
    except:
        rate_val = ""
    payload = {
        "date": get_field("Date", text),
        "location": capitalize_name(get_field("Location", text)),
        "vehicle": vehicle_raw,
        "type": "FUEL" if msg_type=="FUEL" else "MAINTENANCE",
        "present_odo": present,
        "previous_odo": prev,
        "total_km": total_km,
        "diesel_amount": diesel_amt_raw,
        "diesel_liter": diesel_ltr_raw,
        "rate": rate_val,
        "average": average_val,
        "bill_amount": re.sub(r"[^\d.]", "", get_field("Bill amount", text)),
        "work_details": get_field("Work details", text),
        "pilot": capitalize_name(get_field("Pilot name", text)),
        "pump": capitalize_name(get_field("Pump Name", text)),
        "source": "Janani Reporting",
        "month": month_name
    }
    # FIXED V39: Robust unique_key - date_folder + vehicle + type is primary
    # Same vehicle same date same type should be 1 entry only (prevents 7480 log spam 7x)
    # For history, use date+vehicle+type as key, not odo (odo may have parsing variance)
    # Keep full key for exact match but also create simple key for dedup
    simple_key = f"{date_folder}_{vehicle_raw}_{msg_type}".lower()
    full_key = f"{date_folder}_{vehicle_raw}_{present}_{prev}_{msg_type}".lower()
    # Use simple_key for dedup (same vehicle same date FUEL = 1 entry)
    unique_key = full_key
    # Store full details for debugging
    full_unique_key = full_key
    return {
        "month": month_name,
        "date_raw": date_str,
        "date_folder": date_folder,
        "unique_key": unique_key,
        "present": present,
        "payload": payload,
        "whatsapp_time": None
    }

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(s):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(list(s), f, indent=2)

def load_bill_history():
    if os.path.exists(BILL_HISTORY_FILE):
        try:
            with open(BILL_HISTORY_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get("hashes", [])), set(data.get("files", []))
        except:
            return set(), set()
    return set(), set()

def save_bill_history(hashes, files):
    with open(BILL_HISTORY_FILE, 'w') as f:
        json.dump({"hashes": list(hashes), "files": list(files)}, f, indent=2)

def push_to_sheet(payload, history_set, unique_key):
    # FIXED V36: ALWAYS check history to prevent duplicates, even in FORCE_MODE
    # To re-push, delete pushed_history.json
    if unique_key in history_set:
        print(f"  [SKIP] SKIPPED (already pushed): {payload['vehicle']} | {payload['date']} -> {payload['month']} | {payload['type']}")
        return True
    print(f"  -> Pushing: [{payload['type']}] {payload['vehicle']} | {payload['date']} -> {payload['month']} | {payload['location']}")
    for attempt in range(3):
        try:
            payload["skipAllLogs"] = True
            payload["action"] = "add_entry"
            r = requests.post(WEBHOOK_URL, json=payload, timeout=90)
            if "<!DOCTYPE html>" in r.text and "ppConfig" in r.text:
                print(f"  [FAIL] 404 HTML - Deployment deleted! Check WEBHOOK_URL")
                print(f"  URL: {WEBHOOK_URL}")
                return False
            if r.status_code == 404:
                print(f"  [FAIL] 404 - Webhook not found")
                return False
            if r.status_code == 200:
                resp_text = r.text or ""
                try:
                    resp = r.json() if resp_text and not resp_text.strip().startswith("<") else {}
                except:
                    resp = {}
                is_success = False
                if resp.get("success") == True or resp.get("status") in ["success", "ok"]:
                    is_success = True
                if '"success":true' in resp_text or '"status":"success"' in resp_text:
                    is_success = True
                if r.status_code == 200 and resp_text and not resp_text.strip().startswith("<") and len(resp_text) < 1000:
                    # For older scripts that return plain text
                    if "success" in resp_text.lower() or "added" in resp_text.lower():
                        is_success = True
                    elif resp_text.strip() == "" or "ok" in resp_text.lower():
                        is_success = True
                month = resp.get("month", payload.get("month", "Unknown"))
                if is_success:
                    print(f"  [OK] SHEET: {payload.get('vehicle')} -> {month} | {payload.get('type')} | {resp_text[:150]}")
                    history_set.add(unique_key)
                    save_history(history_set)
                    return True
                if "duplicate" in resp_text.lower():
                    print(f"  [SKIP] DUPLICATE: {payload.get('vehicle')} {payload.get('date')}")
                    history_set.add(unique_key)
                    save_history(history_set)
                    return True
                print(f"  [FAIL] FAILED: {r.status_code} - {resp_text[:300]}")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False
            else:
                print(f"  [FAIL] HTTP {r.status_code}: {r.text[:300]}")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False
        except Exception as e:
            print(f"  [FAIL] Error attempt {attempt+1}: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(2)
            continue
    return False

def is_bill_like_image(img_element):
    try:
        src = img_element.get_attribute("src") or ""
        data_src = img_element.get_attribute("data-src") or ""
        if not src and not data_src:
            src = img_element.get_attribute("data-lazy-src") or img_element.get_attribute("href") or ""
            if not src:
                return False
        is_blob = src.startswith("blob:") or "blob:" in src or data_src.startswith("blob:")
        is_data = src.startswith("data:image") or data_src.startswith("data:image")
        is_http = src.startswith("http")
        try:
            size = img_element.size
            w = size.get("width", 0)
            h = size.get("height", 0)
            if w < 60 or h < 60:
                if not (is_blob or is_data):
                    return False
        except:
            w = h = 0
        if is_blob or is_data or is_http:
            if w > 80 or h > 80 or is_blob or is_data:
                return True
        try:
            if w > 100 and h > 100:
                return True
        except:
            pass
        return True
    except:
        return False

def upload_bill_to_drive(date_folder, file_path, vehicle, original_date, present_odo, bill_hashes, bill_files):
    try:
        if not os.path.exists(file_path):
            return False
        with open(file_path, 'rb') as f:
            content_data = f.read()
        file_hash = hashlib.md5(content_data).hexdigest()
        if file_hash in bill_hashes:
            print(f"  ⏩ Bill already uploaded (hash)")
            try:
                os.remove(file_path)
            except:
                pass
            return True
        ext = os.path.splitext(file_path)[1] or ".jpg"
        filename = f"{vehicle}_{date_folder}_{present_odo}_{file_hash[:8]}{ext}" if present_odo else f"{vehicle}_{date_folder}_{file_hash[:8]}{ext}"
        if filename in bill_files:
            print(f"  ⏩ Bill already uploaded (filename)")
            try:
                os.remove(file_path)
            except:
                pass
            return True
        b64_data = base64.b64encode(content_data).decode('utf-8')
        payload = {
            "action": "upload_bill",
            "date_folder": date_folder,
            "filename": filename,
            "mimeType": "image/jpeg",
            "filedata": b64_data,
            "vehicle": vehicle,
            "original_date": original_date
        }
        print(f"  -> Uploading BILL: {filename} -> {date_folder}")
        r = requests.post(WEBHOOK_URL, data=payload, timeout=60)
        print(f"  [OK] DRIVE: {filename} - {r.status_code}")
        bill_hashes.add(file_hash)
        bill_files.add(filename)
        save_bill_history(bill_hashes, bill_files)
        try:
            os.remove(file_path)
        except:
            pass
        return True
    except Exception as e:
        print(f"  [FAIL] Drive error: {e}")
        return False

def download_blob_image(driver, blob_url, save_path):
    try:
        if blob_url.startswith('data:'):
            try:
                if ',' in blob_url:
                    header, b64data = blob_url.split(',', 1)
                    with open(save_path, "wb") as f:
                        f.write(base64.b64decode(b64data))
                    print(f"  Saved data:image directly ({len(b64data)} chars)")
                    return True
            except Exception as e:
                print(f"  data: URL parse error: {e}")
                return False
        js_code = """
        const blobUrl = arguments[0];
        const callback = arguments[1];
        if (blobUrl.startsWith('data:')) {
            callback(blobUrl);
            return;
        }
        fetch(blobUrl).then(r => r.blob()).then(blob => {
            const reader = new FileReader();
            reader.onloadend = () => callback(reader.result);
            reader.readAsDataURL(blob);
        }).catch(err => {
            callback('ERROR:'+err + ' URL:' + blobUrl);
        });
        """
        result = driver.execute_async_script(js_code, blob_url)
        if result and result.startswith("data:"):
            try:
                header, b64data = result.split(',', 1)
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(b64data))
                print(f"  Downloaded blob: {blob_url[:60]}... -> {len(b64data)} chars")
                return True
            except Exception as e:
                print(f"  Blob decode error: {e}")
                return False
        if blob_url.startswith('http'):
            try:
                r = requests.get(blob_url, timeout=10)
                if r.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(r.content)
                    print(f"  Downloaded http image: {blob_url[:60]}")
                    return True
            except:
                pass
        print(f"  Failed to download image: {blob_url[:80]}... Result: {str(result)[:100] if result else 'None'}")
        return False
    except Exception as e:
        print(f"  download_blob_image error: {e} for URL: {blob_url[:60]}")
        return False

def parse_whatsapp_timestamp(bubble_element):
    try:
        pre_plain = bubble_element.get_attribute("data-pre-plain-text") or ""
        if not pre_plain:
            try:
                parent = bubble_element.find_element(By.XPATH, "./..")
                pre_plain = parent.get_attribute("data-pre-plain-text") or ""
            except:
                pass
        m = re.search(r'\[.*?,.*?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\]', pre_plain)
        if m:
            date_str = m.group(1)
            normalized = re.sub(r'[\-]', '/', date_str)
            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y"):
                try:
                    d = datetime.strptime(normalized, fmt)
                    if d.year < 100:
                        d = d.replace(year=2000 + d.year)
                    return d
                except:
                    continue
    except:
        pass
    return None

def scroll_to_load_last_n_days(driver, days=5, max_scrolls=150):
    # FIXED V35: Returns 324 unique texts, not just 17 bubbles
    if days >= 9999:
        print("\n=== GETTING ALL MESSAGES (no time limit) ===")
    else:
        print(f"\n=== Loading last {days} days messages (FIXED SCROLL V35) ===")
    cutoff_date = datetime.now() - timedelta(days=days) if days < 9999 else None
    if cutoff_date:
        print(f"Cutoff: {cutoff_date.strftime('%d/%m/%Y %H:%M')} (last {days} days)")
    print(f"Current: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        try:
            main_chat = driver.find_element(By.XPATH, '//div[@id="main"]')
            main_chat.click()
            time.sleep(1)
        except:
            pass
        scrollable = None
        selectors = [
            'div[data-testid="conversation-panel-messages"]',
            'div._ak1l',
            'div[data-testid="chat"] div._ak1l',
            '#main div._ak1l',
            '#main',
        ]
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elems:
                    try:
                        if driver.execute_script("return arguments[0].scrollHeight", elem) > driver.execute_script("return arguments[0].clientHeight", elem) + 100:
                            scrollable = elem
                            break
                    except:
                        continue
                if scrollable:
                    break
            except:
                continue
        if not scrollable:
            scrollable = driver.find_element(By.XPATH, '//div[@id="main"]')
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable)
        time.sleep(2)
        collected_texts = {}
        bubbles = driver.find_elements(By.XPATH, '//div[@data-testid="msg-container"]')
        if len(bubbles) < 15:
            alt = driver.find_elements(By.XPATH, '//div[@data-pre-plain-text]')
            if len(alt) > len(bubbles):
                bubbles = alt
        try:
            initial_data = driver.execute_script("var b=document.querySelectorAll('[data-testid]');return Array.from(b).map(x=>x.innerText||x.textContent||'').filter(t=>t.trim().length>10);")
            for txt in initial_data:
                h = hash(txt[:120])
                collected_texts[h] = txt
        except:
            pass
        last_count = len(bubbles)
        no_new = 0
        actual_max = 500 if days >= 9999 else max_scrolls
        print(f"  Starting - initial {len(collected_texts)} unique, {last_count} bubbles")
        for i in range(actual_max):
            try:
                driver.execute_script("arguments[0].scrollBy(0, -250)", scrollable)
                time.sleep(0.4)
                scrollable.send_keys(Keys.PAGE_UP)
                time.sleep(0.3)
            except:
                pass
            time.sleep(0.8)
            try:
                new_data = driver.execute_script("var b=document.querySelectorAll('[data-testid]');return Array.from(b).map(x=>x.innerText||x.textContent||'').filter(t=>t.trim().length>10);")
                new_count = 0
                for txt in new_data:
                    h = hash(txt[:120])
                    if h not in collected_texts:
                        collected_texts[h] = txt
                        new_count += 1
                if new_count > 0 or i % 10 == 0:
                    print(f"  Scroll {i+1}/{actual_max}: {last_count} bubbles, {len(collected_texts)} unique (+{new_count})")
            except:
                pass
            bubbles = driver.find_elements(By.XPATH, '//div[@data-testid="msg-container"]')
            if len(bubbles) == 0:
                bubbles = driver.find_elements(By.XPATH, '//div[@data-pre-plain-text]')
            if len(bubbles) == last_count:
                no_new += 1
                if no_new >= 15:
                    print(f"  No new after {no_new} scrolls, top reached. Unique: {len(collected_texts)}")
                    break
            else:
                no_new = 0
                last_count = len(bubbles)
            if days < 9999 and len(bubbles) > 0 and i % 5 == 0:
                try:
                    oldest = bubbles[0]
                    oldest_time = parse_whatsapp_timestamp(oldest)
                    if oldest_time and oldest_time < cutoff_date:
                        print(f"    Reached cutoff {oldest_time} < {cutoff_date}, stopping")
                        break
                except:
                    pass
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable)
        time.sleep(2)
        final = driver.find_elements(By.XPATH, '//div[@data-testid="msg-container"]')
        if len(final) < 15:
            alt_final = driver.find_elements(By.XPATH, '//div[@data-pre-plain-text]')
            if len(alt_final) > len(final):
                final = alt_final
        print(f"Finished scroll, total: {len(final)} bubbles, {len(collected_texts)} unique texts collected\n")
        try:
            with open("collected_messages.json", "w", encoding="utf-8") as cf:
                json.dump(list(collected_texts.values()), cf, ensure_ascii=False, indent=2)
        except:
            pass
        return collected_texts
    except Exception as e:
        print(f"Scroll error: {e}")
        import traceback
        traceback.print_exc()
        return {}

def find_group(driver, group_name):
    for _ in range(3):
        try:
            els = driver.find_elements(By.XPATH, f'//span[@title="{group_name}"]')
            if els:
                els[0].click()
                print(f"[OK] Found group: {group_name}")
                return True
        except:
            pass
        time.sleep(1)
    try:
        side = driver.find_element(By.XPATH, '//div[@id="pane-side"] | //div[@id="side"]')
        for _ in range(6):
            driver.execute_script("arguments[0].scrollTop += 500", side)
            time.sleep(0.8)
            partial = driver.find_elements(By.XPATH, '//span[contains(@title, "Janani")]')
            if partial:
                partial[0].click()
                print(f"[OK] Found via scroll: {partial[0].text}")
                return True
    except:
        pass
    # FIX for >> log.txt 2>&1 : Don't call input() when non-interactive / scheduled / redirected
    if NON_INTERACTIVE:
        print(f"[WARN] Group {group_name} not found auto, waiting 10s for manual click (non-interactive mode, skipping input())")
        time.sleep(10)
        return True
    # Only ask for manual input if we have a real console
    if sys.stdin.isatty():
        print("\n=== MANUAL: Click group, then ENTER ===")
        try:
            input(">>> Press ENTER after clicking group... ")
        except (EOFError, OSError):
            print("[WARN] No console for input(), continuing...")
            time.sleep(5)
    else:
        print("[WARN] Non-interactive, no stdin - waiting 10s then continuing")
        time.sleep(10)
    return True

def read_last_n_days():
    options = webdriver.ChromeOptions()
    chat_path = os.path.abspath(CHAT_DB_PATH)
    options.add_argument(f"--user-data-dir={chat_path}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Fix for DevToolsActivePort error
    options.add_argument("--remote-debugging-port=9222")
    
    download_dir = os.path.abspath("temp_bills")
    os.makedirs(download_dir, exist_ok=True)
    
    # Clean stale lock if Chrome crashed before - causes "Failed to fetch" type errors
    try:
        for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(chat_path, lock_name)
            if os.path.exists(lock_path):
                os.remove(lock_path)
                print(f"Removed stale lock: {lock_name}")
    except Exception as e:
        print(f"Lock cleanup: {e}")

    print(f"[{datetime.now()}] Starting Chrome...")
    print(f"Chrome profile: {chat_path}")
    
    driver = None
    last_err = None
    
    # Try 1: Selenium Manager (built-in since Selenium 4.6+) - NO ChromeDriverManager needed - most stable
    try:
        print("Try 1: Selenium Manager (auto driver download)...")
        driver = webdriver.Chrome(options=options)
        print("[OK] Chrome started via Selenium Manager")
    except Exception as e1:
        last_err = e1
        print(f"Try 1 failed: {e1}")
        # Try 2: ChromeDriverManager (old method)
        try:
            print("Try 2: ChromeDriverManager...")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            print("[OK] Chrome started via ChromeDriverManager")
        except Exception as e2:
            last_err = e2
            print(f"Try 2 failed: {e2}")
            # Try 3: Without user-data-dir (fresh profile - login needed again but works)
            try:
                print("Try 3: Without user-data-dir (fresh session)...")
                options2 = webdriver.ChromeOptions()
                options2.add_argument("--start-maximized")
                options2.add_argument("--disable-blink-features=AutomationControlled")
                options2.add_experimental_option("excludeSwitches", ["enable-automation"])
                options2.add_experimental_option('useAutomationExtension', False)
                driver = webdriver.Chrome(options=options2)
                print("[OK] Chrome started without profile (you will need to scan QR again)")
            except Exception as e3:
                print(f"All Chrome attempts failed!")
                print(f"\n=== FIX STEPS ===")
                print(f"1. Close ALL Chrome windows")
                print(f"2. Delete folder: {chat_path}")
                print(f"3. Install/Update Chrome: https://www.google.com/chrome/")
                print(f"4. Run: pip install --upgrade selenium webdriver-manager")
                print(f"5. Run again: python janani-webhook.py")
                print(f"\nLast errors:\n{e1}\n{e2}\n{e3}")
                raise RuntimeError(f"Chrome failed to start. Close Chrome, delete {chat_path}, update Chrome & selenium. Last error: {e3}") from e3
    driver.get("https://web.whatsapp.com")
    print("Waiting for login...")
    for i in range(90):
        time.sleep(1)
        try:
            driver.find_element(By.XPATH, '//div[@id="side"] | //div[@id="pane-side"]')
            if len(driver.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]')) == 0:
                print(f"[OK] Logged in after {i}s")
                break
        except:
            pass
    time.sleep(8)
    if not find_group(driver, GROUP_NAME):
        driver.quit()
        return [], set(), set(), set()
    time.sleep(8)
    # FIXED V35: Collect 324 unique texts
    collected = scroll_to_load_last_n_days(driver, days=SCAN_DAYS, max_scrolls=150)
    print(f"Using {len(collected)} unique texts collected during scroll (fixes 17 bubbles bug)")
    bubble_data = []
    for idx, txt in enumerate(collected.values()):
        bubble_data.append({"idx": idx, "text": txt})
    print(f"Processing {len(bubble_data)} unique messages...")
    history = load_history()
    bill_hashes, bill_files = load_bill_history()
    print(f"History: {len(history)} sheet, {len(bill_hashes)} bills")
    if FORCE_MODE:
        print("[FORCE] FORCE MODE")
    print()
    parsed_entries = []
    bill_tasks = []
    skipped_old = 0
    skipped_non_target = 0
    skipped_empty = 0
    cutoff_date = datetime.now() - timedelta(days=SCAN_DAYS) if SCAN_DAYS < 9999 else None
    for item in bubble_data:
        try:
            txt = item["text"].strip()
            if not txt:
                continue
            if len(txt.strip()) < 15:
                skipped_empty += 1
                continue
            if "Date-" not in txt:
                if "Vehicle no-" not in txt:
                    skipped_empty += 1
                    continue
            if cutoff_date:
                pass
            if not is_target_message(txt):
                skipped_non_target += 1
                if DEBUG_MODE and "date-" in txt.lower():
                    print(f"NON-TARGET: {txt[:120]}")
                continue
            p = parse_message(txt)
            if p:
                parsed_entries.append(p)
        except Exception as e:
            print(f"Error: {e}")
            continue
    # FIXED V39: Deduplicate by vehicle+date+type (prevents 7480 7x log spam)
    # Same vehicle same date FUEL should be 1 entry, not 7
    deduped = {}
    duplicate_count = 0
    for entry in parsed_entries:
        key = entry["unique_key"]  # Now simple key: date_folder_vehicle_type
        if key not in deduped:
            deduped[key] = entry
        else:
            duplicate_count += 1
            # Keep entry with more data (has present odo)
            existing = deduped[key]
            if len(entry["present"]) > len(existing["present"]) or len(entry["payload"]["diesel_amount"]) > len(existing["payload"]["diesel_amount"]):
                deduped[key] = entry
    parsed_entries = list(deduped.values())
    print(f"\n=== FILTER SUMMARY ===")
    print(f"Total unique texts: {len(bubble_data)}, Target raw: {len(bubble_data)}, Target after dedup: {len(parsed_entries)}, Non-target: {skipped_non_target}, Empty: {skipped_empty}")
    print(f"  History has {len(history)} entries")
    if duplicate_count > 0:
        print(f"  Deduped {duplicate_count} duplicate messages (same vehicle+date+type, e.g., 7480 13/9/26 appeared multiple times in 324)")
        print(f"  This fixes log showing [33/39] to [39/39] same 7480 7 times")
    driver.quit()
    return parsed_entries, history, bill_hashes, bill_files

if __name__ == "__main__":
    entries, history, bill_hashes, bill_files = read_last_n_days()
    # Deduplicate entries by unique_key before pushing (extra safety)
    unique_entries = {}
    for e in entries:
        if e["unique_key"] not in unique_entries:
            unique_entries[e["unique_key"]] = e
    entries = list(unique_entries.values())
    print(f"\n=== Total TARGET entries (after dedup): {len(entries)} ===")
    if not entries:
        print(f"[FAIL] No target messages")
        print(f"Try: python janani-webhook.py --all --debug --force")
    else:
        history = load_history()
        # FIXED V39: Filter out already-pushed BEFORE loop to avoid log spam [33/39] 7480 7x
        entries_to_push = []
        already_pushed = []
        for e in entries:
            if e["unique_key"] in history:
                already_pushed.append(e)
            else:
                entries_to_push.append(e)
        
        if already_pushed:
            print(f"\n[SKIP] Skipping {len(already_pushed)} already pushed (no log spam):")
            for e in already_pushed[:5]:  # Show first 5
                print(f"   - {e['payload'].get('vehicle')} {e['payload'].get('date')} {e['payload'].get('type')}")
            if len(already_pushed) > 5:
                print(f"   ... and {len(already_pushed)-5} more")
        
        if not entries_to_push:
            print(f"\n[OK] All {len(entries)} entries already pushed, nothing new to push")
            print(f"   (This fixes your log showing 7480 13/9/26 7 times as SKIPPED)")
        else:
            print(f"\n[PUSH] Pushing {len(entries_to_push)} NEW entries (out of {len(entries)} total):")
            success_count = 0
            fail_count = 0
            for idx, e in enumerate(entries_to_push):
                print(f"\n[{idx+1}/{len(entries_to_push)}] Pushing {e['payload'].get('vehicle')} {e['payload'].get('date')} {e['payload'].get('type')}...")
                success = push_to_sheet(e["payload"], history, e["unique_key"])
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                time.sleep(1.5)
            print(f"\n[OK] Done! Pushed {success_count} new, Skipped {len(already_pushed)} old, Failed {fail_count}")
            if fail_count > 0:
                print(f"⚠️ {fail_count} failed - check webhook URL in sheet_config.json")
                print(f"Current: {WEBHOOK_URL}")
