import threading

from bottle import Bottle
from utils import log_msg, log_exception, LOGDEBUG

__bottle_manager = Bottle()
__manager_thread = None


def route_all(app):
    for kw in dir(app):
        attr = getattr(app, kw)
        if hasattr(attr, "route"):
            __bottle_manager.route(attr.route)(attr)


def start_thread(web_port):
    global __manager_thread
    __manager_thread = threading.Thread(
        daemon=True,  # thread will be killed on program exit
        target=lambda: __bottle_manager.run(
            host="localhost", port=web_port, debug=False, use_reloader=False
        ),
    )
    __manager_thread.start()


def stop_thread():
    log_msg("Closing bottle app.", LOGDEBUG)
    try:
        __bottle_manager.close()
    except Exception as exc:
        log_exception(exc, f"Bottle app closed with exception.")
