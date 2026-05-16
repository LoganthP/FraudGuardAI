import sys

path = 'c:/Users/logan/Downloads/fraudguard/app/static/index.html'
with open(path, 'rb') as f:
    content = f.read()

script_idx = content.find(b'<script>')
if script_idx == -1: sys.exit(0)

html_part = content[:script_idx]
script_part = content[script_idx:]

# 1. Apply the specific string replacements
# The buckets:
script_part = script_part.replace(b"'$0\xc3\xa2\xe2\x82\xac\xe2\x80\x9c100'", b"'$0-100'")
script_part = script_part.replace(b"'$100\xc3\xa2\xe2\x82\xac\xe2\x80\x9c500'", b"'$100-500'")
script_part = script_part.replace(b"'$500\xc3\xa2\xe2\x82\xac\xe2\x80\x9c1K'", b"'$500-1K'")
script_part = script_part.replace(b"'$1K\xc3\xa2\xe2\x82\xac\xe2\x80\x9c5K'", b"'$1K-5K'")

script_part = script_part.replace(b"'$0\xe2\x80\x93100'", b"'$0-100'")
script_part = script_part.replace(b"'$100\xe2\x80\x93500'", b"'$100-500'")
script_part = script_part.replace(b"'$500\xe2\x80\x931K'", b"'$500-1K'")
script_part = script_part.replace(b"'$1K\xe2\x80\x935K'", b"'$1K-5K'")

script_part = script_part.replace(b"'$0\xe2\x80\x94100'", b"'$0-100'")
script_part = script_part.replace(b"'$100\xe2\x80\x94500'", b"'$100-500'")
script_part = script_part.replace(b"'$500\xe2\x80\x941K'", b"'$500-1K'")
script_part = script_part.replace(b"'$1K\xe2\x80\x945K'", b"'$1K-5K'")

# The dropZone textContent (middle dot -> \u00B7)
script_part = script_part.replace(b"' KB  \xc3\x82\xc2\xb7  '", b"' KB  \\u00B7  '")
script_part = script_part.replace(b"' KB  \xc2\xb7  '", b"' KB  \\u00B7  '")

# The AI summary textContent (em dash -> \u2014)
script_part = script_part.replace(b"[RISK SUMMARY UNAVAILABLE \xe2\x80\x94 MODEL DID NOT RETURN ASSESSMENT]", b"[RISK SUMMARY UNAVAILABLE \\u2014 MODEL DID NOT RETURN ASSESSMENT]")
# Just in case of mojibake:
script_part = script_part.replace(b"[RISK SUMMARY UNAVAILABLE \xc3\xa2\xe2\x80\x9d\xe2\x82\xac MODEL DID NOT RETURN ASSESSMENT]", b"[RISK SUMMARY UNAVAILABLE \\u2014 MODEL DID NOT RETURN ASSESSMENT]")

# Decode to string to process the rest of the JS string literals
text = script_part.decode('utf-8', errors='replace')

out_chars = []
in_str = None
escape = False
for c in text:
    if in_str:
        if escape:
            escape = False
            out_chars.append(c)
        elif c == '\\':
            escape = True
            out_chars.append(c)
        elif c == in_str:
            in_str = None
            out_chars.append(c)
        else:
            if ord(c) > 0x7F:
                out_chars.append(f'\\u{ord(c):04X}')
            else:
                out_chars.append(c)
    else:
        if c in ("'", '"', '`'):
            in_str = c
        out_chars.append(c)

processed_script = ''.join(out_chars).encode('utf-8')

with open(path, 'wb') as f:
    f.write(html_part + processed_script)

print("Unicode replacement successful!")
