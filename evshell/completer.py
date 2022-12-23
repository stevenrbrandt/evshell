from threading import Thread
import readline
import os, re, sys
from time import time

#fd = open("log.txt","w")

class ExecDir:
    def __init__(self, dirname):
        Thread.__init__(self)
        self.dirname = dirname
        self.files = []
        self.st = None

    def scan(self):
        st = os.stat(self.dirname)
        if self.st is not None and \
           self.st.st_mtime == st.st_mtime and \
           self.st.st_ino == st.st_ino and \
           self.st.st_dev == st.st_dev:
             return
        self.st = st
        for f in os.listdir(self.dirname):
            fn = os.path.join(self.dirname,f)
            if os.path.isfile(fn) and os.access(fn, os.X_OK):
                self.files.append(f)

class ExecThread(Thread):
    def __init__(self,e):
        Thread.__init__(self)
        self.e = e
    def run(self):
        try:
            self.e.scan()
        except Exception as e:
            pass

class Completer:
    def __init__(self):
        self.matches = []
        self.cwd = None
        self.path = None
        self.cmds = []
        self.paths = {}
        t1 = time()
        self.update_cmds()
        t2 = time()
        print("Update cmd list:",t2-t1,"seconds")

    def update_cmds(self):
        cwd = os.getcwd()
        path = os.environ.get("PATH","")

        self.cmds = []
        threads = []
        for p in os.environ.get("PATH","").split(":"):
            try:
                if p == "":
                    p = "."
                e = self.paths.get(p,None)
                if e is None:
                    e = ExecDir(p)
                    self.paths[p] = e
                t = ExecThread(e)
                t.start()
                threads += [t]
            except Exception as e:
                #print(f"exc='{e}'",file=fd)
                #fd.flush()
                pass
        for t in threads:
            t.join()
            self.cmds += t.e.files

    def build_matches(self, current_word):

        buf = readline.get_line_buffer()
        g = re.match(r'.*\s',buf)
        if g:
            buf = buf[g.end():]
            use_cmd = False
        else:
            if buf.startswith(".") or buf.startswith("/"):
                use_cmd = False
            else:
                use_cmd = True

        if use_cmd:
            #print("update cmds...",file=fd)
            #fd.flush()
            self.update_cmds()
            #print(f"updated cmds: {len(self.cmds)}",file=fd)
            #fd.flush()
            self.matches = []
            for k in self.cmds:
                if k.startswith(buf):
                    self.matches += [k[len(buf)-len(current_word):]]
            #print(f"build cmd: cw({current_word}) buf({buf}) len({len(self.cmds)})",file=fd)
            #fd.flush()
            return

        dirname = re.sub(r'[^/*]*$','',buf)
        if dirname == "":
            dirname = "."

        matches = None
        try:
            if dirname == ".":
                matches = os.listdir(".")
            else:
                matches = [os.path.join(dirname,m) for m in os.listdir(dirname)]
        except Exception as e:
            matches = []
        self.matches = []
        for k in matches:
            if k.startswith(buf):
                self.matches += [k[len(buf)-len(current_word):]]

    def complete(self, current_word, state):
        try:
            if state == 0:
                self.build_matches(current_word)
            if state < len(self.matches):
                return self.matches[state]
            else:
                return None
        except Exception as e:
            #print_exc(file=fd)
            pass
        finally:
            pass
            #fd.flush()
