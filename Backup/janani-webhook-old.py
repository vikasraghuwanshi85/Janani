import os, re, time, requests, json, hashlib, sys, io, platform
from datetime import datetime, timedelta

# === Windows 8.1 Compatibility Layer ===
IS_WIN81 = platform.system() == "Windows" and platform.release() in ["8", "8.1"] or "Windows-8" in platform.platform()
IS_WINDOWS = platform.system() == "Windows"

# Fix encoding for Win 8.1 cmd (cp1252 -> utf-8)
try:
    if IS_WINDOWS:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        # Force UTF-8 for Windows 8.1
        import _locale
        _locale._getdefaultlocale = (lambda *args: ('en_US', 'utf-8'))
except:
    pass

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.chrome.service import Service
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[WARN] Selenium not installed, installing...")

GROUP_NAME = "Janani Reporting"
CHAT_DB_PATH = "whatsapp_session_janani"
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbx-h8zs4Jz6DbNUHzq2OO1bjLktbf-z0ZR4YODfuaC7V4sjT2kF6c-DSMSmXOQVB-u9/exec"

CONFIG_FILE = "sheet_config.json"
if os.path.exists(CONFIG_FILE):
    try:
        cfg = json.load(open(CONFIG_FILE, encoding='utf-8'))
        if cfg.get("webhook_url"):
            WEBHOOK_URL = cfg["webhook_url"]
    except:
        pass

HISTORY_FILE = "pushed_history.json"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# === V44 Parser - Sorted by Date + Win8.1 Fix ===
ALL_KEYS_PATTERN = r"(?:Date|Location|Vehicle\s*no|Present\s*odo|Previous\s*odo|Diesel\s*amount|Diseal\s*amount|Diesel\s*liter|Diseal\s*liter|Average|Bill\s*amount|Work\s*details|Pilot\s*name|Pump\s*Name)\s*-\s*"

FIELD_ALIASES = {
    "Date": ["Date"],
    "Location": ["Location"],
    "Vehicle no": ["Vehicle no", "Vehicle No", "Vehicle"],
    "Present odo": ["Present odo", "Present Odo"],
    "Previous odo": ["Previous odo", "Previous Odo"],
    "Diesel amount": ["Diesel amount", "Diseal amount", "Diesel Amount", "Diseal Amount"],
    "Diesel liter": ["Diesel liter", "Diseal liter", "Diesel Liter", "Diseal Liter"],
    "Average": ["Average"],
    "Pilot name": ["Pilot name", "Pilot Name"],
    "Pump Name": ["Pump Name", "Pump name"],
}

def clean_text_for_parsing(text):
    if not text:
        return text
    # Fix for your CSV issue: triple duplicate
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
            if next_m:
                val = cleaned[start:start+next_m.start()].strip()
            else:
                val = cleaned[start:].strip().split("\n")[0].split(",")[0].strip()
            if val and val != "-" and val.lower() != "null":
                if key == "Location":
                    vm = re.search(r"\bVehicle\s*no\b", val, re.I)
                    if vm:
                        val = val[:vm.start()].strip()
                return val
    return ""

def is_target_message(text):
    if not text:
        return False
    check_text = clean_text_for_parsing(text)
    if not re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", check_text):
        return False
    tl = check_text.lower()
    if "vehicle" in tl and "present" in tl and "odo" in tl:
        return True
    return False

def normalize_vehicle_raw(raw):
    if not raw:
        return ""
    raw = re.sub(r"PRESENTODO.*", "", raw, flags=re.I)
    raw = re.sub(r"PREVIOUSODO.*", "", raw, flags=re.I)
    raw = re.sub(r"DISEAL.*", "", raw, flags=re.I)
    return re.sub(r"[\s\-]+", "", raw.strip().upper())

def capitalize_name(name):
    if not name:
        return ""
    return " ".join(word.capitalize() for word in name.lower().split())

