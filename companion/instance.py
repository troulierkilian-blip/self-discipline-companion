from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, directory: Path):
        super().__init__()
        directory.mkdir(parents=True, exist_ok=True)
        self.name = "DailyCompanion-" + hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:24]
        self.lock = QLockFile(str(directory / "instance.lock"))
        self.lock.setStaleLockTime(30000)
        self.is_primary = self.lock.tryLock(0)
        self.server = None
        self.sockets = []
        if self.is_primary:
            self.server = QLocalServer(self)
            if not self.server.listen(self.name):
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    raise RuntimeError("无法创建本地窗口激活通道。")
            self.server.newConnection.connect(self.accept)
        else:
            sock = QLocalSocket()
            sock.connectToServer(self.name)
            if not sock.waitForConnected(2000):
                raise RuntimeError("软件正在启动，请稍后再次打开。")
            sock.write(b"activate")
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()

    def accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.sockets.append(sock)
            sock.disconnected.connect(lambda s=sock: self.cleanup(s))
            self.activated.emit()
            sock.disconnectFromServer()

    def cleanup(self, sock):
        if sock in self.sockets:
            self.sockets.remove(sock)
        sock.deleteLater()

    def close(self):
        if self.server:
            self.server.close()
        if self.is_primary:
            self.lock.unlock()
