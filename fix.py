with open('backend/main.py', 'rb') as f:
    b = f.read()
start = b.find(b'"reason": f"')
if start != -1:
    end = b.find(b',\r\n', start)
    if end == -1: end = b.find(b',\n', start)
    correct = '"reason": f"基于公开网页信号，{normalized_name} 与 {normalized_domain} 存在竞品相关性。"'.encode('utf-8')
    b = b[:start] + correct + b[end:]
    with open('backend/main.py', 'wb') as f:
        f.write(b)
    print("Fixed main.py")
else:
    print("Pattern not found")
