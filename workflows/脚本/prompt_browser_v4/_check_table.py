# -*- coding: utf-8 -*-
import sys, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')
path = r'd:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\workflows\文档\提示词收藏.db'
conn = sqlite3.connect(path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [t[0] for t in cur.fetchall()]
print('Tables:', tables)
print('Has fragments:', 'fragments' in tables)
conn.close()
