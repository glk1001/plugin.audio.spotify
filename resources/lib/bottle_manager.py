import socket
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer
from wsgiref.simple_server import make_server

import bottle
from bottle import Bottle
from utils import log_msg, log_exception, LOGDEBUG


class MyWSGIRefServer(bottle.WSGIRefServer):
    def __init__(self, host: str = "", port: int = 0):
        super().__init__(host, port)
        self.srv = None

    def run(self, app):  # pragma: no cover
        class FixedHandler(WSGIRequestHandler):
            # Prevent reverse DNS lookups.
            def address_string(self):
                return self.client_address[0]

            def log_request(*args, **kw):
                if not self.quiet:
                    return WSGIRequestHandler.log_request(*args, **kw)

        handler_cls = self.options.get("handler_class", FixedHandler)
        server_cls = self.options.get("server_class", WSGIServer)

        if ":" in self.host:
            # Fix wsgiref for IPv6 addresses.
            if getattr(server_cls, "address_family") == socket.AF_INET:

                class AddressFamilyServerCls(server_cls):
                    address_family = socket.AF_INET6

                server_cls = AddressFamilyServerCls

        srv = make_server(self.host, self.port, app, server_cls, handler_cls)
        # THIS IS THE ONLY CHANGE TO THE ORIGINAL BOTTLE CLASS METHOD!
        self.srv = srv
        srv.serve_forever()

    # ADD SERVER SHUTDOWN METHOD.
    def shutdown(self):
        self.srv.shutdown()


__server: MyWSGIRefServer = MyWSGIRefServer()
__bottle_manager: Bottle = Bottle()
__manager_thread: threading.Thread = threading.Thread()


def route_all(app):
    for kw in dir(app):
        attr = getattr(app, kw)
        if hasattr(attr, "route"):
            __bottle_manager.route(attr.route)(attr)


def __begin_app():
    bottle.run(app=__bottle_manager, server=__server)


def start_thread(web_port):
    global __manager_thread
    global __server
    __server = MyWSGIRefServer(host="localhost", port=web_port)
    __manager_thread = threading.Thread(target=__begin_app)
    __manager_thread.start()


def stop_thread():
    log_msg("Closing bottle app and thread.", LOGDEBUG)
    try:
        __bottle_manager.close()
        __server.shutdown()
        __manager_thread.join()
    except Exception as exc:
        log_exception(exc, f"Bottle app closed with exception.")
