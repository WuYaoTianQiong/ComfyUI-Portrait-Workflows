"""数据迁移脚本：将旧的 tags 字段迁移到新的 Tag 表"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Prompt, Tag, PromptTag, db
from playhouse.migrate import migrate, SchemaMigrator


def migrate_tags():
    """迁移旧的 tags 字段到新的 Tag 系统"""
    print("=" * 60)
    print("数据迁移：tags 字段 -> Tag 表")
    print("=" * 60)
    print()
    
    # 1. 获取所有有 tags 的提示词
    prompts = Prompt.select().where(
        (Prompt.tags.is_null(False)) & (Prompt.tags != "")
    )
    
    total = prompts.count()
    print(f"找到 {total} 个有标签的提示词")
    print()
    
    if total == 0:
        print("没有需要迁移的数据")
        return
    
    migrated_count = 0
    tag_count = 0
    
    for prompt in prompts:
        if not prompt.tags:
            continue
        
        # 2. 分割 tags 字符串
        tag_names = [t.strip() for t in prompt.tags.split(",") if t.strip()]
        
        for tag_name in tag_names:
            # 3. 查找或创建标签
            tag = Tag.get_or_none(Tag.name == tag_name)
            if tag is None:
                tag = Tag.create(name=tag_name, color="#8b5cf6")
                tag_count += 1
                print(f"  [创建标签] {tag_name}")
            
            # 4. 创建关联（如果不存在）
            existing = PromptTag.get_or_none(
                (PromptTag.prompt == prompt) & (PromptTag.tag == tag)
            )
            if existing is None:
                PromptTag.create(prompt=prompt, tag=tag)
                migrated_count += 1
        
        print(f"  [提示词 #{prompt.id}] {prompt.name[:30]}... -> {len(tag_names)} 个标签")
    
    print()
    print("=" * 60)
    print(f"迁移完成！")
    print(f"  - 创建了 {tag_count} 个新标签")
    print(f"  - 创建了 {migrated_count} 个提示词-标签关联")
    print("=" * 60)
    print()
    print("提示：迁移完成后，您可以选择保留或删除 Prompt 表的 tags 字段。")


def main():
    """主函数"""
    print()
    print("开始迁移数据...")
    print()
    migrate_tags()
    
    # 验证迁移结果
    print()
    print("验证迁移结果...")
    tags = Tag.select().count()
    relations = PromptTag.select().count()
    print(f"  - Tag 表中有 {tags} 个标签")
    print(f"  - PromptTag 表中有 {relations} 个关联")
    print()
    print("迁移完成！")


if __name__ == "__main__":
    main()
