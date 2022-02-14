#!/usr/bin/env python3 
# Purpose of Piebash
# (1) Security for Science Gateways
# (2) Supercharge Jupyter: Allow in-process calling of bash from Python, save ENVIRON variables, etc.
# (3) Call python functions from bash or bash functions from python
from Piraha import parse_peg_src, Matcher, Group
from subprocess import Popen, PIPE, STDOUT
import os
import sys
import re
from traceback import print_exc

def here(*args):
    import inspect
    stack = inspect.stack()
    frame = stack[1]
    print("HERE:","%s:%d" % (frame.filename, frame.lineno), *args, flush=True)
    frame = None
    stack = None

class ExitShell(Exception):
    def __init__(self, rc):
        self.rc = rc

import io
home = os.environ["HOME"]
log_file = os.path.join(home,"log_shell.txt")
log_fd = io.TextIOWrapper(open(log_file,"ab",0), write_through=True)
sys.stderr.flush()
#sys.stderr = open(log_file,"ab",0)

my_shell = os.path.realpath(sys.argv[0])

Never = object()

class TFN:

    def __init__(self, b):
        if b in [True, False]:
            self.b = b
        elif b == "True":
            self.b = True
        elif b == "False":
            self.b = False
        else:
            self.b = Never

    def toggle(self):
        if self.b == True:
            self.b = False
        elif self.b == False:
            self.b = True
        elif self.b == Never:
            pass
        else:
            raise Exception("bad state")

    def __bool__(self):
        if self.b in [True, False]:
            return self.b
        else:
            return False

def unesc(s):
    s2 = ""
    i = 0
    while i < len(s):
        if s[i] == '\\':
            s2 += s[i+1]
            i += 2
        else:
            s2 += s[i]
            i += 1
    return s2

verbose = False

sftp_default = "/usr/libexec/openssh/sftp-server"
sftp = os.environ.get("SFTP",sftp_default)

exe_dir = re.sub(r'/*$','/',os.environ.get("EXE_DIR",os.path.join(os.environ["HOME"],"exe")))

if sys.stdout.isatty():
    from termcolor import colored
else:
    def colored(txt,_):
        return txt

grammar = r"""
skipper=\b([ \t]|\\\n|\#.*)*
raw_word=(\\.|[^\\"'\t \n\$\#&\|;{}`()<>?*,])+
dchar=[^"$\\]
dlit=\\.
dquote="({dlit}|{dchar}|{var}|{math}|{subproc}|{bquote})*"
bquote=`(\\.|[^`$]|{var}|{math}|{subproc})*`
squote='(\\.|[^'])*'
unset=:-
unset_raw=-
rm_front=\#\#?
rm_back=%%?
w=[a-zA-Z0-9_]+
var=\$({w}|\{({w}({unset}{words2}|{unset_raw}{raw_word}|{rm_front}{word2}|{rm_back}{word2}|))\})
func=function {ident} \( \) \{( {cmd})* \}[ \t]*\n

worditem=({glob}|{redir}|{ml}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote})
worditemex=({glob}|{redir}|{ml}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote}|{expand})
word={expand}{-worditemex}+|{-worditem}{-worditemex}*

word2=({glob}|{redir}|{ml}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote})
words2={word2}+

ending=(&&?|\|[\|&]?|;|\n|$)
fd_from=[0-9]+
fd_to=&[0-9]+
redir=({fd_from}|)>({fd_to}|)
ident=[a-zA-Z0-9][a-zA-Z0-9_]*
ml=<< {ident}
math=\$\(\((\)[^)]|[^)])*\)\)
subproc=\$\(( {cmd})* \)
cmd=(( {word})+( {ending}|)|{ending})
glob=\?|\*|\[.-.\]
expand=[\{,\}]
whole_cmd=( {func}|{cmd})* $
"""
pp,_ = parse_peg_src(grammar)

class For:
    def __init__(self,variable,values):
        self.variable = variable
        self.values = values
        self.index = 0
        self.docmd = -1
        self.donecmd = -1
    def __repr__(self):
        return f"For({self.variable},{self.values},{self.docmd},{self.donecmd})"

