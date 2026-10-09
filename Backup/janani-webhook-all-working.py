"""
JANANI FLEET - V78 - FIXED FUEL NOT PUSHING + DEBUG MODE
- New fuel entry not pushing? V78 shows WHY
- Added --force flag to force push even if in history
- Added detailed fuel debug logging
- Fixed fuel parsing edge cases

Usage:
python FINAL_V78_FIXED_FUEL_PUSH.py --days 7 --debug-fuel
python FINAL_V78_FIXED_FUEL_PUSH.py --days 1 --force --debug-fuel
"""

import os, re, time, requests, json, hashlib, sys, io, platform
from datetime import datetime, timedelta

def detect_windows():
    info = {"is_windows": platform.system() == "Windows", "is_win8_family": False}
    if not info["is_windows"]: return info
    ver = platform.version()
    if "6.2" in ver or "6.3" in ver: info["is_win8_family"] = True
    return info

WIN_INFO = detect_windows()
IS_WIN8_FAMILY = WIN_INFO["is_win8_family"]

try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except: pass

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

GROUP_NAME = "Janani AI Reporting"
GROUP_ALIASES = ["Janani AI Reporting", "Janani Reporting", "Janani AI", "Janani"]
CHAT_DB_PATH = "whatsapp_session_janani"
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxv1nErWrIV55nPz0NjXjvc71HMxnaeekujImRkl3y7cz0ptSpsUd3yVJS5jCAuqU4/exec"
HISTORY_FILE = "pushed_history.json"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

DEFAULT_DAYS = 30
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

CONFIG_FILE = "sheet_config.json"
if os.path.exists(CONFIG_FILE):
    try:
        cfg = json.load(open(CONFIG_FILE, encoding='utf-8'))
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
    "Vehicle no": ["Vehicle no", "Vehicle No", "Vehicle", "Vehicle No.", "Veh No", "Veh no", "V No"],
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

def clean_text_for_parsing(text):
    if not text: return text
    if "Janani Reporting" in text and text.count(",") >= 4:
        return text.split(",")[0].strip()
    return text

def get_field(key, text):
    cleaned = clean_text_for_parsing(text)
    aliases = FIELD_ALIASES.get(key, [key])
    for alias in aliases:
        pattern = rf"{re.escape(alias)}\s*[-:]*\s*"
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            start = m.end()
            next_m = re.search(ALL_KEYS_PATTERN, cleaned[start:], re.IGNORECASE)
            if next_m: val = cleaned[start:start+next_m.start()].strip()
            else: val = cleaned[start:].strip().split("\n")[0].split(",")[0].strip()
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
        pattern = rf"{re.escape(alias)}\s*[:\-]?\s*([A-Za-z0-9\.\s\/]+)"
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            val = m.group(1).strip().split("\n")[0][:40]
            if val and val.lower() not in ["null", "-", "", "presentodo", "fuel", "vehicle no"]:
                # Check if val is not another field name
                if len(val) > 2 and not re.match(r'^(PRESENT|PREVIOUS|DIESEL|VEHICLE|PUMP|PILOT|LOCATION|DATE)', val, re.I):
                    return val
    return ""

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

