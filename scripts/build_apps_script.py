"""Build the single Google Apps Script deployment from reviewed source modules."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
sources = [root / 'apps_script' / name for name in
           ('entrypoints.gs', 'fuel_header_fix.gs', 'bill_folder_fix.gs')]
parts = [path.read_text(encoding='utf-8') for path in sources]
contents = '\n\n'.join(parts)
names = re.findall(r'^function\s+(\w+)\s*\(', contents, re.MULTILINE)
if len(names) != len(set(names)):
    raise RuntimeError('Duplicate function definitions in Apps Script bundle')
banner = '// GENERATED COMPLETE SCRIPT: paste this file alone into Apps Script.\n'
banner += '// Sources: entrypoints.gs, fuel_header_fix.gs, bill_folder_fix.gs.\n\n'
banner += '// This bundle needs no separate helper files, despite component comments below.\n\n'
(root / 'apps_script' / 'Janani.gs').write_text(banner + contents, encoding='utf-8')
print('Generated apps_script/Janani.gs')
