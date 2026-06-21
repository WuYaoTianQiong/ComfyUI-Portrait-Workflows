"""Peewee ORM 模型 —— 映射 v3 已有的 SQLite 表结构"""
from peewee import (
    SqliteDatabase, Model, AutoField, TextField, IntegerField,
    FloatField, DateTimeField, BooleanField, SQL, ForeignKeyField,
    DeferredForeignKey
)
from config import settings

db = SqliteDatabase(
    str(settings.db_path),
    pragmas={"journal_mode": "wal", "foreign_keys": 1},
)
print(f"[models] Using database: {settings.db_path} (exists: {settings.db_path.exists()})")


class BaseModel(Model):
    class Meta:
        database = db


# ======== Phase 2: 分类和标签系统 ========
class Category(BaseModel):
    """分类表（支持多级分类）"""
    id = AutoField()
    name = TextField()  # 分类名称
    parent_id = IntegerField(null=True)  # 父分类 ID（NULL 表示顶级分类）
    sort_order = IntegerField(default=0)  # 排序顺序
    color = TextField(default="#6366f1")  # 分类颜色标识
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "categories"


class Tag(BaseModel):
    """标签表（独立管理）"""
    id = AutoField()
    name = TextField(unique=True)  # 标签名称（唯一）
    color = TextField(default="#8b5cf6")  # 标签颜色
    usage_count = IntegerField(default=0)  # 使用次数
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "tags"



# =============================================


class Prompt(BaseModel):
    id = AutoField()
    name = TextField(default="")
    prompt = TextField(default="")
    negative_prompt = TextField(default="")
    steps = IntegerField(null=True)
    cfg_scale = FloatField(null=True)
    sampler = TextField(default="")
    seed = IntegerField(null=True)
    model = TextField(default="")
    width = IntegerField(null=True)
    height = IntegerField(null=True)
    tags = TextField(default="")
    note = TextField(default="")
    # ======== Phase 1 新增字段 ========
    is_favorite = BooleanField(default=False)      # 收藏
    is_pinned = BooleanField(default=False)        # 置顶
    usage_count = IntegerField(default=0)          # 使用次数
    last_used_at = DateTimeField(null=True)         # 最后使用时间
    rating = IntegerField(null=True)               # 评级 1-5
    # ========================================
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    updated_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "prompts"


class GenJob(BaseModel):
    id = AutoField()
    job_type = TextField()
    status = TextField()
    title = TextField(null=True)
    total = IntegerField(default=0)
    done_count = IntegerField(default=0)
    error_count = IntegerField(default=0)
    items = TextField(null=True)  # JSON string
    workflow_path = TextField(null=True)
    orientation = TextField(null=True)
    quality = TextField(null=True)
    extra = TextField(null=True)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    updated_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "gen_jobs"


class GenHistory(BaseModel):
    id = AutoField()
    job_id = IntegerField(null=True)
    prompt_id = IntegerField(null=True)
    comfyui_prompt_id = TextField(null=True)
    filename = TextField(null=True)
    subfolder = TextField(null=True)
    img_type = TextField(null=True)
    view_url = TextField(null=True)
    preview = TextField(null=True)
    prompt_params = TextField(null=True)  # JSON: 出图参数（steps, cfg, sampler, seed, model, width, height 等）
    favorite = BooleanField(default=False)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    source = TextField(default="local")

    class Meta:
        table_name = "gen_history"
        indexes = (
            (("filename", "subfolder", "img_type"), True),  # unique
        )



class PromptCategory(BaseModel):
    """提示词-分类 多对多关系表"""
    prompt = ForeignKeyField(Prompt, backref="prompt_categories")
    category = ForeignKeyField(Category, backref="prompts")

    class Meta:
        table_name = "prompt_categories"
        indexes = (
            (("prompt", "category"), True),  # 联合唯一索引
        )


class PromptTag(BaseModel):
    """提示词-标签 多对多关系表"""
    prompt = ForeignKeyField(Prompt, backref="prompt_tags")
    tag = ForeignKeyField(Tag, backref="prompts")

    class Meta:
        table_name = "prompt_tags"
        indexes = (
            (("prompt", "tag"), True),  # 联合唯一索引
        )


def _migrate_column(db, table, col, col_def):
    """如果列不存在则 ALTER TABLE 添加（兼容旧库）。"""
    try:
        cursor = db.execute_sql(f"SELECT {col} FROM {table} LIMIT 0")
        cursor.close()
    except Exception:
        try:
            db.execute_sql(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            pass


def init_db():
    """确保表存在，并迁移新列（兼容 v3 旧库）。"""
    db.connect()
    db.create_tables([Prompt, GenJob, GenHistory], safe=True)

    # 迁移 GenHistory 新列
    _migrate_column(db, "gen_history", "prompt_params",
                     "prompt_params TEXT")
    _migrate_column(db, "gen_history", "favorite",
                     "favorite BOOLEAN NOT NULL DEFAULT 0")

    # ======== Phase 1: 迁移新字段 ========
    _migrate_column(db, "prompts", "is_favorite",
                     "is_favorite BOOLEAN NOT NULL DEFAULT 0")
    _migrate_column(db, "prompts", "is_pinned",
                     "is_pinned BOOLEAN NOT NULL DEFAULT 0")
    _migrate_column(db, "prompts", "usage_count",
                     "usage_count INTEGER NOT NULL DEFAULT 0")
    _migrate_column(db, "prompts", "last_used_at",
                     "last_used_at DATETIME")
    _migrate_column(db, "prompts", "rating",
                     "rating INTEGER")
    # ==========================================

    # ======== Phase 2: 创建新表 ========
    db.create_tables([Category, Tag, PromptCategory, PromptTag], safe=True)
    # ==========================================

    db.close()
