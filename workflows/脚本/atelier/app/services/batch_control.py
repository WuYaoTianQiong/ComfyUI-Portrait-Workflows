"""批量任务的跨请求停机信号（线程安全）。

原 `state.py`（4 行单变量）与 `shared.py`（纯再导出 + 一个无人使用的常量）
都只是"没想好放哪"的落点，按命名规范归位到服务层。
"""
import threading

# 批量出图 / 批量换脸的"立即停止"开关：
# 由 jobs 路由置位，各批处理循环内轮询 is_set() 后退出。
batch_stop_flag = threading.Event()