class WordIter:
    def __init__(self, a):
        self.a = a
        self.index = -1
        self.iter = 1
        self.s = ""
        self.is_glob = False
        self.c = None

    def copy(self, w):
        self.a = w.a
        self.index = w.index
        self.iter = w.iter
        self.s = w.s
        self.is_glob = w.is_glob
        self.c = w.c

    def __repr__(self):
        return f"{self.index}/{len(self.a)} i={self.iter}/{len(self.s)} s='{self.s}'"

    def sets(self):
        if isinstance(self.a[self.index],Group):
            self.is_glob = True
            self.s = self.a[self.index].substring()
        else:
            self.is_glob = False
            self.s = self.a[self.index]
            assert type(self.s) == str

    def decr(self):
        assert self.iter > 0
        self.iter -= 1

    def incr(self):
        while True:
            if self.iter >= len(self.s):
                if self.index+1 < len(self.a):
                    self.index += 1
                    self.iter = 0
                    self.sets()
                    continue
                else:
                    here('-Done2-')
                    return False
            self.c = self.s[self.iter]
            self.iter += 1
            here("-Iter-")
            return True

        if self.index >= len(self.a):
            here("-Done-")
            return False

class Space:
    def __repr__(self):
        return " "

def spaceout(a):
    b = []
    for i in range(len(a)):
        if i > 0:
            b += [Space()]
        b += [a[i]]
    return b

def deglobw(w,j=0):
    files = None
    while w.incr():
        here(files)
        if not w.is_glob:
            if files is None:
                if w.c == '/':
                    files = os.listdir('/') + ["."] + [".."]
                    for f in range(len(files)):
                        files = "/" + files[f]
                else:
                    files = os.listdir('.') + ["."] + [".."]
            here(files)
            new_files = []
            delj = 0
            for f in files:
                if j < len(f) and f[j] == w.c:
                    delj = 1
                    new_files += [f]
                elif w.c == '/' and len(f) == j:
                    for k in os.listdir(f):
                        new_files += [f+'/'+k]
                    w.decr()
            j += delj
            files = new_files
        elif w.c == '?':
            new_files = []
            delj = 0
            for k in files:
                if j < len(k):
                    delj = 1
                    new_files += [k]
            here("j:",j,delj)
            j += delj
            files = new_files
        elif w.c == '*':
            if not w.incr():
                return files
            else:
                w.decr()
        else:
            here()
            files = []
            break
    here('fin')
    if w.incr():
        here()
        files = []
    new_files = []
    for f in files:
        if j == len(f):
            new_files += [f]
    files = new_files
    return files

def deglob(a):

    assert type(a) == list
    has_glob = False
    for k in a:
        if isinstance(k, Group):
            has_glob = True
    if not has_glob:
        return a

    s = []
    raw = ''
    for k in a:
        if isinstance(k,Group) and k.is_("glob"):
            ks = k.substring()
            s += [("g"+ks,k)]
            raw += ks
        elif isinstance(k,Group) and k.is_("expand"):
            here("remove this")
            #ks = k.substring()
            #for c in ks:
            #    s += [(c,)]
            #raw += ks
        elif type(k) == str:
            for c in k:
                s += [(c,)]
            raw += k
        else:
            assert False
    files = fmatch(None, s, i1=0, i2=0)
    if len(files) == 0:
        return [raw]
    else:
        return spaceout(files)

def deglob__(a):
    assert type(a) == list
    has_glob = False
    for k in a:
        if isinstance(k, Group):
            has_glob = True
    if not has_glob:
        return a
    w = WordIter(a)
    print("*" * 20)
    while w.incr():
        here("w.c:",w.c,"w.is_glob:",w.is_glob)
    print("*" * 20)
    w = WordIter(a)
    files = deglobw(w)
    for f in files:
        print(colored("->","green"),f)
    here("done")
    exit(0)

def deglob_(a):
    assert type(a) == list
    has_glob = False
    for k in a:
        if isinstance(k, Group):
            has_glob = True
    if not has_glob:
        return a
    raw = ''
    s = r'^'
    for k in a:
        if isinstance(k, Group):
            ss = k.substring()
            raw += ss
            if ss == "*":
                s += ".*"
            elif ss == "?":
                s += ".?"
            elif ss[0] == '[':
                s += ss
            elif ss[0] == '{':
                s += "(" + ss[1:-1].replace(",","|") + ")"
            else:
                assert False
        elif type(k) == str:
            raw += k
            for c in k:
                if re.match(r'^[a-zA-Z0-9_]$', c):
                    s += c
                else:
                    s += '\\'+c
        else:
            assert False
    s += '$'
    res = []
    for f in os.listdir('.'):
        if re.match(s, f):
            res += [f]
    if len(res) == 0:
        return [raw]
    return res

