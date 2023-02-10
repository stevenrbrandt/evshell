from typing import Optional, Dict, Any, Tuple
from threading import Thread, RLock
from subprocess import Popen, PIPE, STDOUT
from traceback import print_exc
import os
from .here import here
from time import sleep

lastpid : Optional[int] = None

def get_lastpid()->Optional[int]:
    return lastpid

runningLock = RLock()
running : Dict[int,'PipeThread'] = {}

def get_running(pid:int, verbose:bool=False)->Optional['PipeThread']:
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

def pwait(pid:Optional[int])->Optional['PipeThread']:
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
    def __init__(self)->None:
        Thread.__init__(self)
        self.setDaemon(True)

    def run(self)->None:
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
    def __init__(self, *args:Any, **kwargs:Any)->None:
        #Thread.__init__(self)
        self.args = args
        self.kwargs = kwargs
        self.result : Optional[Tuple[str,str]] = None
        self.returncode : Optional[int] = None
        self.p = Popen(*self.args,**self.kwargs)
        self.pid : int = self.p.pid
        self.run_in_background = False

    def background(self)->None:
        """
        Call this method before start if the
        intent is to run in the background.
        """
        global lastpid
        lastpid = self.p.pid
        self.run_in_background = True
        with runningLock:
            running[self.pid] = self

    def start(self)->None:
        pass

    def run(self)->None:
        assert self.p is not None
        self.result = self.p.communicate()
        self.returncode = self.p.returncode
        if "stdout" in self.kwargs and type(self.kwargs["stdout"]) == int:
            fd = self.kwargs["stdout"]
            if fd > 2:
                os.close(self.kwargs["stdout"])

    def is_running(self)->bool:
        return self.p.poll() is None

    def getpid(self)->Optional[int]:
        return self.pid

    def communicate(self)->Optional[Tuple[str,str]]:
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
    t = p2.communicate()
    if t is not None:
        o, e = t
    t = p2.communicate()
    if t is not None:
        o, e = t
    print("out:",o,end='')
