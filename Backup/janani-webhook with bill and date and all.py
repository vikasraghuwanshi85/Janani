"""
JANANI FLEET - FINAL V76 - FIXED NOT SCROLLING - 0 MESSAGES ISSUE
Fixes screenshot: Scroll 0-10 Found 0 message containers

Root cause: WhatsApp Web updated DOM - div[data-testid="msg-container"] and div.message-in/out no longer work
New WhatsApp uses: div[data-id], div with role=row, and different panel structure

V76 Fix:
1. Tries 10+ selectors for message containers
2. Tries 8+ selectors for scrollable chat panel
3. Uses JS to dump DOM and find messages dynamically
4. Scrolls correctly in new WhatsApp Web layout
5. Debug mode shows what it finds

Usage:
python FINAL_V76_FIXED_SCROLLING.py --all --debug
python FINAL_V76_FIXED_SCROLLING.py --days 30
"""

import os, re, time, requests, json, hashlib, sys, io, platform, base64
from datetime import datetime, timedelta

def detect_windows():
    info = {"is_windows": platform.system() == "Windows", "is_win8_family": False, "is_win11": False}
    if not info["is_windows"]: return info
    ver = platform.version()
    if "6.2" in ver or "6.3" in ver: info["is_win8_family"] = True
    elif "10" in ver:
        try:
            build = int(ver.split(".")[-1]) if "." in ver else 0
            if build >= 22000: info["is_win11"] = True
        except: pass
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
    print("[ERROR] pip install selenium webdriver-manager requests")

GROUP_NAME = "Janani AI Reporting"
GROUP_ALIASES = ["Janani AI Reporting", "Janani Reporting", "Janani AI", "Janani"]
CHAT_DB_PATH = "whatsapp_session_janani"
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxv1nErWrIV55nPz0NjXjvc71HMxnaeekujImRkl3y7cz0ptSpsUd3yVJS5jCAuqU4/exec"
HISTORY_FILE = "pushed_history.json"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

DEFAULT_DAYS = 30
DAYS_TO_SCAN = DEFAULT_DAYS
DEBUG_MODE = "--debug" in sys.argv

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
    "Date": ["Date"], "Location": ["Location"],
    "Vehicle no": ["Vehicle no", "Vehicle No", "Vehicle"],
    "Present odo": ["Present odo", "Present Odo"],
    "Previous odo": ["Previous odo", "Previous Odo"],
    "Diesel amount": ["Diesel amount", "Diseal amount", "Diesel Amount"],
    "Diesel liter": ["Diesel liter", "Diseal liter", "Diesel Liter"],
    "Average": ["Average"], "Bill amount": ["Bill amount", "Bill Amount"],
    "Work details": ["Work details", "Work Details"],
    "Pilot name": ["Pilot name", "Pilot Name"], "Pump Name": ["Pump Name", "Pump name"],
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
        pattern = rf"{re.escape(alias)}\s*-\s*"
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            start = m.end()
            next_m = re.search(ALL_KEYS_PATTERN, cleaned[start:], re.IGNORECASE)
            if next_m: val = cleaned[start:start+next_m.start()].strip()
            else: val = cleaned[start:].strip().split("\n")[0].split(",")[0].strip()
            if val and val != "-" and val.lower() != "null":
                if key == "Location":
                    vm = re.search(r"\bVehicle\s*no\b", val, re.I)
                    if vm: val = val[:vm.start()].strip()
                return val
    return ""

def is_target_message(text):
    if not text: return False
    if text in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]']: return True
    check_text = clean_text_for_parsing(text)
    tl = check_text.lower()
    if "present" in tl and "odo" in tl: return True
    if "bill" in tl or "vehicle" in tl or "forwarded" in tl: return True
    if re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", check_text):
        if "vehicle" in tl: return True
    return False

def normalize_vehicle_raw(raw):
    if not raw: return ""
    raw = re.sub(r"PRESENTODO.*|PREVIOUSODO.*|DISEAL.*|BILL.*|WORK.*", "", raw, flags=re.I)
    return re.sub(r"[\s\-]+", "", raw.strip().upper())

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