class Expando:
    def __init__(self):
        self.a = [[]]
        self.parent = None

    def start_new_list(self):
        e = Expando()
        e.parent = self
        self.a[-1] += [e]
        return e

    def start_new_alternate(self):
        self.a += [[]]

    def end_list(self):
        return self.parent

    def add_item(self, item):
        self.a[-1] += [item]

    def __repr__(self):
        return "Expando("+str(self.a)+")"

    def build_strs(self):
        streams = [a for a in self.a]
        final_streams = []
        show = False
        while len(streams) > 0:
            new_streams = []
            for stream in streams:
                found = False
                for i in range(len(stream)):
                    item = stream[i]
                    if isinstance(item,Expando):
                        found = True
                        show = True
                        for a in item.a:
                            new_stream = stream[:i]+a+stream[i+1:]
                            new_streams += [new_stream]
                        break
                if not found:
                    final_streams += [stream]
            streams = new_streams
        return final_streams
            
def expand1(a,ex=None,i=0,sub=0):
    if ex is None:
        ex = Expando()
    sub = 0
    for i in range(len(a)):
        if isinstance(a[i], Group) and a[i].is_("expand"):
            if a[i].substring() == "{":
                ex = ex.start_new_list()
            elif a[i].substring() == '}':
                ex = ex.end_list()
            elif a[i].substring() == ',':
                ex.start_new_alternate()
            else:
                ex.add_item(a[i])
        else:
            ex.add_item(a[i])
    return ex

def expand(a,i=0,sub=False):
    items = []
    streams = []
    while i < len(a):
        if isinstance(a[i], Group) and a[i].is_("expand"):
            if a[i].substring() == "{":
                sub_streams = expand(a,i+1,True)
                new_streams = [] + streams
                for s2 in sub_streams:
                    new_streams += [items + s2]
                return new_streams
            elif a[i].substring() == ",":
                if sub:
                    streams += [items]
                    items = []
                else:
                    items += [","]
            elif a[i].substring() == "}":
                if sub:
                    pass #return streams + [items]
                else:
                    items += ["}"]
        else:
            items += [a[i]]
        i += 1
    return streams + [items]

def fmatch(fn,pat,i1=0,i2=0):
    while True:
        if fn is None:
            result = []
            if pat[0] == ('/',):
                for d in os.listdir(fp):
                    result += fmatch('/'+d, pat, 1, 1)
            else:
                for d in os.listdir('.'):
                    result += fmatch(d, pat, 0, 0)
            return result
        elif i2 == len(pat) and i1 == len(fn):
            return [fn]
        elif i1 == len(fn) and pat[i2] == ('/',):
            dd = []
            for k in os.listdir(fn):
                ff = os.path.join(fn,k)
                if i1 <= len(ff):
                    dd += fmatch(os.path.join(fn,k), pat, i1, i2)
            return dd
        elif i2 >= len(pat):
            return []
        elif pat[i2][0] == 'g?':
            i1 += 1
            i2 += 1
        elif pat[i2][0] == 'g*':
            if i2+1 <= len(pat):
                result = fmatch(fn, pat, i1, i2+1)
            else:
                restult = []
            if i1+1 <= len(fn):
                if len(result) == 0:
                    result = fmatch(fn, pat, i1+1, i2+1)
                if len(result) == 0:
                    result = fmatch(fn, pat, i1+1, i2)
            return result
        elif i1 < len(fn) and i2 < len(pat) and (fn[i1],) == pat[i2]:
            i1 += 1
            i2 += 1
        else:
            return []


def cat(a, b):
    assert type(a) == list
    if type(b) == list:
        #a[-1] += b[0]
        a += b
    elif type(b) == str:
        if len(a) == 0:
            a += [""]
        a[-1] += b
    else:
        assert False

