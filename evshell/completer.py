from typing import List, Optional, Dict, Union, cast
from threading import Thread
import readline
import os, re, sys
from time import time
import pwd

home = pwd.getpwuid(os.getuid()).pw_dir

#fd = open("log.txt","w")

class ExecDir:
    def __init__(self, dirname:str)->None:
        self.dirname = dirname
        self.files : List[str] = []
        self.st : Optional[os.stat_result]= None

    def scan(self)->None:
        if not os.path.isdir(self.dirname):
            return
        st = os.stat(self.dirname)
        if self.st is not None and \
           self.st.st_mtime == st.st_mtime and \
           self.st.st_ino == st.st_ino and \
           self.st.st_dev == st.st_dev:
             return
        self.st = st
        for f in os.listdir(self.dirname):
            # While the next two lines are more correct, they are horrendously slow
            #fn = os.path.join(self.dirname,f)
            #if os.path.isfile(fn) and os.access(fn, os.X_OK):
            self.files.append(f)

class Completer:
    def __init__(self) -> None:
        self.matches : List[str] = []
        self.cwd : Optional[str] = None
        self.path : Optional[str] = None
        self.cmds : List[str] = []
        self.paths : Dict[str,ExecDir] = {}
        self.update_cmds()

    def update_cmds(self)->None:
        cwd = os.getcwd()
        path = os.environ.get("PATH","")

        self.cmds = []
        for p in os.environ.get("PATH","").split(":"):
            if p == "":
                p = "."
            e = self.paths.get(p,None)
            if e is None:
                e = ExecDir(p)
                e.scan()
                self.paths[p] = e
            self.cmds += e.files

    def build_matches(self, current_word:str)->None:

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
            elif dirname.startswith("~/"):
                # This is a temporary hack.
                fix_dirname = os.path.join(home, dirname[2:])
                #print("fix_dirname:",fix_dirname,file=fd)
                #fd.flush()
                matches = [os.path.join(dirname,m) for m in os.listdir(fix_dirname)]
            else:
                #print("dirname:",dirname,file=fd)
                #fd.flush()
                matches = [os.path.join(dirname,m) for m in os.listdir(dirname)]
        except Exception as e:
            #print(e,file=fd)
            #fd.flush()
            matches = []
        self.matches = []
        for k in matches:
            if k.startswith(buf):
                self.matches += [k[len(buf)-len(current_word):]]

    def complete(self, current_word:str, state:int)->Optional[str]:
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
        return None