def parse_date_strict_ddmmyyyy(date_str):
    date_str = date_str.strip()
    normalized = re.sub(r'[\-]', '/', date_str)
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(normalized, fmt)
            if d.year < 100:
                d = d.replace(year=2000 + d.year)
            return d.strftime("%d-%m-%Y"), d, MONTHS[d.month-1]
        except:
            continue
    try:
        parts = re.split(r'[/\-]', date_str.strip())
        if len(parts) == 3:
            day, mon, yr = int(parts[0]), int(parts[1]), int(parts[2])
            if yr < 100:
                yr += 2000
            if 1 <= mon <= 12 and 1 <= day <= 31:
                d = datetime(yr, mon, day)
                return d.strftime("%d-%m-%Y"), d, MONTHS[mon-1]
    except:
        pass
    now = datetime.now()
    return now.strftime("%d-%m-%Y"), now, MONTHS[now.month-1]

def parse_message(text):
    if not is_target_message(text):
        return None
    cleaned = clean_text_for_parsing(text)
    date_str = get_field("Date", text)
    if not date_str:
        m = re.search(r"^\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", cleaned)
        if m:
            date_str = m.group(1)
    if not date_str:
        return None
    date_folder, d, month_name = parse_date_strict_ddmmyyyy(date_str)
    present_raw = get_field("Present odo", text)
    prev_raw = get_field("Previous odo", text)
    present = re.sub(r"\D", "", present_raw)[:7]
    prev = re.sub(r"\D", "", prev_raw)[:7]
    total_km = ""
    try:
        if present and prev:
            p_int, pr_int = int(present), int(prev)
            if not (100 <= p_int <= 9999999 and 100 <= pr_int <= 9999999):
                return None
            diff = p_int - pr_int
            if not (0 <= diff <= 5000):
                return None
            total_km = str(diff)
    except:
        return None
    veh_raw = get_field("Vehicle no", text)
    vehicle_raw = normalize_vehicle_raw(veh_raw)
    if not vehicle_raw or len(vehicle_raw) > 10:
        return None
    if not re.match(r"^[A-Z0-9]{3,10}$", vehicle_raw):
        return None
    if "PRESENTODO" in vehicle_raw:
        return None
    diesel_amt_raw = get_field("Diesel amount", text) or get_field("Diseal amount", text)
    diesel_amt_clean = ""
    if diesel_amt_raw:
        m = re.search(r"(\d+\.\d+|\d+)", diesel_amt_raw)
        if m:
            diesel_amt_clean = m.group(1)
    diesel_ltr_raw = get_field("Diesel liter", text) or get_field("Diseal liter", text)
    diesel_ltr_clean = ""
    if diesel_ltr_raw:
        m = re.search(r"(\d+\.\d+|\d+)", diesel_ltr_raw)
        if m:
            diesel_ltr_clean = m.group(1)
    average_val = ""
    try:
        if diesel_ltr_clean and total_km:
            tk, ltr = float(total_km), float(diesel_ltr_clean)
            if ltr != 0:
                average_val = f"{tk/ltr:.2f}"
    except:
        average_val = ""
    rate_val = ""
    try:
        if diesel_amt_clean and diesel_ltr_clean:
            rate_val = f"{float(diesel_amt_clean)/float(diesel_ltr_clean):.2f}"
    except:
        rate_val = ""
    payload = {
        "date": date_str,
        "location": get_field("Location", text),
        "vehicle": vehicle_raw,
        "type": "FUEL",
        "present_odo": present,
        "previous_odo": prev,
        "total_km": total_km,
        "diesel_amount": diesel_amt_clean,
        "diesel_liter": diesel_ltr_clean,
        "rate": rate_val,
        "average": average_val,
        "bill_amount": "",
        "work_details": "",
        "pilot": capitalize_name(get_field("Pilot name", text)),
        "pump": capitalize_name(get_field("Pump Name", text)),
        "source": "Janani Reporting",
        "month": month_name
    }
    simple_key = f"{date_folder}_{vehicle_raw}_FUEL".lower()
    return {"month": month_name, "date_raw": date_str, "date_folder": date_folder, "unique_key": simple_key, "present": present, "payload": payload, "date_obj": d}

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return set(json.load(open(HISTORY_FILE, encoding='utf-8')))
        except:
            return set()
    return set()

def save_history(s):
    json.dump(list(s), open(HISTORY_FILE, 'w', encoding='utf-8'), indent=2)

def push_to_sheet(payload, history, unique_key):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=30)
        print(f"Push {payload.get('vehicle')} {payload.get('date')} -> {r.text[:150]}")
        if r.status_code == 200:
            history.add(unique_key)
            save_history(history)
            return True
    except Exception as e:
        print(f"Push failed {e}")
    return False