class shell:
    
    def __init__(self,stdout = sys.stdout, stderr = sys.stderr):
        self.txt = ""
        self.vars = {"?":"0", "*":" ".join(sys.argv[2:])}
        self.stdout = stdout
        self.stderr = stderr
        self.lines = []
        self.cmds = []
        self.stack = []
        self.for_loops = []
        self.funcs = {}
        self.output = ""
        self.error = ""

    def eval(self, gr, index=-1):
        r = self.eval_(gr,index)
        if r is None:
            r = []
        assert type(r) in [list, str], gr.dump()+" "+repr(type(r))+" r="+repr(r)
        return r

    def eval_(self, gr, index=-1):
        if index == -1:
            index = len(self.cmds)
            self.cmds += [gr]
        assert index >= 0 and index < len(self.cmds), f"index={index}/{len(self.cmds)}"
        assert gr == self.cmds[index]
        if gr.is_("whole_cmd"):
            #here("wc:",gr.dump())
            result = []
            ending = ""
            for c in gr.children:
                if ending == "&&" and self.vars["?"] != "0":
                    continue
                elif ending == "||" and self.vars["?"] == "0":
                    continue
                result = self.eval(c)
                if c.has(-1,"ending"):
                    ending = c.has(-1).substring()
            return result
        elif gr.is_("cmd"):
            args = []
            skip = False

            for k in gr.children:
                if not k.is_("ending") and not k.has(0,"redir"):
                    ek = self.eval(k)
                    #here(ek,k.dump())
                    exk = expand1(ek).build_strs()
                    #here("ex=>",str(ex1))
                    #here("bs=",ex1.build_strs())
                    #exk = expand(ek)
                    for nek in exk:
                        nek = deglob(nek)
                        if type(nek) == str:
                            args += [nek]
                        elif type(nek) == list:
                            #args += ["".join(nek)]
                            args += [""]
                            for kk in nek:
                                if isinstance(kk,Space):
                                    args += [""]
                                else:
                                    args[-1] += kk
                        else:
                            assert False
                    #here(args,k.dump())

            if len(args)>0:
                here("cmd:",args)
                if args[0] == "for":
                    f = For(args[1],args[3:])
                    self.for_loops += [f]
                    if f.index < len(f.values):
                        self.vars[f.variable] = f.values[f.index]
                    here(self.for_loops)
                    return

                elif args[0] == "do":
                    f = self.for_loops[-1]
                    if f.docmd == -1:
                        f.docmd = index
                    args = args[1:]

                elif args[0] == "done":
                    f = self.for_loops[-1]
                    assert f.docmd != -1
                    f.donecmd = index
                    if len(f.values) > 1:
                        for ii in range(1,len(f.values)):
                            f.index = ii
                            self.vars[f.variable] = f.values[f.index]
                            for cmdnum in range(f.docmd,f.donecmd):
                                self.eval(self.cmds[cmdnum], cmdnum)
                    self.for_loops = self.for_loops[:-1]
                    return

                if args[0] == "then":
                    args = args[1:]

                elif args[0] == "else":
                    args = args[1:]
                    self.stack[-1][1].toggle()

                if args[0] == "if":
                    if len(self.stack) > 0 and not self.stack[-1][1]:
                        self.stack += [("if",TFN(Never))]
                    else:
                        endmark = None
                        # if [ a = b ] ;
                        #  7 6 5 4 3 2 1
                        # if [ a = b ] 
                        #  6 5 4 3 2 1 
                        if gr.Has(-1,"ending").StrEq(-7,"if").StrEq(-6,"[").StrEq(-2,"]").Has(-1,"ending").eval():
                            endmark = -2
                        elif gr.StrEq(-6,"if").StrEq(-5,"[").StrEq(-1,"]").eval():
                            endmark = -1
                        elif gr.Has(-1,"ending").StrEq(-7,"if").StrEq(-6,"[[").StrEq(-2,"]]").Has(-1,"ending").eval():
                            endmark = -2
                        elif gr.StrEq(-6,"if").StrEq(-5,"[[").StrEq(-1,"]]").eval():
                            endmark = -1
            
                        if endmark is not None:
                            testresult = 0
                            op = unesc(gr.has(endmark-2).substring())
                            arg1 = gr.has(endmark-3)
                            arg2 = gr.has(endmark-1)
                            if op == "=":
                                testresult = (arg1.substring() == arg2.substring())
                            elif op == "!=":
                                testresult = (arg1.substring() != arg2.substring())
                            elif op == "<":
                                testresult = (float(arg1.substring()) < float(arg2.substring()))
                            elif op == ">":
                                testresult = (float(arg1.substring()) > float(arg2.substring()))
                            else:
                                raise Exception(op)

                        self.stack += [("if",TFN(testresult))]
                elif args[0] == "fi":
                    self.stack = self.stack[:-1]
            if len(self.stack) > 0:
                skip = not self.stack[-1][1]
            if len(self.for_loops)>0:
                f = self.for_loops[-1]
                if f.index >= len(f.values):
                    skip = True
            if skip:
                return []
            if len(args)==0:
                return []
            if args[0] in self.funcs:
                for c in self.funcs[args[0]]:
                    self.eval(c)
                return []
            elif args[0] not in ["if","then","else","fi","for","done"]:
                #if args[0] == "if":
                #    self.stack += [("if",line)]
                sout = self.stdout
                serr = self.stderr
                if not os.path.exists(args[0]):
                    for path in os.environ.get("PATH",".").split(":"):
                        full_path = os.path.join(path, args[0])
                        if os.path.exists(full_path):
                            args[0] = full_path
                            break
                if os.path.exists(args[0]):
                    try:
                        with open(args[0],"r") as fd:
                            first_line = fd.readline()
                            if first_line.startswith("#!"):
                                args = re.split(r'\s+',first_line[2:].strip()) + args
                    except:
                        pass
                try:
                    p = Popen(args, stdout=sout, stderr=serr, universal_newlines=True)
                except OSError as e:
                    args = ["/bin/sh"]+args
                    p = Popen(args, stdout=sout, stderr=serr, universal_newlines=True)
                o, e = p.communicate("")
                if type(o) == str:
                    self.output += o
                if type(e) == str:
                    self.error += e
                self.vars["?"] = str(p.returncode)
                return o
            return []
        elif gr.is_("glob"):
            return [gr]
        elif gr.is_("expand"):
            return [gr]
        elif gr.is_("word") or gr.is_("word2") or gr.is_("words2"):
            s = []
            for c in gr.children:
                #s += self.eval(c)
                cat(s, self.eval(c))
            return s #"".join(s)
        elif gr.is_("raw_word"):
            return [unesc(gr.substring())]
        elif gr.is_("math"):
            ms = gr.substring()
            ms = ms[3:-2]
            return str(eval(ms)).strip()
        elif gr.is_("func"):
            assert gr.children[0].is_("ident")
            ident = gr.children[0].substring()
            self.funcs[ident] = gr.children[1:]
        elif gr.is_("subproc"):
            result = ""
            o,e = self.output, self.error
            for c in gr.children:
                save = self.stdout
                self.stdout = PIPE
                self.output, self.error = "", ""
                result = self.eval(c)
                self.stdout = save
            self.output, self.error = o, e
            return spaceout(re.split(r'\s+',result.strip()))
        elif gr.is_("dquote"):
            s = ""
            for c in gr.children:
                r = self.eval(c)
                if type(r) == str:
                    s += r
                else:
                    assert type(r) == list, "t=%s r=%s %s" % (type(r), r, c.dump())
                    for k in r:
                        if isinstance(k,Space):
                            s += ' '
                        else:
                            s += k
            assert type(s) == str
            #here("s=",s)
            return s
        elif gr.is_("dchar"):
            return gr.substring()
        elif gr.is_("dlit"):
            s = gr.substring()
            if s == "\\n":
                return "\n"
            elif s == "\\r":
                return "\r"
            else:
                return s[1]
        elif gr.is_("var"):
            varname = gr.has(0,"w").substring()
            if varname in os.environ:
                v = spaceout(re.split(r'\s+', os.environ[varname]))
            elif varname in self.vars:
                v = spaceout(re.split(r'\s+', self.vars[varname]))
            else:
                v = None

            if v is None and gr.has(1,"unset"):
                v = self.eval(gr.children[2])
            elif v is None and gr.has(1,"unset_raw"):
                v = self.eval(gr.children[2])
            rmb = gr.has(1,"rm_back")
            if rmb:
                back = gr.children[2].substring()
                if len(v) > 0 and v[0].endswith(back):
                    v[0] = v[0][:-len(back)]

            if v is None:
                return ""
            else:
                return v
        elif gr.has(0,"fd_from") and gr.has(1,"fd_to"):
            fd_from = gr.children[0].substring()
            fd_to = gr.children[1].substring()
            if fd_from == "2" and fd_to == "&1":
                self.stderr = self.stdout
                return None
            elif fd_from == "1" and fd_to == "&2":
                self.stdout = self.stderr
                return None
            else:
                raise Exception(f"{fd_from} and {fd_to}")
        else:
            here(gr.dump())
            raise Exception(gr.substring())
            return [gr.substring()]

    def run_text(self,txt):
        print(colored("="*50,"yellow"))
        txt = self.txt + txt
        if txt.endswith("\\\n"):
            self.txt = txt
            return "CONTNUE"

        print(colored(txt,"cyan"))
        m = Matcher(pp, "whole_cmd", txt)
        if m.matches():
            # here(m.gr.dump())
            if verbose:
                print(colored(txt,"cyan"))
                print(colored(m.gr.dump(),"magenta"))
            end = m.gr.end
            txt2 = txt[end:]
            if len(txt2)>0:
                s.run_text(txt2)
            self.txt = ''
            self.lines += [m.gr]
            self.eval(m.gr)
            return "EVAL"
        elif m.maxTextPos == len(txt):
            self.txt = txt
            print()
            m.showError()
            print("continue...")
            return "CONTNUE"
        else:
            self.txt = ''
            print()
            m.showError()
            #m.showError(sys.stderr)
            here("done")
            exit(0)
            return "SYNTAX"

