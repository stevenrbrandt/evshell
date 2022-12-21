from threading import Thread, RLock
from subprocess import Popen, PIPE, STDOUT
from traceback import print_exc
import os
from here import here
from time import sleep

lastpid = None

def get_lastpid():
    return lastpid

runningLock = RLock()
running = {}

def get_running(pid, verbose=False):
    with runningLock:
        if pid is None:
            for k in running:
                pid = k
                if verbose:
                    print("pid:",pid)
                break
            if pid is None:
                return
        return running.get(pid,None)

def pwait(pid):
    if pid is not None:
        with runningLock:
            p = running.get(pid,None)
            if p is None:
                return None
            p.communicate()
            del running[pid]
            return p
    else:
        while True:
            with runningLock:
                for k in running:
                    p = running[k]
                    if not p.is_running():
                        del running[k]
                        return p
            sleep(.1)
    return None

class PipeRunner(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.setDaemon(True)

    def run(self):
        count = 0
        while True:
            with runningLock:
                vals = running.values()
            for p in vals:
                if p.returncode is None and not p.is_running():
                    p.run()
                    count = 0
                else:
                    count += 1
            if   count > 10000:
                sleep(1)
            elif count > 1000:
                sleep(.1)
            elif count > 100:
                sleep(.01)

_pipe_runner = PipeRunner()
_pipe_runner.start()

class PipeThread: #(Thread):
    def __init__(self, *args, **kwargs):
        #Thread.__init__(self)
        self.args = args
        self.kwargs = kwargs
        self.p = None
        self.pid = None
        self.result = None
        self.returncode = None
        self.p = Popen(*self.args,**self.kwargs)
        self.pid = self.p.pid
        self.run_in_background = False

    def background(self):
        """
        Call this method before start if the
        intent is to run in the background.
        """
        global lastpid
        lastpid = self.p.pid
        self.run_in_background = True
        with runningLock:
            running[self.pid] = self

    def start(self):
        pass

    def run(self):
        self.result = self.p.communicate()
        self.returncode = self.p.returncode
        if "stdout" in self.kwargs and type(self.kwargs["stdout"]) == int:
            fd = self.kwargs["stdout"]
            if fd > 2:
                os.close(self.kwargs["stdout"])

    def is_running(self):
        return self.p.poll() is None

    def getpid(self):
        return self.pid

    def communicate(self):
        if self.run_in_background:
            while self.returncode is None:
                sleep(.01)
        else:
            self.run()
        return self.result

if __name__ == "__main__":
    pipe = os.pipe()
    env = os.environ
    p1 = PipeThread(["echo","hello"], universal_newlines=True, stdout=pipe[1], env=env)
    #p1.setDaemon(True)
    p1.start()
    p2 = PipeThread(["sed","s/h/H/"], universal_newlines=True, stdin=pipe[0], stdout=PIPE, env=env)
    p2.start();
    o, e = p2.communicate()
    o, e = p2.communicate()
    print("out:",o,end='')