def parse_message(text, image_data="", original_text_for_vehicle=""):
    check_text = original_text_for_vehicle or text
    if text in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]']:
        check_text = original_text_for_vehicle or ""
    
    if not is_target_message(text) and not is_target_message(check_text):
        if not image_data:
            return None
    
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
        m = re.search(r"\b(\d{4,10})\b", check_text)
        if m: vehicle_raw = f"BILL_{m.group(1)}"
        else: 
            # V77 FIX: Deterministic - hash of text, not timestamp
            txt_hash = hashlib.md5(check_text.encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
            vehicle_raw = f"BILL_{txt_hash}"
    
    if not vehicle_raw or len(vehicle_raw) > 15:
        if image_data: 
            # V77 FIX: Deterministic vehicle - hash of image or text, not timestamp
            if image_data:
                img_hash_temp = hashlib.md5(image_data[:1000].encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
                vehicle_raw = f"BILL_{img_hash_temp}"
            else:
                txt_hash = hashlib.md5(check_text.encode('utf-8', errors='ignore')).hexdigest()[:6].upper()
                vehicle_raw = f"BILL_{txt_hash}"
        else: return None
    
    tl = (text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text).lower()
    
    if image_data: msg_type = "MAINTENANCE"
    elif "present" in tl and "odo" in tl: msg_type = "FUEL"
    else: msg_type = "MAINTENANCE"
    
    present = prev = total_km = diesel_amt_clean = diesel_ltr_clean = average_val = rate_val = bill_amount = work_details = ""
    
    if msg_type == "FUEL":
        present_raw = get_field("Present odo", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        prev_raw = get_field("Previous odo", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        diesel_amt_raw = get_field("Diesel amount", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        diesel_ltr_raw = get_field("Diesel liter", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        avg_raw = get_field("Average", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)
        present = re.sub(r"\D", "", present_raw)[:7]
        prev = re.sub(r"\D", "", prev_raw)[:7]
        diesel_amt_clean = re.sub(r"[^\d.]", "", diesel_amt_raw)[:10]
        diesel_ltr_clean = re.sub(r"[^\d.]", "", diesel_ltr_raw)[:10]
        average_val = re.sub(r"[^\d.]", "", avg_raw)[:10]
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
        "location": get_field("Location", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text) or ("Forwarded Bill" if image_data else ""),
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
        "work_details": work_details,
        "pilot": capitalize_name(get_field("Pilot name", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)) or "Narendra Singh",
        "pump": "Aadeshwar Petroleum" if "aadeshwar" in check_text.lower() or image_data else capitalize_name(get_field("Pump Name", text if text not in ['[IMAGE_ONLY_BILL]', '[FORWARDED_BILL_IMAGE]'] else check_text)),
        "source": "WhatsApp Forwarded Bill Image" if "forwarded" in check_text.lower() or image_data else "WhatsApp Group Direct - Fuel" if msg_type == "FUEL" else "WhatsApp Group Direct",
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
        # V77 FIX: Key based ONLY on image hash + date - same bill image = same key always, no duplicates
        img_hash = image_hash_for_payload
        # Deterministic: date + full image hash = same bill always same key
        simple_key = f"{date_folder}_{img_hash}_BILL".lower()
    else:
        if msg_type == "FUEL":
            simple_key = f"{date_folder}_{vehicle_raw}_{present}_{prev}_FUEL".lower()
        else:
            simple_key = f"{date_folder}_{vehicle_raw}_{bill_amount}_{work_details[:30]}_MAINT".lower()
    
    return {"month": month_name, "date_folder": date_folder, "unique_key": simple_key, "payload": payload, "date_obj": d, "type": msg_type, "present": present, "has_image": bool(image_data)}

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
    print(f"JANANI V76 FIXED SCROLLING - {DAYS_TO_SCAN} Days")
    print("Feature: Fixed 0 messages - New WhatsApp Web selectors")
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
    print(f"[INFO] Collecting with FIXED SCROLLING - {days} days, max scrolls {max_scrolls}")
    collected = {}
    
    # V76 FIXED SCROLLING - New WhatsApp Web structure
    for i in range(max_scrolls):
        try:
            # Try to find messages with MANY selectors - WhatsApp changed DOM
            messages = driver.execute_script("""
                let result = [];
                let debugSelectors = {};
                
                // V76 - Try MANY selectors for message containers (WhatsApp Web updated 2024-2025)
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
                    'div#main div[data-id]',
                    'span[data-testid="msg-container"]',
                    'div[data-testid="chat"] div[data-id]'
                ];
                
                let nodes = [];
                for(let sel of selectors){
                    let found = document.querySelectorAll(sel);
                    debugSelectors[sel] = found.length;
                    if(found.length > 0 && nodes.length == 0){
                        nodes = found;
                        console.log('Using selector: ' + sel + ' found ' + found.length);
                    }
                    if(found.length > nodes.length){
                        nodes = found;
                    }
                }
                
                // Fallback: find by innerText containing Date pattern and Vehicle
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
                    debugSelectors['fallback_vehicle_search'] = nodes.length;
                }
                
                // If still 0, try to find main chat area and get its children
                if(nodes.length == 0){
                    let chatAreas = [
                        'div[data-testid="conversation-panel-messages"]',
                        'div#main',
                        'div[data-testid="chat"]',
                        'div._1c_mC',
                        'div.copyable-area'
                    ];
                    for(let areaSel of chatAreas){
                        let area = document.querySelector(areaSel);
                        if(area){
                            let children = area.querySelectorAll('div');
                            debugSelectors[areaSel + ' children'] = children.length;
                            // Look for divs that look like messages (have text with Vehicle/Date)
                            let msgLike = [];
                            for(let child of children){
                                let txt = child.innerText || '';
                                if(txt.length > 30 && txt.length < 2000){
                                    if(txt.match(/\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}/) && (txt.includes('Vehicle') || txt.includes('Location'))){
                                        msgLike.push(child);
                                    }
                                }
                            }
                            if(msgLike.length > 0){
                                nodes = msgLike;
                                break;
                            }
                        }
                    }
                }
                
                console.log('Debug selectors:', debugSelectors);
                console.log('Final nodes count:', nodes.length);
                
                // Now extract info from nodes
                nodes.forEach((n, idx)=>{
                    let text = '';
                    try{
                        text = n.innerText || n.textContent || '';
                    }catch(e){ text = ''; }
                    text = text.trim();
                    
                    // Skip if too short or too long (not a message)
                    if(text.length < 10 || text.length > 3000) return;
                    // Must contain some keywords
                    let tl = text.toLowerCase();
                    if(!(tl.includes('vehicle') || tl.includes('date') || tl.includes('bill') || tl.includes('location') || tl.includes('present') || n.querySelector('img'))){
                        return;
                    }
                    
                    let innerHTML = n.innerHTML || '';
                    let isForwarded = innerHTML.includes('Forwarded') || text.includes('Forwarded');
                    let hasImage = false;
                    let imgCount = 0;
                    let allImgInfo = [];
                    
                    let imgs = n.querySelectorAll('img');
                    imgs.forEach((img, imgIdx)=>{
                        let w = img.naturalWidth || img.width || 0;
                        let h = img.naturalHeight || img.height || 0;
                        let src = img.src || '';
                        let isProfile = src.includes('avatar') || src.includes('pps') || src.includes('sticker') || src.includes('emoji');
                        let isSmallIcon = (w > 0 && w < 60) && (h > 0 && h < 60);
                        allImgInfo.push({
                            idx: imgIdx,
                            width: w,
                            height: h,
                            src: src.substring(0, 80),
                            isProfile: isProfile,
                            isSmallIcon: isSmallIcon
                        });
                        if(!isProfile && !isSmallIcon && (w >= 80 || src.includes('blob:') || src.includes('mmg') || src.includes('whatsapp.net'))){
                            if(w * h >= 100*100 || src.includes('blob:')){
                                imgCount++;
                                hasImage = true;
                            }
                        }
                    });
                    
                    if(n.querySelector('[data-testid="image-thumb"]')){
                        hasImage = true;
                        imgCount = Math.max(imgCount, 1);
                    }
                    
                    let isBillRelated = false;
                    if(text){
                        let tl2 = text.toLowerCase();
                        if(tl2.includes('vehicle') || tl2.includes('bill') || tl2.includes('forwarded') || /\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}/.test(text)){
                            isBillRelated = true;
                        }
                    }
                    
                    if(hasImage || isBillRelated || isForwarded || text.length > 30){
                        result.push({
                            idx: idx,
                            text: text || (isForwarded ? '[FORWARDED_BILL_IMAGE]' : '[IMAGE_ONLY_BILL]'),
                            hasImage: hasImage,
                            imgCount: imgCount,
                            isForwarded: isForwarded,
                            isBillRelated: isBillRelated,
                            textLength: text.length,
                            allImgInfo: allImgInfo,
                            debugSelectors: (idx==0 ? debugSelectors : null)
                        });
                    }
                });
                
                // Return debug info on first run
                if(result.length == 0 && nodes.length == 0){
                    return [{debugEmpty: true, debugSelectors: debugSelectors, bodyText: document.body.innerText.substring(0,500)}];
                }
                
                return result;
            """)
            
            if DEBUG_MODE and i == 0:
                print(f"  [DEBUG] First scroll JS returned {len(messages) if messages else 0} items")
                if messages and len(messages) > 0 and messages[0].get('debugSelectors'):
                    print(f"  [DEBUG] Selectors tried: {messages[0]['debugSelectors']}")
                if messages and len(messages) > 0 and messages[0].get('debugEmpty'):
                    print(f"  [DEBUG] No nodes found! Selectors: {messages[0].get('debugSelectors')}")
                    print(f"  [DEBUG] Body text preview: {messages[0].get('bodyText','')[:200]}")
            
            found_in_this_scroll = 0
            if messages:
                for msg in messages:
                    if not isinstance(msg, dict): continue
                    if msg.get('debugEmpty'): continue
                    
                    txt = msg.get('text', '')
                    has_img = msg.get('hasImage', False)
                    
                    if not has_img and len(txt) < 10:
                        continue
                    
                    # Skip debug entries
                    if 'debugSelectors' in msg and not txt:
                        continue
                    
                    h = hashlib.md5(f"{txt[:100]}_{msg.get('imgCount',0)}_{msg.get('isForwarded',False)}_{msg.get('idx')}".encode('utf-8', errors='ignore')).hexdigest()[:16]
                    if h not in collected:
                        image_data = ""
                        if has_img:
                            if DEBUG_MODE:
                                print(f"  📷 Found {'FORWARDED' if msg.get('isForwarded') else 'BILL'} WITH IMAGE: {txt[:60]}... (imgCount={msg.get('imgCount',0)})")
                            try:
                                b64 = driver.execute_async_script("""
                                    const callback = arguments[arguments.length - 1];
                                    const searchText = arguments[0];
                                    const isForwarded = arguments[1];
                                    const targetIdx = arguments[2];
                                    
                                    (async () => {
                                        try {
                                            // V76 - Try many selectors
                                            const selectors = [
                                                'div[data-testid="msg-container"]',
                                                'div[data-id]',
                                                'div.message-in',
                                                'div.message-out',
                                                'div[role="row"]'
                                            ];
                                            let nodes = [];
                                            for(let sel of selectors){
                                                let found = document.querySelectorAll(sel);
                                                if(found.length > nodes.length) nodes = found;
                                            }
                                            
                                            let targetNode = null;
                                            if(isForwarded){
                                                for(let n of nodes){
                                                    if(n.innerText.includes('Forwarded') || n.innerHTML.includes('Forwarded')){
                                                        if(n.querySelector('img') || n.querySelector('[data-testid="image-thumb"]')){
                                                            targetNode = n;
                                                            break;
                                                        }
                                                    }
                                                }
                                            }
                                            if(!targetNode && searchText && searchText !== '[IMAGE_ONLY_BILL]' && searchText !== '[FORWARDED_BILL_IMAGE]'){
                                                for(let n of nodes){
                                                    let t = n.innerText || '';
                                                    if(t && t.includes(searchText.substring(0,30))){
                                                        targetNode = n;
                                                        break;
                                                    }
                                                }
                                            }
                                            if(!targetNode && targetIdx < nodes.length){
                                                targetNode = nodes[targetIdx];
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
                                                    if(img.naturalWidth >= 100 && img.naturalHeight >= 100){
                                                        try{
                                                            let canvas = document.createElement('canvas');
                                                            let ctx = canvas.getContext('2d');
                                                            canvas.width = img.naturalWidth;
                                                            canvas.height = img.naturalHeight;
                                                            ctx.drawImage(img, 0, 0);
                                                            let data = canvas.toDataURL('image/jpeg', 0.8);
                                                            if(data && data.length > 5000){
                                                                callback(data);
                                                                return;
                                                            }
                                                        }catch(e){}
                                                    }
                                                }
                                                
                                                // Try blob fetch
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
                                        } catch(e){
                                            callback("");
                                        }
                                    })();
                                """, txt[:100], msg.get('isForwarded', False), msg.get('idx', 0))
                                
                                if b64 and len(b64) > 5000:
                                    image_data = b64
                                    if DEBUG_MODE:
                                        print(f"    Got bill image: {len(image_data)/1024:.1f} KB")
                                else:
                                    if DEBUG_MODE:
                                        print(f"    Failed to get image data")
                            except Exception as e:
                                if DEBUG_MODE:
                                    print(f"    Image capture error: {e}")
                        
                        collected[h] = {"text": txt, "image_data": image_data}
                        found_in_this_scroll += 1
            
            print(f"  Scroll {i}: Found {found_in_this_scroll} new messages (total {len(collected)})")
            
            if DEBUG_MODE and i == 0 and len(collected) == 0:
                # Dump HTML for debugging
                try:
                    html = driver.execute_script("return document.documentElement.outerHTML.substring(0,10000)")
                    print(f"  [DEBUG] HTML preview: {html[:2000]}")
                except: pass
            
            # Scroll up - V76 FIXED: Try many scrollable areas
            try:
                scrolled = driver.execute_script("""
                    const scrollSelectors = [
                        'div[data-testid="conversation-panel-messages"]',
                        'div#main',
                        'div[data-testid="chat"]',
                        'div._1c_mC',
                        'div.copyable-area',
                        'div[data-testid="conversation-panel-wrapper"]',
                        'div[tabindex="0"]'
                    ];
                    for(let sel of scrollSelectors){
                        let el = document.querySelector(sel);
                        if(el){
                            let before = el.scrollTop;
                            el.scrollTop = 0;
                            // Also try scrolling the first child that is scrollable
                            if(el.scrollTop == before){
                                let children = el.querySelectorAll('div');
                                for(let child of children){
                                    if(child.scrollHeight > child.clientHeight){
                                        child.scrollTop = 0;
                                        if(child.scrollTop == 0 || child.scrollTop != before){
                                            return 'Scrolled ' + sel + ' child';
                                        }
                                    }
                                }
                            }
                            return 'Scrolled ' + sel + ' from ' + before + ' to ' + el.scrollTop;
                        }
                    }
                    // Fallback: window scroll
                    window.scrollTo(0,0);
                    return 'Scrolled window';
                """)
                if DEBUG_MODE:
                    print(f"    Scroll result: {scrolled}")
                time.sleep(2.5 if IS_WIN8_FAMILY else 1.5)
            except Exception as e:
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_UP)
                    time.sleep(1)
                except: pass
                if DEBUG_MODE:
                    print(f"    Scroll fallback error: {e}")
            
            # If no new messages for 5 scrolls and we have some, break
            if i > 5 and found_in_this_scroll == 0:
                if len(collected) > 10:
                    print(f"  No new messages for 5 scrolls, stopping (have {len(collected)})")
                    break
            # If still 0 after 10 scrolls, try different approach
            if i == 10 and len(collected) == 0:
                print(f"  Still 0 after 10 scrolls, trying alternative method...")
                try:
                    # Try to click on main chat area to focus
                    driver.execute_script("""
                        let main = document.querySelector('div#main');
                        if(main) main.click();
                    """)
                    time.sleep(1)
                except: pass
                
        except Exception as e:
            print(f"  Scroll error {i}: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)
            continue
    
    print(f"[INFO] Collected {len(collected)} messages with {sum(1 for v in collected.values() if v['image_data'])} REAL bill images")
    return collected

def read_last_n_days(days=30):
    if not SELENIUM_AVAILABLE:
        print("[ERROR] Selenium not installed")
        return [], set()
    print(f"Platform: {platform.platform()} | Scanning {days} days - V76 FIXED SCROLLING")
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
        filtered_by_date = 0
        skipped = 0
        
        for h, item in collected_dict.items():
            txt = item["text"].strip()
            img_data = item.get("image_data", "")
            if not txt and not img_data: continue
            if len(txt) < 3 and not img_data: continue
            
            if img_data and len(img_data) < 5000:
                print(f"  Skipping small image ({len(img_data)/1024:.1f} KB) - likely profile pic: {txt[:40]}")
                if not is_target_message(txt):
                    skipped += 1
                    continue
                img_data = ""
            
            p = parse_message(txt, image_data=img_data, original_text_for_vehicle=txt)
            if p:
                if p.get('date_obj') and p['date_obj'] < cutoff_date and not p.get('has_image'):
                    filtered_by_date += 1
                    continue
                parsed.append(p)
            else:
                skipped += 1
        
        if filtered_by_date > 0:
            print(f"[INFO] Filtered {filtered_by_date} older than {days} days")
        if skipped > 0:
            print(f"[INFO] Skipped {skipped} non-target messages")
        
        parsed.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
        fuel = sum(1 for e in parsed if e.get('type') == 'FUEL')
        maint = sum(1 for e in parsed if e.get('type') == 'MAINTENANCE')
        with_images = sum(1 for e in parsed if e.get('has_image'))
        print(f"[INFO] V77 FIXED DUPLICATES - Fuel: {fuel}, Bills: {maint}, Images: {with_images} | History: {len(history)} already pushed")
        
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
    print(f"JANANI V77 FIXED DUPLICATES - BOTH FUEL + BILL LOG - {DAYS_TO_SCAN} Days")
    print(f"Feature: BOTH Fuel+BILL - No duplicates")
    print(f"Fix: Deterministic keys + fixed push_list")
    if DEBUG_MODE:
        print(f"DEBUG MODE ON - Will show selectors and HTML")
    print("="*60)
    entries, history = read_last_n_days(days=DAYS_TO_SCAN)
    entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
    print(f"\nTotal: {len(entries)}")
    if not entries:
        print("[FAIL] No messages - WhatsApp Web DOM may have changed again")
        print("[HINT] Run with --debug to see selectors, or try:")
        print("  1. Update Chrome to latest")
        print("  2. Clear whatsapp_session_janani folder and login again")
        print("  3. Check if group name is correct: Janani AI Reporting")
    else:
        for e in entries[:15]:
            p = e['payload']
            img_flag = "📷 REAL BILL" if p.get('has_image') else "⛽ FUEL"
            size = f"{len(p.get('image_data',''))/1024:.1f}KB" if p.get('image_data') else "0KB"
            if p['type'] == 'FUEL':
                print(f"  {e['date_folder']} {img_flag} | {p['vehicle']} | FUEL | {p['location']} | {p['total_km']} KM | {size} | -> {p['target_sheet']}")
            else:
                print(f"  {e['date_folder']} {img_flag} | {p['vehicle']} | MAINT | Rs.{p['bill_amount']} | {p['pilot']} | {size} | -> {p['target_sheet']}")
        
        to_push = [e for e in entries if e["unique_key"] not in history]
        to_push_images = [e for e in entries if e['payload'].get('has_image')]
        to_push_fuel = [e for e in entries if e['payload'].get('type') == 'FUEL']
        print(f"\nNew to push: {len(to_push)} (Fuel: {sum(1 for e in to_push if e['payload'].get('type')=='FUEL')} + Bills: {sum(1 for e in to_push if e['payload'].get('has_image'))})")
        print(f"Total with REAL images: {len(to_push_images)} | Total Fuel: {len(to_push_fuel)}")
        
        # V77 FIX: Only push new entries, NOT all if to_push empty (this was causing duplicates)
        push_list = to_push
        
        for idx, e in enumerate(push_list):
            payload = e['payload']
            has_img = "📷 REAL BILL" if payload.get('has_image') else "⛽ FUEL"
            size = len(payload.get('image_data',''))/1024 if payload.get('image_data') else 0
            target = payload.get('target_sheet', 'unknown')
            print(f"[{idx+1}/{len(push_list)}] {has_img} {payload['vehicle']} {payload['date']} {payload['type']} | {size:.1f}KB -> {target}")
            
            try:
                r = requests.post(WEBHOOK_URL, json=payload, timeout=90)
                resp_text = r.text
                if resp_text.strip().startswith("<!DOCTYPE") or "ppConfig" in resp_text:
                    print(f"  -> ❌ APPS SCRIPT ERROR: Deploy Web App as Anyone")
                    continue
                print(f"  -> {resp_text[:500]}")
                try:
                    j = json.loads(resp_text)
                    if j.get("success"):
                        history.add(e["unique_key"])
                        save_history(history)
                        if j.get("imageUrl"):
                            print(f"  -> ✅ Bill uploaded to: {j.get('dateFolder')} -> {j.get('imageUrl')[:60]}...")
                        if j.get("sheet"):
                            print(f"  -> ✅ Fuel/Bill inserted into sheet: {j.get('sheet')}")
                except:
                    if "inserted" in resp_text or "duplicate" in resp_text:
                        history.add(e["unique_key"])
                        save_history(history)
                time.sleep(2)
            except Exception as ex:
                print(f"  Push failed: {ex}")
        
        print("\n[DONE] V77 - BOTH Fuel+BILL - FIXED DUPLICATES!")
        print(f"Fuel -> Month sheets (Jan, Feb...) | Bills -> Bill log: Date | File Name | Vehicle | Drive Link | Original Date | Uploaded At")
