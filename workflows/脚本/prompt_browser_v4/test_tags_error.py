"""测试 /api/tags 端点的详细错误"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("Testing GET /api/tags...")
try:
    response = client.get("/api/tags")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