s = shell()

def test(cmd):
    varsave = {}
    for k in s.vars:
        varsave[k] = s.vars[k]
    try:
        print(colored("TEST","blue"))
        s.stdout = PIPE
        s.output = ""
        s.run_text(cmd)
        p = Popen(["bash","-c",cmd],universal_newlines=True,stdout=PIPE,stderr=PIPE)
        o, e = p.communicate()
        print("   bash: (",colored(re.sub(r'\n',r'\\n',o),"green"),")",sep='')
        print("piebash: (",colored(re.sub(r'\n',r'\\n',s.output),"magenta"),")",sep='')
        assert o == s.output
        assert e == s.error, f"<{e}> != <{s.error}>"
    finally:
        s.vars = {}
        for k in varsave:
            s.vars[k] = varsave[k]

test("echo hi; for a in 1 2 3; do echo $a; done")
test("echo hi; for a in 1 2 3; do echo x; for b in 4 5 6; do echo $a$b; done; done")
test("if [ 1 = 0 ]; then echo a; echo b; echo c; else echo d; echo e; echo f; fi")
test("if [ 1 = 0 ]; then echo true; else echo false; fi")
test("if [ 0 = 0 ]; then echo true; else if [ 1 = 0 ]; then echo false; fi; fi")
test("if [ 0 = 1 ]; then echo true; else if [ 1 = 0 ]; then echo false; fi; fi")
test("if [ 1 = 0 ]; then echo true; else echo false; fi")
test("if [ 1 \\> 0 ]; then echo true; else echo false; fi")
test("if [ 1 \\< 0 ]; then echo true; else echo false; fi")
test("if [ 1 != 0 ]; then echo true; else echo false; fi")
test("echo {a,b{c,d}}{e,f}")
s.run_text('if [ a = b ]; then echo $HOME; fi;')
#s.run_text('''
#for x in 1 2 3
#do
#  echo $x
#done
#'''.strip()+"\n")
test('echo ${b-date}')
test('echo aaa ${b:-date}')
test('echo aaa ${b:-$(date +%m-%d-%Y)"y"$q}')
test('echo ${b:-$(date +%m-%d-%Y)"y"$q}"x"')
os.environ["date"]="foo.cpp"
s.vars["date"]="foo.cpp"
test('echo ${date%.cpp}')
test('''echo hello 2>&1''')

s.run_text('echo "hello ')
s.run_text('world"')
print("GOT WORLD")
s.run_text('echo hello \\\n')
s.run_text('world-$(date)')
s.run_text('echo "Date $(date) $((22+10*2))"')
s.run_text('''echo a

echo b''')
s.run_text('''
function foo() {
    echo this is foo
}

foo''')
test('python3 ./x.py a b c')
os.environ['q'] = "a b c"
test('python3 ./x.py $q')
test('echo $(seq 1 10)')
s.run_text('ls x*')
s.run_text('ls a*')
test('ls x.{py,sh}')
test('''
function zap() {
  echo x.{py,sh}
}
zap
''')
test("echo {a,b{c,d}}")
test("echo x*")
test("./a.sh")
test("./a.sh && ./b.sh")
test("./a.sh || ./b.sh")
test("./b.sh && ./a.sh")
test("./b.sh || ./a.sh")
here("All tests passed")
