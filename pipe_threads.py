from threading import Thread
from subprocess import Popen, PIPE, STDOUT
import os

class PipeThread(Thread):
    def __init__(self, *args, **kwargs):
        Thread.__init__(self)
        self.args = args
        self.kwargs = kwargs
        self.p = None
        self.result = None
        self.returncode = None
    def run(self):
        p = Popen(*self.args,**self.kwargs)
        self.result = p.communicate()
        self.returncode = p.returncode
        if "stdout" in self.kwargs and type(self.kwargs["stdout"]) == int:
            fd = self.kwargs["stdout"]
            if fd > 2:
                os.close(self.kwargs["stdout"])
    def communicate(self):
        self.join()
        return self.result

if __name__ == "__main__":
    pipe = os.pipe()
    p1 = PipeThread(["echo","hello"], universal_newlines=True, stdout=pipe[1])
    p1.setDaemon(True)
    p1.start()
    p2 = PipeThread(["sed","s/h/H/"], universal_newlines=True, stdin=pipe[0], stdout=PIPE)
    p2.start();
    o, e = p2.communicate()
    print("out:",o,end='')
