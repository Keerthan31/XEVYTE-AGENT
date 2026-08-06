import re
import glob

# Replace multi-line docstrings with single-line docstrings
def replacer(match):
    inner = match.group(1).replace('\n', ' ')
    inner = re.sub(' +', ' ', inner).strip()
    return f'"""{inner}"""'

for py_file in glob.glob('/Users/koushikviswandha/Desktop/XEVYTE-AGENT-main 2/backend/*.py'):
    with open(py_file, 'r') as f:
        content = f.read()
    new_content = re.sub(r'"""(.*?)"""', replacer, content, flags=re.DOTALL)
    with open(py_file, 'w') as f:
        f.write(new_content)
print("Fixed docstrings in all python files")
