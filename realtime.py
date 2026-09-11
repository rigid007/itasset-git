# -*- coding: utf-8 -*-
"""WebSSH 实时终端：Flask-SocketIO + paramiko。"""
import logging
import threading

from flask import request
from flask_login import current_user
from flask_socketio import SocketIO, Namespace, emit

from extensions import db

logger = logging.getLogger(__name__)

socketio = SocketIO(async_mode='threading', cors_allowed_origins='*')


class SSHTerminalNamespace(Namespace):
    """/ssh 命名空间：设备交互式终端。"""

    def __init__(self, namespace):
        super().__init__(namespace)
        self._clients = {}  # sid -> {'client', 'channel', 'reader'}

    def _authorized(self):
        try:
            from utils.permission import has_permission
            return current_user.is_authenticated and has_permission(current_user, 'exec:view')
        except Exception:
            return False

    def on_connect(self, auth):
        return self._authorized()

    def on_connect_device(self, data):
        sid = request.sid
        if sid in self._clients:
            emit('ssh_error', {'message': '已有活动会话，请先断开'})
            return
        if not self._authorized():
            emit('ssh_error', {'message': '无权限使用终端'})
            return
        device_id = (data or {}).get('device_id')
        cols = int((data or {}).get('cols', 80) or 80)
        rows = int((data or {}).get('rows', 24) or 24)
        try:
            import paramiko
            from models.models import Device
            from utils.device_config import resolve_device_credential
            device = db.session.get(Device, int(device_id))
            if not device:
                emit('ssh_error', {'message': '设备不存在'})
                return
            host = device.management_ip or device.ip_address
            username, password, port = resolve_device_credential(device)
            if not host or not username:
                emit('ssh_error', {'message': '设备未配置 IP 或 SSH 凭据'})
                return
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                host, port=port, username=username, password=password,
                timeout=10, look_for_keys=False, allow_agent=False,
            )
            channel = client.invoke_shell(term='xterm', width=cols, height=rows)
            channel.settimeout(0.05)
            self._clients[sid] = {'client': client, 'channel': channel}

            def reader():
                buf = b''
                while sid in self._clients:
                    try:
                        chunk = channel.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        if b'\n' in buf or len(buf) > 4096:
                            emit('ssh_output', {'data': buf.decode(errors='replace')}, to=sid)
                            buf = b''
                    except Exception:
                        break
                if buf:
                    emit('ssh_output', {'data': buf.decode(errors='replace')}, to=sid)
                self._close(sid)
                emit('ssh_disconnected', {'message': '连接已关闭'}, to=sid)

            t = threading.Thread(target=reader, daemon=True)
            self._clients[sid]['reader'] = t
            t.start()
            emit('ssh_connected', {'message': f'已连接 {device.name} ({host})'})
        except Exception as e:
            logger.exception('[webssh] 连接失败')
            emit('ssh_error', {'message': f'连接失败: {e}'})

    def on_ssh_input(self, data):
        sid = request.sid
        client = self._clients.get(sid)
        if client:
            try:
                client['channel'].send((data or {}).get('data', ''))
            except Exception:
                self._close(sid)

    def on_resize(self, data):
        sid = request.sid
        client = self._clients.get(sid)
        if client:
            try:
                client['channel'].resize_pty(
                    width=int((data or {}).get('cols', 80)),
                    height=int((data or {}).get('rows', 24)),
                )
            except Exception:
                pass

    def on_disconnect_device(self, data=None):
        self._close(request.sid)
        emit('ssh_disconnected', {'message': '连接已断开'})

    def on_disconnect(self):
        self._close(request.sid)

    def _close(self, sid):
        client = self._clients.pop(sid, None)
        if not client:
            return
        try:
            client['channel'].close()
        except Exception:
            pass
        try:
            client['client'].close()
        except Exception:
            pass


socketio.on_namespace(SSHTerminalNamespace('/ssh'))
