import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

db_path = r'd:/Entertainment/ComfyUI-aki-v2/workflows/文档/提示词收藏.db'
db = sqlite3.connect(db_path)

# List tables
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Tables: {[t[0] for t in tables]}\n")

for t in tables:
    tname = t[0]
    cols = db.execute(f"PRAGMA table_info({tname})").fetchall()
    print(f"=== {tname} ({len(cols)} columns) ===")
    for c in cols:
        print(f"  {c[1]} ({c[2]})")
    
    rows = db.execute(f"SELECT * FROM {tname} LIMIT 50").fetchall()
    print(f"  Total rows: {len(rows)} shown")
    for i, row in enumerate(rows):
        print(f"\n  --- Row {i+1} ---")
        for ci, col in enumerate(cols):
            val = str(row[ci]) if row[ci] is not None else '(NULL)'
            if len(val) > 200:
                val = val[:200] + '...'
            print(f"    {col[1]}: {val}")
    print()

db.close()
