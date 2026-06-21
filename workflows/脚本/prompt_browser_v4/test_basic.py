"""基础功能测试脚本 - 验证模型、路由等基本功能"""
import sys
import traceback

# 设置标准输出编码为 UTF-8（兼容 Windows）
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_imports():
    """测试所有模块是否能正常导入"""
    print("=" * 60)
    print("Test 1: Module Import")
    print("=" * 60)
    
    try:
        from config import settings
        print("[PASS] config imported successfully")
        print(f"  Host: {settings.host}:{settings.port}")
        print(f"  Database: {settings.db_path}")
    except Exception as e:
        print(f"[FAIL] config import failed: {e}")
        traceback.print_exc()
        return False
    
    try:
        from models import db, Prompt, Category, Tag, PromptCategory, PromptTag
        print("[PASS] models imported successfully")
        print(f"  Available models: Prompt, Category, Tag, PromptCategory, PromptTag")
    except Exception as e:
        print(f"[FAIL] models import failed: {e}")
        traceback.print_exc()
        return False
    
    try:
        from routers import prompts, categories, tags
        print("[PASS] routers imported successfully")
        print(f"  Available routers: prompts, categories, tags")
    except Exception as e:
        print(f"[FAIL] routers import failed: {e}")
        traceback.print_exc()
        return False
    
    return True


def test_db_init():
    """测试数据库初始化"""
    print("\n" + "=" * 60)
    print("Test 2: Database Initialization")
    print("=" * 60)
    
    try:
        from models import init_db, db
        
        print("Initializing database...")
        init_db()
        print("[PASS] Database initialized successfully")
        
        # 检查表是否创建
        db.connect()
        tables = db.get_tables()
        db.close()
        
        expected_tables = ['prompts', 'categories', 'tags', 'prompt_categories', 'prompt_tags']
        print(f"\nTables in database: {tables}")
        
        missing = [t for t in expected_tables if t not in tables]
        if missing:
            print(f"[FAIL] Missing tables: {missing}")
            return False
        else:
            print(f"[PASS] All expected tables created")
        
        return True
    except Exception as e:
        print(f"[FAIL] Database initialization failed: {e}")
        traceback.print_exc()
        return False


def test_crud_operations():
    """测试基本的 CRUD 操作"""
    print("\n" + "=" * 60)
    print("Test 3: Basic CRUD Operations")
    print("=" * 60)
    
    try:
        from models import Category, Tag, Prompt, db
        
        db.connect()
        
        # 测试 Category 创建
        print("\n3.1 Testing Category creation...")
        cat = Category.create(name="Test Category", color="#ff0000")
        print(f"[PASS] Category created: id={cat.id}, name={cat.name}")
        
        # 测试 Tag 创建
        print("\n3.2 Testing Tag creation...")
        tag = Tag.create(name="Test Tag", color="#00ff00")
        print(f"[PASS] Tag created: id={tag.id}, name={tag.name}")
        
        # 测试 Prompt 创建
        print("\n3.3 Testing Prompt creation...")
        prompt = Prompt.create(
            name="Test Prompt",
            prompt="test prompt",
            tags="old_tag1,old_tag2"
        )
        print(f"[PASS] Prompt created: id={prompt.id}, name={prompt.name}")
        
        # 测试关联
        print("\n3.4 Testing Prompt-Category association...")
        from models import PromptCategory, PromptTag
        
        pc = PromptCategory.create(prompt=prompt, category=cat)
        print(f"[PASS] Prompt-Category association created")
        
        pt = PromptTag.create(prompt=prompt, tag=tag)
        print(f"[PASS] Prompt-Tag association created")
        
        # 清理测试数据
        print("\n3.5 Cleaning up test data...")
        pt.delete_instance()
        pc.delete_instance()
        prompt.delete_instance()
        tag.delete_instance()
        cat.delete_instance()
        print(f"[PASS] Test data cleaned up")
        
        db.close()
        return True
    except Exception as e:
        print(f"[FAIL] CRUD operations failed: {e}")
        traceback.print_exc()
        try:
            db.close()
        except:
            pass
        return False


def main():
    """主测试函数"""
    print("\n")
    print("=" * 60)
    print("Prompt Browser V4 Basic Functionality Test")
    print("=" * 60)
    print("\n")
    
    results = []
    
    # 测试 1: 模块导入
    r1 = test_imports()
    results.append(("Module Import", r1))
    
    if not r1:
        print("\n[FAIL] Module import failed, aborting subsequent tests")
        return
    
    # 测试 2: 数据库初始化
    r2 = test_db_init()
    results.append(("Database Initialization", r2))
    
    if not r2:
        print("\n[FAIL] Database initialization failed, aborting subsequent tests")
        return
    
    # 测试 3: CRUD 操作
    r3 = test_crud_operations()
    results.append(("CRUD Operations", r3))
    
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
        print("[SUCCESS] All tests passed! Basic functionality is working.")
    else:
        print("[ERROR] Some tests failed, please check the error messages.")
    print("=" * 60 + "\n")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
