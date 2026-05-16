import sys

with open('c:/Users/logan/Downloads/fraudguard/app/static/index.html', 'rb') as f:
    content = f.read()

script_idx = content.find(b'<script>')
if script_idx == -1: sys.exit(0)
script_part = content[script_idx:].decode('utf-8', errors='replace')

in_str = None
escape = False
for i, c in enumerate(script_part):
    if in_str:
        if escape:
            escape = False
        elif c == '\\':
            escape = True
        elif c == in_str:
            in_str = None
        else:
            if ord(c) > 0x7F:
                print(f'Found non-ASCII in string literal at index {i}: {repr(c)} - snippet: {repr(script_part[i-20:i+20])}')
    else:
        if c in ("'", '"', '`'):
            in_str = c
