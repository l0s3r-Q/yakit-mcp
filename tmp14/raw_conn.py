# -*- coding: utf-8 -*-
import socket, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('127.0.0.1', 9011))
    print('9011 原始连接 OK')
    s.close()
except Exception as e:
    print('9011 连接失败:', repr(e))
# 再试 gRPC
import grpc
try:
    ch = grpc.insecure_channel('127.0.0.1:9011')
    grpc.channel_ready_future(ch).result(timeout=5)
    print('gRPC channel ready')
except Exception as e:
    print('gRPC 失败:', repr(e))