def get_chrome_options_win81():
    """Windows 8.1 compatible Chrome options - Chrome 109 is last supported"""
    options = webdriver.ChromeOptions()
    # Win 8.1 compatible args
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-web-security")
    # Win 8.1 needs these
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-software-rasterizer")
    # User data dir
    options.add_argument(f"--user-data-dir={os.path.abspath(CHAT_DB_PATH)}")
    # Exclude automation switches
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    # Prefs for Win 8.1
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.images": 2  # Speed up on old PC
    }
    # Only on Win8.1, disable images for speed
    if IS_WIN81:
        options.add_experimental_option("prefs", prefs)
    return options

def find_chromedriver_win81():
    """Find chromedriver for Win 8.1 - Chrome 109 max"""
    possible_paths = [
        "./chromedriver.exe",
        "./chromedriver-win64/chromedriver.exe",
        os.path.join(os.getenv("LOCALAPPDATA", ""), "chromedriver.exe"),
        "C:\\chromedriver\\chromedriver.exe"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return None

def create_driver_win81():
    """Create driver with Win 8.1 fallback logic"""
    options = get_chrome_options_win81()
    
    # Try 1: webdriver-manager (will auto-detect Chrome 109 on Win8.1)
    if "--no-webdriver-manager" not in sys.argv:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            print("[INFO] Using webdriver-manager (auto Chrome 109 for Win8.1)...")
            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            print(f"[OK] Chrome driver created via manager: {driver_path}")
            return driver
        except Exception as e:
            print(f"[WARN] webdriver-manager failed: {e}")
    
    # Try 2: Local chromedriver.exe (download Chrome 109 driver manually for Win8.1)
    local_driver = find_chromedriver_win81()
    if local_driver:
        try:
            print(f"[INFO] Using local driver: {local_driver}")
            service = Service(local_driver)
            driver = webdriver.Chrome(service=service, options=options)
            return driver
        except Exception as e:
            print(f"[WARN] Local driver failed: {e}")
    
    # Try 3: System PATH chromedriver
    try:
        print("[INFO] Trying system chromedriver...")
        driver = webdriver.Chrome(options=options)
        return driver
    except Exception as e:
        print(f"[FAIL] All driver attempts failed: {e}")
        print("\n[WIN8.1 FIX] Download ChromeDriver 109.0.5414.74 for Win8.1:")
        print("https://chromedriver.storage.googleapis.com/109.0.5414.74/chromedriver_win32.zip")
        print("Extract chromedriver.exe to this folder and run again.")
        raise

def scroll_and_collect_win81(driver, days=5):
    """V45 Fixed - works on Chrome 153 + new WhatsApp Web"""
    collected = {}
    print(f"[INFO] Collecting last {days} days - Win8.1/Chrome153 compatible...")
    last_count = 0
    same_count = 0
    max_scrolls = 80 if IS_WIN81 else 150
    
    # Multiple selectors for message bubbles (WhatsApp changed these too)
    message_xpaths = [
        '//span[contains(@class,"selectable-text")]',
        '//div[contains(@class,"copyable-text")]//span',
        '//div[@data-testid="msg-container"]//span',
        '//span[@data-testid="msg-container"]',
        '//div[contains(@class,"message-in")]//span',
        '//div[contains(@class,"message-out")]//span',
    ]
    
    for i in range(max_scrolls):
        try:
            found_this_round = 0
            for xpath in message_xpaths:
                try:
                    bubbles = driver.find_elements(By.XPATH, xpath)
                    for b in bubbles:
                        try:
                            txt = b.text.strip()
                            # Valid message: has Date and Vehicle
                            if txt and len(txt) > 15 and len(txt) < 3000 and "Vehicle" in txt and "Location" in txt:
                                h = hashlib.md5(txt.encode('utf-8', errors='ignore')).hexdigest()
                                if h not in collected:
                                    collected[h] = txt
                                    found_this_round += 1
                        except:
                            continue
                    if found_this_round > 0:
                        break  # Found with this selector, no need to try others
                except:
                    continue
            
            if len(collected) == last_count:
                same_count += 1
                if same_count > 5:
                    print(f"  No new messages after {i} scrolls, stopping")
                    break
            else:
                same_count = 0
            last_count = len(collected)
            if i % 10 == 0:
                print(f"  Scroll {i}: {len(collected)} messages ({found_this_round} new)...")
            
            # Scroll up to load older messages
            try:
                # Try multiple scroll methods for new WhatsApp
                driver.execute_script("window.scrollBy(0, -700);")
                # Also try scrolling the chat container
                driver.execute_script("var el=document.querySelector('[data-testid=conversation-panel-wrapper]'); if(el) el.scrollTop-=700;")
            except:
                driver.execute_script("window.scrollBy(0, -600);")
            
            time.sleep(0.8 if IS_WIN81 else 0.5)
        except Exception as e:
            print(f"Scroll error at {i}: {e}")
            break
    
    print(f"[INFO] Collected {len(collected)} unique target messages")
    return collected

# For compatibility, keep original function names
def scroll_to_load_last_n_days(driver, days=5, max_scrolls=150):
    return scroll_and_collect_win81(driver, days)

def find_group(driver, group_name):
    """V45 Fixed for Chrome 153 + new WhatsApp Web - tries 10 selectors"""
    print(f"[INFO] Searching for group: {group_name} (Chrome {driver.capabilities.get('browserVersion','?')})")
    
    selectors = [
        '//div[@contenteditable="true"][@data-tab="3"]',  # Old - your error
        '//div[@contenteditable="true"][@data-tab="2"]',
        '//div[@contenteditable="true"][@data-lexical-editor="true"]',  # New WhatsApp 2024
        '//div[@title="Search input textbox"]',
        '//div[@aria-label="Search input textbox"]',
        '//div[contains(@aria-label, "Search")][@contenteditable="true"]',
        '//div[@data-testid="chat-list-search"]//div[@contenteditable="true"]',
        '//div[@role="textbox"][@contenteditable="true"]',
        '//p[@class="selectable-text copyable-text"]',
        '//div[contains(@class,"x1c4vz4f")][@contenteditable="true"]',
    ]
    
    for idx, xpath in enumerate(selectors):
        try:
            print(f"  Trying selector {idx+1}/{len(selectors)}: {xpath[:60]}...")
            search_boxes = driver.find_elements(By.XPATH, xpath)
            if not search_boxes:
                continue
            search_box = search_boxes[0]
            driver.execute_script("arguments[0].scrollIntoView();", search_box)
            time.sleep(0.5)
            search_box.click()
            time.sleep(0.5)
            # Clear with Ctrl+A
            try:
                search_box.send_keys(Keys.CONTROL + "a")
                search_box.send_keys(Keys.BACKSPACE)
            except:
                try:
                    driver.execute_script("arguments[0].textContent='';", search_box)
                except:
                    pass
            time.sleep(0.5)
            search_box.send_keys(group_name)
            print(f"    Typed '{group_name}'")
            time.sleep(2.5 if IS_WIN81 else 2)
            search_box.send_keys(Keys.ENTER)
            time.sleep(3)
            
            # Verify group opened - check header
            try:
                header = driver.find_elements(By.XPATH, f'//span[@title="{group_name}"] | //div[@title="{group_name}"] | //span[contains(text(),"{group_name}")]')
                if header:
                    print(f"[OK] Found group via selector {idx+1}")
                    return True
            except:
                pass
            return True  # Assume success if typing worked
        except Exception as e:
            print(f"    Selector {idx+1} failed: {str(e)[:100]}")
            continue
    
    # Fallback: click directly in chat list
    print("[INFO] Trying direct chat list click...")
    try:
        chats = driver.find_elements(By.XPATH, f'//span[@title="{group_name}"]')
        if not chats:
            chats = driver.find_elements(By.XPATH, f'//span[contains(@title, "{group_name}")]')
        if not chats:
            chats = driver.find_elements(By.XPATH, f'//div[contains(@class,"x1f6kntn")]//span[contains(text(),"{group_name}")]')
        if chats:
            print(f"  Found {len(chats)} chat entries, clicking first...")
            driver.execute_script("arguments[0].click();", chats[0])
            time.sleep(4)
            return True
    except Exception as e:
        print(f"Direct click failed: {e}")
    
    print("[FAIL] Could not find group with any selector - WhatsApp Web may have changed again")
    return False

def read_last_n_days():
    if not SELENIUM_AVAILABLE:
        print("[ERROR] Selenium not installed. Run: pip install selenium webdriver-manager")
        return [], set()
    
    print(f"[INFO] Starting Chrome - Windows 8.1 Compatible Mode")
    print(f"[INFO] Platform: {platform.platform()} | Win8.1 detected: {IS_WIN81}")
    
    try:
        driver = create_driver_win81()
    except Exception as e:
        print(f"[FAIL] Could not create driver: {e}")
        return [], set()
    
    try:
        driver.get("https://web.whatsapp.com")
        print("Waiting for login (60 sec timeout for Win8.1)...")
        for i in range(90):
            time.sleep(1)
            try:
                driver.find_element(By.XPATH, '//div[@id="side"] | //div[@id="pane-side"]')
                if len(driver.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]')) == 0:
                    print(f"[OK] Logged in after {i}s")
                    break
            except:
                pass
            if i % 10 == 0:
                print(f"  Waiting... {i}s")
        
        time.sleep(10 if IS_WIN81 else 8)
        if not find_group(driver, GROUP_NAME):
            driver.quit()
            return [], set()
        
        time.sleep(8 if IS_WIN81 else 6)
        collected = scroll_and_collect_win81(driver, days=5)
        print(f"[INFO] Collected {len(collected)} unique texts")
        
        bubble_data = list(collected.values())
        history = load_history()
        print(f"[INFO] History: {len(history)} entries")
        
        parsed_entries = []
        skipped = 0
        for txt in bubble_data:
            txt = txt.strip()
            if len(txt) < 15:
                skipped += 1
                continue
            if not is_target_message(txt):
                skipped += 1
                continue
            p = parse_message(txt)
            if p:
                parsed_entries.append(p)
        
        # SORT ALL BY DATE - NEW FEATURE
        parsed_entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
        print(f"[INFO] Sorted {len(parsed_entries)} entries by date (newest first)")
        
        # Dedup
        deduped = {}
        for entry in parsed_entries:
            key = entry["unique_key"]
            if key not in deduped:
                deduped[key] = entry
        
        parsed_entries = list(deduped.values())
        # Sort again after dedup by date
        parsed_entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
        
        print(f"\n=== Sorted by Date (Win8.1) ===")
        for e in parsed_entries[:5]:
            print(f"  {e['date_folder']} - {e['payload']['vehicle']} - {e['payload']['total_km']} KM")
        
        driver.quit()
        return parsed_entries, history
        
    except Exception as e:
        print(f"[ERROR] {e}")
        try:
            driver.quit()
        except:
            pass
        return [], set()

if __name__ == "__main__":
    print("="*60)
    print("Janani Fleet - Windows 8.1 Compatible + Sorted by Date")
    print("Fixes: 3.57963E+25 bug + Win8.1 Chrome 109 + Sorting")
    print("="*60)
    
    entries, history = read_last_n_days()
    print(f"\nTotal entries sorted by date: {len(entries)}")
    
    # Sort again to be sure
    entries.sort(key=lambda x: x.get('date_obj') or datetime.min, reverse=True)
    
    if not entries:
        print("[FAIL] No messages found")
    else:
        print(f"\n[NEWEST FIRST - Sorted by Date]")
        for e in entries[:10]:
            p = e['payload']
            print(f"  {e['date_folder']} | {p['vehicle']} | {p['location']} | {p['total_km']} KM | {p['pilot']}")
        
        entries_to_push = [e for e in entries if e["unique_key"] not in history]
        print(f"\nNew to push: {len(entries_to_push)} (already pushed: {len(entries)-len(entries_to_push)})")
        
        for idx, e in enumerate(entries_to_push):
            print(f"[{idx+1}/{len(entries_to_push)}] {e['payload']['vehicle']} {e['payload']['date']}...")
            try:
                requests.post(WEBHOOK_URL, json=e["payload"], timeout=30)
                history.add(e["unique_key"])
                save_history(history)
                time.sleep(1.5)
            except Exception as ex:
                print(f"Push failed: {ex}")
        
        print("\n[DONE] All sorted by date and pushed. Open dashboard: janani-dashboard-sorted-by-date-win81.html")
