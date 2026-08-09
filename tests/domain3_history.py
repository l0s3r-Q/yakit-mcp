# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 3 域: 历史与分组管理
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_clear_history, yakit_list_tasks,
                               yakit_list_labels, yakit_add_label, yakit_delete_label)

engine, gui_alive = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()} GUI={gui_alive}")

print("\n########## 1. yakit_list_tasks（历史任务列表）##########")
p("list_tasks", yakit_list_tasks())

print("\n########## 2. yakit_add_label 新建分组 ##########")
r = json.loads(yakit_add_label("实战测试分组", "domain3 测试用"))
p("add_label", r)
label_hash = None
if r.get("items"):
    label_hash = r["items"][0].get("hash") if isinstance(r["items"][0], dict) else None
elif r.get("hash"):
    label_hash = r["hash"]
print("获取到 hash:", label_hash)

print("\n########## 3. yakit_list_labels 列出分组 ##########")
p("list_labels", yakit_list_labels())

print("\n########## 4. yakit_delete_label 删除分组 ##########")
if label_hash:
    p("delete_label", yakit_delete_label(label_hash))
else:
    print("无 hash，尝试从 list 中取一个删除")
    ls = json.loads(yakit_list_labels())
    items = ls.get("labels") or ls.get("data") or []
    if items:
        h = items[0].get("hash") or items[0].get("Hash")
        if h:
            p("delete_label", yakit_delete_label(str(h)))
        else:
            print("items 无 hash 字段:", str(items[0])[:200])
    else:
        print("无标签可删")

print("\n########## 5. yakit_clear_history 清空历史（谨慎：先看任务数）##########")
p("clear_history", yakit_clear_history())

print("\n########## 6. 清空后 list_tasks 验证 ##########")
p("list_tasks_after", yakit_list_tasks())

print("\n历史分组域测试完成")