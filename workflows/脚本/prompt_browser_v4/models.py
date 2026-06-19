"""Peewee ORM 模型 —— 映射 v3 已有的 SQLite 表结构"""
from peewee import (
    SqliteDatabase, Model, AutoField, TextField, IntegerField,
    FloatField, DateTimeField, BooleanField, SQL
)
from config import settings

db = SqliteDatabase(
    str(settings.db_path),
    pragmas={"journal_mode": "wal", "foreign_keys": 1},
)


class BaseModel(Model):
    class Meta:
        database = db


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
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])
    source = TextField(default="local")

    class Meta:
        table_name = "gen_history"
        indexes = (
            (("filename", "subfolder", "img_type"), True),  # unique
        )


def init_db():
    """确保表存在（兼容 v3 schema）。"""
    db.connect()
    # Peewee 只创建不存在的表，不修改已有表结构
    db.create_tables([Prompt, GenJob, GenHistory], safe=True)
    # 兼容旧 schema：如果 v3 库已有表但没有 updated_at 列，Peewee 不报错但也不会加
    # 这里不做迁移，因为 v3 的 init_db() 已处理过
    db.close()
