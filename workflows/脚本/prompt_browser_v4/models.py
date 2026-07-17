"""Peewee ORM 模型 —— 映射 v3 已有的 SQLite 表结构"""
from peewee import (
    SqliteDatabase, Model, AutoField, TextField, IntegerField,
    FloatField, DateTimeField, BooleanField, SQL, ForeignKeyField,
    DeferredForeignKey
)
from config import settings

db = SqliteDatabase(
    str(settings.db_path),
    pragmas={"journal_mode": "delete", "foreign_keys": 1},
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
    color = TextField(default="#5b8fb9")  # 标签颜色（统一钢蓝）
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
    is_deleted = BooleanField(default=False)  # 软删除标记

    class Meta:
        table_name = "gen_history"
        # 唯一索引不由 peewee Meta.indexes 管理，而是由
        # _migrate_genhistory_unique_constraint 在 init_db 中创建
        # 部分唯一索引 (filename, subfolder, img_type) WHERE is_deleted=0，
        # 避免 peewee 创建非部分索引时被 is_deleted=1 的重复行触发 IntegrityError。
        indexes = ()



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

# ======== Phase 5: 图片分类 / 标签（复用提示词同一套分类法）========
class ImageCategory(BaseModel):
    """图片-分类 多对多关系表（快照拷贝，独立于提示词）"""
    image = ForeignKeyField(GenHistory, backref="image_categories")
    category = ForeignKeyField(Category, backref="images")

    class Meta:
        table_name = "image_categories"
        indexes = (
            (("image", "category"), True),  # 联合唯一索引
        )


class ImageTag(BaseModel):
    """图片-标签 多对多关系表（快照拷贝，独立于提示词）"""
    image = ForeignKeyField(GenHistory, backref="image_tags")
    tag = ForeignKeyField(Tag, backref="images")

    class Meta:
        table_name = "image_tags"
        indexes = (
            (("image", "tag"), True),  # 联合唯一索引
        )


def inherit_prompt_taxonomy(history_id: int, force: bool = False) -> int:
    """将来源提示词【当前】的分类/标签【快照拷贝】到图片。
    仅新增、绝不删除（尊重用户后续手动调整）。
    force=False 时若图片已有任意分类/标签则跳过（避免每次轮询重复写）。"""
    gh = GenHistory.get_or_none(GenHistory.id == history_id)
    if gh is None or not gh.prompt_id:
        return 0
    if not force:
        existing = (ImageCategory.select().where(ImageCategory.image == history_id).count()
                    + ImageTag.select().where(ImageTag.image == history_id).count())
        if existing > 0:
            return 0
    added = 0
    for pc in PromptCategory.select().where(PromptCategory.prompt == gh.prompt_id):
        _, created = ImageCategory.get_or_create(image=history_id, category=pc.category)
        if created:
            added += 1
    for pt in PromptTag.select().where(PromptTag.prompt == gh.prompt_id):
        _, created = ImageTag.get_or_create(image=history_id, tag=pt.tag)
        if created:
            added += 1
    return added


def backfill_image_taxonomy() -> int:
    """为所有带 prompt_id 且尚未分类的图片补齐来源提示词的分类/标签。"""
    done = 0
    for gh in GenHistory.select().where(GenHistory.prompt_id.is_null(False), GenHistory.is_deleted == False):
        if inherit_prompt_taxonomy(gh.id):
            done += 1
    return done


# ======== Phase 3: 模板系统 ========
class Template(BaseModel):
    """组合模板表"""
    id = AutoField()
    name = TextField()
    category = ForeignKeyField(Category, backref="templates", null=True)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    updated_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "templates"


class TemplateFragment(BaseModel):
    """模板碎片（引用式）"""
    id = AutoField()
    template = ForeignKeyField(Template, backref="fragments")
    prompt = ForeignKeyField(Prompt, backref="template_fragments", null=True)
    fragment_type = TextField()  # 人物外貌/姿态动作/...
    cached_content = TextField(default="")  # 快照，来源删除时兜底
    sort_order = IntegerField(default=0)

    class Meta:
        table_name = "template_fragments"


# ======== Phase 4: 碎片库 ========
class Fragment(BaseModel):
    """独立碎片（碎片库）"""
    id = AutoField()
    name = TextField(default="")              # 碎片名（用户可自定义）
    fragment_type = TextField()                # 人物面部/姿态动作/...
    content = TextField()                      # 碎片文本内容
    tags = TextField(default="")
    usage_count = IntegerField(default=0)      # 被引用次数
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    updated_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    class Meta:
        table_name = "fragments"
# ================================


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


# ======== 自动分类工具函数 ========
import re

AUTO_CATEGORIES = {
    "composite": {"name": "组合提示词", "color": "#6366f1"},
    "single":    {"name": "单项提示词", "color": "#f59e0b"},
    "scattered": {"name": "零散提示词", "color": "#6b7280"},
}

# 自动类型分类当前包含的名称集合；含已废弃的“片段提示词”以便清洗历史残留
_AUTO_TYPE_NAMES = {info["name"] for info in AUTO_CATEGORIES.values()} | {"片段提示词"}


def _clear_auto_type_categories(prompt_id: int):
    """清除该提示词上所有「自动类型」旧标签（含旧体系的片段提示词），
    避免重分类时新旧标签叠加成互相矛盾的标签。不影响用户的自定义主题分类。"""
    old_cats = list(Category.select().where(Category.name.in_(_AUTO_TYPE_NAMES)))
    if not old_cats:
        return
    old_ids = [c.id for c in old_cats]
    PromptCategory.delete().where(
        (PromptCategory.prompt == prompt_id) & (PromptCategory.category.in_(old_ids))
    ).execute()


def classify_prompt_text(prompt_text: str) -> str | None:
    """根据提示词文本检测类型：
    'composite'  ≥4种碎片
    'single'     1-3种碎片
    'scattered'  无【】标记
    """
    if not prompt_text:
        return None
    frags = re.findall(r"【([^】]+)】", prompt_text)
    n_types = len(set(frags))
    if n_types == 0:
        return "scattered"
    elif n_types >= 4:
        return "composite"
    else:
        return "single"


def auto_classify_prompt(prompt_id: int):
    """为单条提示词自动分配类型分类（幂等：先清旧自动类型标签，再赋正确值）。
    只管理自动类型分类，不删除用户自定义的主题分类。"""
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        return
    ptype = classify_prompt_text(p.prompt)
    if ptype is None:
        return
    # 先清掉该提示词上所有旧自动类型标签（含旧体系的片段提示词），避免叠加
    _clear_auto_type_categories(prompt_id)
    cat_info = AUTO_CATEGORIES[ptype]
    cat = Category.get_or_none(Category.name == cat_info["name"])
    if cat is None:
        cat = Category.create(name=cat_info["name"], color=cat_info["color"], parent_id=None)
    PromptCategory.create(prompt=prompt_id, category=cat.id)


def ensure_auto_categories():
    """确保三个自动分类在 categories 表中存在"""
    for key, info in AUTO_CATEGORIES.items():
        cat = Category.get_or_none(Category.name == info["name"])
        if cat is None:
            Category.create(name=info["name"], color=info["color"], parent_id=None)
# ================================


def _migrate_genhistory_unique_constraint(database):
    """将 gen_history 唯一约束回退到 (filename, subfolder, img_type) 三字段（部分索引）。

    历史：
      - v4.0 及之前: (filename, subfolder, img_type) —— 不同运行的同名文件被静默合并
      - v4.1: 升级为 (comfyui_prompt_id, filename, subfolder, img_type) —— 解决"合并覆盖"问题，
        却引入了新问题：不同运行的同名文件各存一条，但物理文件已被后者覆盖，
        导致多条记录指向同一份文件内容，画廊出现重复图。
      - v4.2 (本迁移): 降回 (filename, subfolder, img_type)，但改用 `WHERE is_deleted=0`
        部分唯一索引。不同运行的同名文件通过 ON CONFLICT DO UPDATE 覆写旧记录
        （id 不变，标签/分类/收藏不丢失），而非新插入。
    """
    # 删除含 comfyui_prompt_id 的旧唯一索引
    old = database.execute_sql(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='gen_history' "
        "AND sql LIKE '%comfyui_prompt_id%'"
    ).fetchall()
    for (idx_name,) in old:
        try:
            database.execute_sql(f'DROP INDEX "{idx_name}"')
            print(f"[migrate] 已删除旧唯一索引: {idx_name}")
        except Exception as e:
            print(f"[migrate] 删除 {idx_name} 失败: {e}")

    # 创建部分唯一索引 (已存在则跳过)
    try:
        database.execute_sql("""
            CREATE UNIQUE INDEX IF NOT EXISTS gen_history_filename_subfolder_img_type
            ON gen_history(filename, subfolder, img_type)
            WHERE is_deleted = 0
        """)
        print("[migrate] 已创建部分唯一索引 (filename, subfolder, img_type) WHERE is_deleted=0")
    except Exception as e:
        print(f"[migrate] 创建部分唯一索引（可能已存在）: {e}")


def init_db():
    """确保表存在，并迁移新列（兼容 v3 旧库）。"""
    db.connect()

    # 唯一约束迁移必须在 create_tables 之前，否则 peewee 的 safe=True 
    # 可能新建旧约束；新约束这里手动建好，后续 create_tables 的 IF NOT EXISTS 会跳过
    _migrate_genhistory_unique_constraint(db)

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
    # ======== Phase 5: 图片分类/标签表 ========
    db.create_tables([ImageCategory, ImageTag], safe=True)
    # ==========================================

    # 迁移：软删除字段
    _migrate_column(db, "gen_history", "is_deleted",
                    "is_deleted BOOLEAN NOT NULL DEFAULT 0")

    # ======== Phase 3: 模板表 ========
    db.create_tables([Template, TemplateFragment], safe=True)
    # ==========================================

    # ======== Phase 4: 碎片库 ========
    db.create_tables([Fragment], safe=True)
    # 迁移碎片库新列（兼容旧表）
    _migrate_column(db, "fragments", "name", "name TEXT NOT NULL DEFAULT ''")
    _migrate_column(db, "fragments", "tags", "tags TEXT NOT NULL DEFAULT ''")
    _migrate_column(db, "fragments", "updated_at",
                     "updated_at DATETIME")
    # ==========================================

    db.close()
