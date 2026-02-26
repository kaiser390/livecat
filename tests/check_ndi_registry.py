"""Check NDI registry keys and env vars."""
import os
import winreg

# Check NDI environment variables
print("=== NDI Environment Variables ===")
for key in sorted(os.environ):
    if 'NDI' in key.upper() or 'NEWTEK' in key.upper():
        print(f"  {key} = {os.environ[key]}")

print()
print("=== NDI Registry Keys ===")

paths = [
    r"SOFTWARE\NDI",
    r"SOFTWARE\NewTek",
    r"SOFTWARE\Vizrt",
    r"SOFTWARE\Vizrt\NDI",
    r"SOFTWARE\NDI\Runtime",
    r"SOFTWARE\NDI SDK",
    r"SOFTWARE\NewTek\NDI Runtime",
    r"SOFTWARE\NewTek\NDI SDK",
]

for root_name, root_key in [("HKLM", winreg.HKEY_LOCAL_MACHINE), ("HKCU", winreg.HKEY_CURRENT_USER)]:
    for path in paths:
        try:
            key = winreg.OpenKey(root_key, path)
            i = 0
            while True:
                try:
                    name, val, vtype = winreg.EnumValue(key, i)
                    print(f"  {root_name}\\{path}\\{name} = {val}")
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

# Check if NDI runtime DLL is in standard locations
print()
print("=== NDI DLL Locations ===")
locations = [
    r"C:\Program Files\NDI\NDI 6 Runtime",
    r"C:\Program Files\NDI\NDI 5 Runtime",
    r"C:\Program Files\NDI\NDI Runtime",
    r"C:\Program Files (x86)\NDI\NDI 6 Runtime",
    os.path.join(os.environ.get('ProgramData', ''), 'NDI'),
]

for loc in locations:
    if os.path.exists(loc):
        print(f"  EXISTS: {loc}")
        for f in os.listdir(loc):
            print(f"    {f}")
    else:
        print(f"  not found: {loc}")
