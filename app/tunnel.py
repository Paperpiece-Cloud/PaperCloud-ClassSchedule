"""自建 localtunnel 客户端（纯标准库）。

为什么要自己写：
    localtunnel 的官方客户端是 Node 包，但在本项目环境里装不上
    （pnpm 的隔离式 node_modules 在沙箱下解析不到 axios/openurl）。
    读了它的源码后发现协议极其简单，用标准库几十行就能实现：

      1. HTTP GET https://loca.lt/<你想要的子域名>
         -> 返回 {"id":..,"ip":..,"port":..,"url":"https://xxx.loca.lt", ...}
         这一步就把子域名占住了。
      2. 对远端 ip:port 建若干条 TCP 连接，
         每条连接收到的字节原样转发给本机 HTTP 服务，回包再原样发回去。
         没有任何握手、鉴权或分帧 —— 就是纯 TCP 转发。

于是可以拿到「自己起名字」的地址，例如：
    https://papercloud-temporary.loca.lt

注意：loca.lt 会给访客显示一个「点击继续」的中间页（防止滥用），
同学第一次打开要多点一下。要完全干净、固定的地址，还是得用自己的域名。
"""

import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

DEFAULT_SERVER = "https://loca.lt"
UA = "Mozilla/5.0 (compatible; kt-tunnel/1.0)"


class TunnelError(Exception):
    pass


class LocalTunnel:
    """把本机端口暴露成 https://<subdomain>.loca.lt。"""

    def __init__(self, subdomain, local_host="127.0.0.1", local_port=8787,
                 server=DEFAULT_SERVER, connections=6, verbose=True):
        self.subdomain = (subdomain or "").strip()
        self.local_host = local_host
        self.local_port = int(local_port)
        self.server = server.rstrip("/")
        self.connections = max(1, int(connections))
        self.verbose = verbose

        self.url = None
        self.remote_ip = None
        self.remote_port = None
        self.tunnel_id = None
        self._stop = False
        self._stats = {"connections": 0, "bytesUp": 0, "bytesDown": 0, "errors": 0}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 日志

    def _log(self, *a):
        if self.verbose:
            print("[隧道]", *a, flush=True)

    # ------------------------------------------------------------ 申请地址

    def _get_info(self, timeout=25):
        url = self.server + "/" + (self.subdomain or "?new")
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            # 有些部署会看这个头来决定要不要返回 JSON
            "X-Requested-With": "XMLHttpRequest",
        })
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise TunnelError(f"申请地址失败 HTTP {e.code} {body}")
        except Exception as e:
            raise TunnelError(f"申请地址失败 {type(e).__name__}: {e}")

        try:
            info = json.loads(raw)
        except Exception:
            raise TunnelError(f"服务端返回的不是 JSON：{raw[:200]}")

        if not info.get("url"):
            msg = info.get("message") or raw[:200]
            raise TunnelError(f"服务端没有分配地址：{msg}")
        return info

    # ------------------------------------------------------------ 数据转发

    @staticmethod
    def _pipe(src, dst, counter=None, stop_flag=None):
        """把 src 收到的字节原样写到 dst，直到一端关闭。"""
        try:
            while True:
                if stop_flag is not None and stop_flag():
                    break
                try:
                    chunk = src.recv(65536)
                except (socket.timeout, ssl.SSLWantReadError):
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                if counter is not None:
                    counter(len(chunk))
                try:
                    dst.sendall(chunk)
                except OSError:
                    break
        finally:
            # 半关闭：告诉对端这边没有更多数据了，但还能继续读
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _serve_one(self):
        """建立一条远端连接，并把它和本机服务对接起来。"""
        remote = socket.create_connection((self.remote_ip, self.remote_port), timeout=20)
        remote.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        remote.settimeout(300)

        local = socket.create_connection((self.local_host, self.local_port), timeout=20)
        local.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        local.settimeout(300)

        with self._lock:
            self._stats["connections"] += 1

        up = threading.Thread(
            target=self._pipe, args=(remote, local),
            kwargs={"counter": lambda n: self._bump("bytesUp", n)}, daemon=True)
        up.start()
        self._pipe(local, remote, counter=lambda n: self._bump("bytesDown", n))

        for s in (remote, local):
            try:
                s.close()
            except OSError:
                pass

    def _bump(self, key, n):
        with self._lock:
            self._stats[key] += n

    def _worker(self):
        while not self._stop:
            try:
                self._serve_one()
            except Exception:
                with self._lock:
                    self._stats["errors"] += 1
                if self._stop:
                    break
                time.sleep(0.5)

    # ------------------------------------------------------------ 生命周期

    def start(self):
        """申请地址并开始转发。返回分配到的 url。"""
        info = self._get_info()
        self.url = info["url"]
        self.remote_ip = info.get("ip")
        self.remote_port = info.get("port")
        self.tunnel_id = info.get("id")

        if not self.remote_ip or not self.remote_port:
            raise TunnelError("服务端没给转发地址（ip/port）")

        self._log(f"地址已分配：{self.url}")
        self._log(f"转发节点：{self.remote_ip}:{self.remote_port}")
        self._log(f"本机目标：{self.local_host}:{self.local_port}")

        for _ in range(self.connections):
            threading.Thread(target=self._worker, daemon=True).start()

        return self.url

    def stop(self):
        self._stop = True

    @property
    def stats(self):
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------- CLI

def main():
    import argparse

    ap = argparse.ArgumentParser(description="自建 localtunnel 客户端")
    ap.add_argument("subdomain", help="你想要的子域名，例如 papercloud-temporary")
    ap.add_argument("--port", type=int, default=8787, help="本机端口（默认 8787）")
    ap.add_argument("--conn", type=int, default=6, help="并发连接数（默认 6）")
    ap.add_argument("--server", default=DEFAULT_SERVER, help=f"隧道服务（默认 {DEFAULT_SERVER}）")
    args = ap.parse_args()

    t = LocalTunnel(args.subdomain, local_port=args.port,
                    server=args.server, connections=args.conn)
    try:
        url = t.start()
    except TunnelError as e:
        print("[隧道] 失败:", e)
        return 1

    print()
    print("=" * 58)
    print(f"  公网地址： {url}")
    print("=" * 58)
    print("  保持这个窗口开着，关掉隧道就断了。Ctrl+C 退出。")
    print()
    try:
        while True:
            time.sleep(30)
            s = t.stats
            print(f"[隧道] 连接 {s['connections']} 次 · 上行 {s['bytesUp']//1024}KB "
                  f"· 下行 {s['bytesDown']//1024}KB · 错误 {s['errors']}", flush=True)
    except KeyboardInterrupt:
        t.stop()
        print("\n[隧道] 已停止")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
