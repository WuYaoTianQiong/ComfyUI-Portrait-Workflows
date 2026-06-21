"""API 端点测试脚本"""
import urllib.request
import urllib.error
import json
import sys

BASE_URL = "http://127.0.0.1:8655"


def test_endpoint(name, method, endpoint, data=None):
    """测试一个 API 端点"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n{'=' * 60}")
    print(f"Testing: {method} {endpoint}")
    print(f"{'=' * 60}")
    
    try:
        if method == "GET":
            req = urllib.request.Request(url)
        elif method == "POST":
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8') if data else None,
                headers={'Content-Type': 'application/json'}
            )
        elif method == "PUT":
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8') if data else None,
                headers={'Content-Type': 'application/json'},
                method='PUT'
            )
        elif method == "DELETE":
            req = urllib.request.Request(url, method='DELETE')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.status
            body = response.read().decode('utf-8')
            
            print(f"[PASS] Status: {status}")
            try:
                json_body = json.loads(body)
                print(f"Response: {json.dumps(json_body, indent=2, ensure_ascii=False)[:500]}...")
            except:
                print(f"Response: {body[:500]}...")
            return True, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        print(f"[FAIL] HTTP Error {e.code}: {e.reason}")
        try:
            error_body = e.read().decode('utf-8')
            print(f"Error details: {error_body[:500]}")
        except:
            pass
        return False, None
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False, None


def main():
    """主测试函数"""
    print("\n")
    print("=" * 60)
    print("Prompt Browser V4 API Endpoint Tests")
    print("=" * 60)
    print("\n")
    
    results = []
    
    # 测试 1: GET /api/categories
    r1, categories = test_endpoint("获取分类列表", "GET", "/api/categories")
    results.append(("GET /api/categories", r1))
    
    # 测试 2: POST /api/categories (创建分类)
    new_category = {"name": "测试分类", "color": "#ff0000"}
    r2, created_category = test_endpoint("创建分类", "POST", "/api/categories", new_category)
    results.append(("POST /api/categories", r2))
    
    # 测试 3: GET /api/tags
    r3, tags = test_endpoint("获取标签列表", "GET", "/api/tags")
    results.append(("GET /api/tags", r3))
    
    # 测试 4: POST /api/tags (创建标签)
    new_tag = {"name": "测试标签", "color": "#00ff00"}
    r4, created_tag = test_endpoint("创建标签", "POST", "/api/tags", new_tag)
    results.append(("POST /api/tags", r4))
    
    # 测试 5: GET /api/prompts
    r5, prompts = test_endpoint("获取提示词列表", "GET", "/api/prompts")
    results.append(("GET /api/prompts", r5))
    
    # 清理测试数据
    if r2 and created_category:
        cat_id = created_category.get('id')
        if cat_id:
            test_endpoint("删除测试分类", "DELETE", f"/api/categories/{cat_id}")
    
    if r4 and created_tag:
        tag_id = created_tag.get('id')
        if tag_id:
            test_endpoint("删除测试标签", "DELETE", f"/api/tags/{tag_id}")
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name}: [{status}]")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] All API tests passed!")
    else:
        print("[ERROR] Some API tests failed.")
    print("=" * 60 + "\n")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
