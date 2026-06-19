"""跨请求共享状态（线程安全）"""
import threading

batch_stop_flag = threading.Event()