def parse_message_debug(text, image_data="", original_text_for_vehicle="", debug=False):
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
    if not date_str:
        m = re.search(r"^\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", cleaned)
        if m: date_str = m.group(1)
    if not date_str:
        m = re.search(r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", check_text)
        if m: date_str = m.group(1)
        else: date_str = datetime.now().strftime("%d/%m/%y")
    
    date_folder, d, month_name = parse_date_strict_ddmmyyyy(date_str)
    
    veh_raw = get_field("Vehicle no", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
    vehicle_raw = normalize_vehicle_raw(veh_raw)
    if not vehicle_raw:
        for pat in [r"Vehicle\s*no[^A-Z0-9]*([A-Z0-9]{3,10})", r"Vehicle\s*[:\-]\s*([A-Z0-9]{3,10})"]:
            m = re.search(pat, (text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text), re.IGNORECASE)
            if m:
                vehicle_raw = normalize_vehicle_raw(m.group(1))
                if vehicle_raw: break
    if not vehicle_raw:
        m = re.search(r"\b([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4})\b", (text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text).upper())
        if m: vehicle_raw = normalize_vehicle_raw(m.group(1))
    
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
                debug_info.append(f"Vehicle parse failed: veh_raw='{veh_raw}' normalized='{vehicle_raw}' len>{15 if vehicle_raw and len(vehicle_raw)>15 else 'empty'} for text: {check_text[:100]}")
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
        
        present = re.sub(r"\D", "", present_raw)[:7]
        prev = re.sub(r"\D", "", prev_raw)[:7]
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
        full_hash = hashlib.md5(image_data.encode('utf-8', errors='ignore')).hexdigest()[:20]
        image_hash_for_payload = full_hash
        file_name_for_payload = f"{vehicle_raw}_{date_folder.replace('/','')}_{full_hash[:12]}.jpg"
        original_date_for_payload = date_folder
    
    payload = {
        "action": "insert",
        "date": date_folder,
        "location": capitalize_name(get_field("Location", text)),
        "vehicle": vehicle_raw,
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
        "image_url": "",
        "image_hash": image_hash_for_payload,
        "file_name": file_name_for_payload,
        "original_date": original_date_for_payload,
        "target_sheet": target_sheet
    }
    
    if image_data:
        img_hash = image_hash_for_payload
        simple_key = f"{date_folder}_{img_hash}_BILL".lower()
    else:
        if msg_type == "FUEL":
            simple_key = f"{date_folder}_{vehicle_raw}_{present}_{prev}_FUEL".lower()
        else:
            simple_key = f"{date_folder}_{vehicle_raw}_{bill_amount}_{work_details[:30]}_MAINT".lower()
    
    return {"month": month_name, "date_folder": date_folder, "unique_key": simple_key, "payload": payload, "date_obj": d, "type": msg_type, "present": present, "has_image": bool(image_data)}, debug_info

def parse_message(text, image_data="", original_text_for_vehicle=""):
    result, _ = parse_message_debug(text, image_data, original_text_for_vehicle, debug=False)
    return result

def load_history():
    if os.path.exists(HISTORY_FILE):
        try: return set(json.load(open(HISTORY_FILE, encoding='utf-8')))
        except: return set()
    return set()

def save_history(s):
    json.dump(list(s), open(HISTORY_FILE, 'w', encoding='utf-8'), indent=2)

def get_chrome_options_universal():
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    session_path = os.path.abspath(CHAT_DB_PATH)
    if not os.path.exists(session_path): os.makedirs(session_path, exist_ok=True)
    if platform.system() == "Windows":
        for lock_name in ["SingletonLock","SingletonSocket","SingletonCookie","lockfile"]:
            lock_path = os.path.join(session_path, lock_name)
            if os.path.exists(lock_path):
                try: os.remove(lock_path)
                except: pass
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
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=get_chrome_options_universal())
    except:
        driver = webdriver.Chrome(options=get_chrome_options_universal())
    return driver

def find_group(driver, group_name):
    aliases = GROUP_ALIASES if group_name == GROUP_NAME else [group_name] + GROUP_ALIASES
    for attempt_name in aliases:
        try:
            print(f"[INFO] Searching for group: {attempt_name}")
            try:
                search_box = driver.find_element(By.XPATH, '//div[@contenteditable="true"][@data-tab="3"] | //div[@title="Search or start new chat"] | //div[@contenteditable="true"]')
                search_box.click()
                time.sleep(0.5)
                search_box.send_keys(Keys.CONTROL + "a")
                search_box.send_keys(Keys.BACKSPACE)
                time.sleep(0.5)
                search_box.send_keys(attempt_name)
                time.sleep(2)
            except: pass
            elems = driver.find_elements(By.XPATH, f'//span[@title="{attempt_name}"] | //span[contains(@title, "{attempt_name}")]')
            for elem in elems:
                try:
                    title = (elem.get_attribute("title") or elem.text or "").strip()
                    if not title or len(title) < 3: continue
                    if "janani" in title.lower() or attempt_name.lower() in title.lower():
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
            messages = driver.execute_script("""
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
                    if(text.length < 10 || text.length > 3000) return;
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
                    result.push({idx: idx, text: text || (isForwarded ? '[FORWARDED_BILL_IMAGE]' : '[IMAGE_ONLY_BILL]'), hasImage: hasImage, imgCount: imgCount, isForwarded: isForwarded, textLength: text.length});
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
                    h = hashlib.md5(f"{txt[:100]}_{msg.get('imgCount',0)}_{msg.get('isForwarded',False)}_{msg.get('idx')}".encode('utf-8', errors='ignore')).hexdigest()[:16]
                    if h not in collected:
                        image_data = ""
                        if has_img:
                            try:
                                b64 = driver.execute_async_script("""
                                    const callback = arguments[arguments.length - 1];
                                    const searchText = arguments[0];
                                    const targetIdx = arguments[2];
                                    (async () => {
                                        try {
                                            const selectors = ['div[data-testid="msg-container"]','div[data-id]','div.message-in','div.message-out','div[role="row"]'];
                                            let nodes = [];
                                            for(let sel of selectors){ let found = document.querySelectorAll(sel); if(found.length > nodes.length) nodes = found; }
                                            let targetNode = null;
                                            for(let n of nodes){
                                                let t = n.innerText || '';
                                                if(t && t.includes(searchText.substring(0,30))){ targetNode = n; break; }
                                            }
                                            if(!targetNode && targetIdx < nodes.length) targetNode = nodes[targetIdx];
                                            if(targetNode){
                                                targetNode.scrollIntoView({behavior: 'smooth', block: 'center'});
                                                await new Promise(r => setTimeout(r, 800));
                                                let imgs = Array.from(targetNode.querySelectorAll('img'));
                                                let sorted = imgs.filter(img => {
                                                    let src = img.src || '';
                                                    return !(src.includes('avatar') || src.includes('pps') || src.includes('sticker'));
                                                }).sort((a,b) => (b.naturalWidth*b.naturalHeight) - (a.naturalWidth*a.naturalHeight));
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
                                                for(let img of sorted){
                                                    let src = img.src || '';
                                                    if(src.startsWith('blob:')){
                                                        try{
                                                            let resp = await fetch(src);
                                                            let blob = await resp.blob();
                                                            let reader = new FileReader();
                                                            reader.onloadend = () => callback(reader.result);
                                                            reader.readAsDataURL(blob);
                                                            return;
                                                        }catch(e){}
                                                    }
                                                }
                                            }
                                            callback("");
                                        } catch(e){ callback(""); }
                                    })();
                                """, txt[:100], msg.get('isForwarded', False), msg.get('idx', 0))
                                if b64 and len(b64) > 5000: image_data = b64
                            except: pass
                        collected[h] = {"text": txt, "image_data": image_data}
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
        print("Waiting login 90s - Scan QR")
        for i in range(90):
            time.sleep(1)
            try:
                driver.find_element(By.XPATH, '//div[@id="side"] | //div[@id="pane-side"]')
                if len(driver.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]')) == 0:
                    print(f"[OK] Logged in after {i}s")
                    break
            except: pass
        time.sleep(8 if IS_WIN8_FAMILY else 5)
        if not find_group(driver, GROUP_NAME):
            print(f"[FAIL] Group {GROUP_NAME} not found")
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
            
            if img_data and len(img_data) < 5000:
                if not is_target_message(txt):
                    continue
                img_data = ""
            
            result, debug_info = parse_message_debug(txt, image_data=img_data, original_text_for_vehicle=txt, debug=DEBUG_FUEL)
            if result:
                if result.get('date_obj') and result['date_obj'] < cutoff_date and not result.get('has_image'):
                    if DEBUG_FUEL and result.get('type') == 'FUEL':
                        print(f"  [FILTERED BY DATE] Fuel {result['payload']['vehicle']} {result['date_folder']} < cutoff {cutoff_date.strftime('%d/%m/%y')}")
                    continue
                parsed.append(result)
            else:
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
    print("="*60)
    print(f"JANANI V78 FIXED FUEL NOT PUSHING - {DAYS_TO_SCAN} Days")
    print(f"Force: {FORCE_PUSH} | Debug Fuel: {DEBUG_FUEL}")
    print("="*60)
    entries, history = read_last_n_days(days=DAYS_TO_SCAN)
    entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
    print(f"\nTotal found: {len(entries)} (after dedup within run)")
    print(f"History: {len(history)} entries")
    if not entries:
        print("[FAIL] No messages")
        print("[HINT] Try: python FINAL_janani_webhook.py --days 1 --debug-fuel --force")
    else:
        fuel_entries = [e for e in entries if e.get('type') == 'FUEL']
        print(f"\nFuel entries found: {len(fuel_entries)}")
        for e in fuel_entries[:10]:
            p = e['payload']
            in_hist = "IN HISTORY (will skip unless --force)" if e['unique_key'] in history else "NEW"
            print(f"  {e['date_folder']} ⛽ {p['vehicle']} | Present:{p['present_odo']} Prev:{p['previous_odo']} | {p['diesel_amount']}L | {in_hist} | key={e['unique_key'][:40]}")
        
        if FORCE_PUSH:
            to_push = entries
            print(f"\n[FORCE] Pushing ALL {len(to_push)} entries (ignoring history)")
        else:
            to_push = [e for e in entries if e["unique_key"] not in history]
            print(f"\nNew to push: {len(to_push)} (Fuel: {sum(1 for e in to_push if e['payload'].get('type')=='FUEL')} + Bills: {sum(1 for e in to_push if e['payload'].get('has_image'))})")
            print(f"Will SKIP {len(entries) - len(to_push)} already in history")
            if len(to_push) == 0:
                print("\n⚠️ No new entries! If you have new fuel entry but it's not pushing:")
                print("  1. It might already be in pushed_history.json with same key")
                print("  2. Delete pushed_history.json and run again")
                print("  3. Or run with --force flag: python FINAL_janani_webhook.py --days 1 --force")
                print("  4. Or run with --debug-fuel to see why fuel parsing failed")
        
        push_list = to_push
        
        for idx, e in enumerate(push_list):
            payload = e['payload']
            has_img = "📷 BILL" if payload.get('has_image') else "⛽ FUEL"
            size = len(payload.get('image_data',''))/1024 if payload.get('image_data') else 0
            target = payload.get('target_sheet', 'unknown')
            print(f"[{idx+1}/{len(push_list)}] {has_img} {payload['vehicle']} {payload['date']} {payload['type']} | {size:.1f}KB -> {target}")
            
            try:
                r = requests.post(WEBHOOK_URL, json=payload, timeout=90)
                resp_text = r.text
                if resp_text.strip().startswith("<!DOCTYPE"):
                    print(f"  -> ❌ APPS SCRIPT ERROR")
                    continue
                print(f"  -> {resp_text[:800]}")
                try:
                    j = json.loads(resp_text)
                    if j.get("success"):
                        if not FORCE_PUSH:
                            history.add(e["unique_key"])
                            save_history(history)
                        if j.get("sheet"):
                            print(f"  -> ✅ Inserted into: {j.get('sheet')}")
                        if j.get("duplicate"):
                            print(f"  -> ⚠️ Sheet says duplicate: {j.get('reason')} - adding to history to prevent re-push")
                            history.add(e["unique_key"])
                            save_history(history)
                except:
                    if "inserted" in resp_text or "duplicate" in resp_text:
                        if not FORCE_PUSH:
                            history.add(e["unique_key"])
                            save_history(history)
                time.sleep(2)
            except Exception as ex:
                print(f"  Push failed: {ex}")
        
        print("\n[DONE] V78")
