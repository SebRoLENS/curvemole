"""Wait for disk tasks with a responsive Qt event loop."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEventLoop, QTimer


def run_background_io(operation):
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="CurveMoleRecoveryScan") as executor:
        future = executor.submit(operation)
        if not future.done():
            loop = QEventLoop()
            timer = QTimer()
            timer.setInterval(30)
            timer.timeout.connect(lambda: loop.quit() if future.done() else None)
            timer.start()
            loop.exec()
            timer.stop()
        return future.result()
