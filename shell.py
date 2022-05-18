#!/usr/bin/env python3 
# Purpose of Piebash
# (1) Security for Science Gateways
# (2) Supercharge Jupyter: Allow in-process calling of bash from Python, save ENVIRON variables, etc.
# (3) Call python functions from bash or bash functions from python
from pwd import getpwnam, getpwuid
from Piraha import parse_peg_src, Matcher, Group, set_trace
from subprocess import Popen, PIPE, STDOUT
from pipe_threads import PipeThread
import os
import sys
import re
from traceback import print_exc
from here import here
from shutil import which

class ExitShell(Exception):
    def __init__(self, rc):
        self.rc = rc

import io
home = os.environ["HOME"]

my_shell = os.path.realpath(sys.argv[0])

Never = object()

class ContinueException(Exception):
    def __init__(self,message):
        super().__init__(message)
        self.message = message

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

from colored import colored

grammar = r"""
skipper=\b([ \t]|\\\n|\#.*)*
s=\b([ \t\n]|\\\n|\#.*)*
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

ending=(&&?|\|[\|&]?|;(?!;)|\n|$)
esac=esac
casepattern=[^ \t\)]*\)
case=case {word} in({-s}{casepattern}|)
case2=;;{-s}({esac}|{casepattern}|)

fd_from=[0-9]+
fd_to=&[0-9]+
ltgt=(<|>>|>)
redir=({fd_from}|){ltgt}( {fd_to}| {word})
ident=[a-zA-Z0-9][a-zA-Z0-9_]*
ml=<< {ident}
math=\$\(\((\)[^)]|[^)])*\)\)
subproc=\$\(( {cmd})* \)
cmd=(( {word})+( {ending}|)|{ending})
glob=\?|\*|\[.-.\]
expand=[\{,\}]
whole_cmd=^( ({func}|{case}|{case2}|{cmd}))* $
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
            
def expandCurly(a,ex=None,i=0,sub=0):
    """
    The expandCurly method expands out curly braces on the command line,
    e.g. "echo {a,b}{c,d}" should produce "ac ad bc bd".
    """
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

def expandtilde(s):
    if type(s) == str:
        if s.startswith("~/"):
            return home + s[1:]
        if len(s)>0 and s[0] == '~':
            g = re.match(r'^~(\w+)/(.*)', s)
            if g:
                try:
                    pw = getpwnam(g.group(1))
                    if pw is not None:
                        return pw.pw_dir+"/"+g.group(2)
                except:
                    pass
        return s
    elif type(s) == list:
        return [expandtilde(s[0])] + s[1:]
    else:
        return s

class shell:
    
    def __init__(self,stdout = sys.stdout, stderr = sys.stderr, stdin = sys.stdin):
        self.txt = ""
        self.vars = {"?":"0", "PWD":os.path.realpath(os.getcwd()),"*":" ".join(sys.argv[2:]), "SHELL":os.path.realpath(sys.argv[0]), "PYSHELL":"1"}
        pwdata = getpwuid(os.getuid())
        self.vars["USER"] = pwdata.pw_name
        self.vars["LOGNAME"] = pwdata.pw_name
        self.vars["HOME"] = pwdata.pw_dir
        self.exports = set()
        for var in os.environ:
            if var not in self.vars:
                self.vars[var] = os.environ[var]
            self.exports.add(var)
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.lines = []
        self.cmds = []
        self.stack = []
        self.for_loops = []
        self.case_stack = []
        self.funcs = {}
        self.output = ""
        self.error = ""
        self.save_in = []
        self.save_out = []
        self.last_ending = None
        self.curr_ending = None
        self.last_pipe = None
        self.log_fd = open(os.path.join(self.vars["HOME"],"pieshell-log.txt"),"a")
    
    def set_var(self,vname,value):
        if self.allow_set_var(vname, value):
            self.vars[vname] = value

    def allow_cd(self, dname):
        return True

    def allow_cmd(self, args):
        return True

    def allow_read(self, fname):
        return True

    def allow_write(self, fname):
        return True

    def allow_append(self, fname):
        return True

    def allow_set_var(self,var,val):
        return True

    def allow_access_var(self,var):
        return True

    def lookup_var(self,gr):
        varname = gr.has(0,"w").substring()
        if not self.allow_access_var(varname):
            return ""
        if varname in self.vars:
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

    def evaltest(self, args, index=0):
        evalresult = None
        if args[index] == "if":
            index += 1
        if args[index] in ["[[","["]:
            start = args[index]
            index += 1
        else:
            start = None
        if index < len(args) and args[index] in ["-e","-w","r","-x","-f","-d"]:
            op = args[index]
            assert index+1 < len(args), f"No file following opertor '{op}'"
            fname = args[index+1]
            if op == "-x":
                evalresult = os.path.exists(fname) and os.access(fname, os.X_OK)
            elif op == "-r":
                evalresult = os.path.exists(fname) and os.access(fname, os.R_OK)
            elif op == "-w":
                evalresult = os.path.exists(fname) and os.access(fname, os.W_OK)
            elif op == "-e":
                evalresult = os.path.exists(fname)
            elif op == "-d":
                evalresult = os.path.isdir(fname)
            elif op == "-f":
                evalresult = os.path.isfile(fname)
            else:
                assert False
            index += 2
        if index+1 < len(args) and args[index+1] in ["=","!=","\\<","<",">","\\>"]:
            op = args[index+1]
            arg1 = args[index]
            arg2 = args[index+2]
            index += 3
            if op == "=":
                evalresult = arg1 == arg2
            elif op == "!=":
                evalresult = arg1 != arg2
            elif op in ["<","\\<"]:
                evalresult = int(arg1) < int(arg2)
            elif op in [">","\\>"]:
                evalresult = int(arg1) > int(arg2)
            else:
                assert False
        if index < len(args) and args[index] == "]":
            index += 1
            assert start == "[", f"Mismatched braces: '{start}' and '{args[index]}'"
        if index < len(args) and args[index] == "]]":
            index += 1
            assert start == "[[", f"Mismatched braces: '{start}' and '{args[index]}'"
        if start is not None:
            pass #here(args)
        if evalresult is None and args[0] == "if":
            self.evalargs(args[1:], None, False, None, index, None)
            evalresult = self.vars["?"] == "0"
        return evalresult

    def do_case(self, gr):
        word = self.case_stack[-1][0]
        rpat = re.sub(r'\*','.*',gr.substring()[:-1])+'$'
        self.case_stack[-1][1] = re.match(rpat,word)

    def mkargs(self, k):
        args = []
        # Calling eval will cause $(...) etc. to be replaced.
        ek = self.eval(k)
        if k.has(0,"dquote") or k.has(0,"squote"):
            pass
        else:
            # expand ~/ and ~username/. This should
            # not happen to quoted values.
            ek = expandtilde(ek)

        # Now the tricky part. Evaluate {a,b,c} elements of the shell.
        # This can result in multiple arguments being generated.
        exk = expandCurly(ek).build_strs()
        for nek in exk:
            # Evaluate globs
            nek = deglob(nek)
            if type(nek) == str:
                args += [nek]
            elif type(nek) == list:
                args += [""]
                for kk in nek:
                    if isinstance(kk,Space):
                        args += [""]
                    else:
                        args[-1] += kk
            else:
                assert False

        return args

    def eval(self, gr, index=-1,xending=None):
        assert type(gr) != list
        r = self.eval_(gr,index,xending)
        if r is None:
            r = []
        assert type(r) in [list, str], gr.dump()+" "+repr(type(r))+" r="+repr(r)
        return r

    def eval_(self, gr, index=-1, xending=None):
        assert type(gr) != list
        if index == -1 and not gr.is_("whole_cmd"):
            index = len(self.cmds)
            self.cmds += [gr]
        if gr.is_("whole_cmd"):
            #here("wc:",gr.dump())
            pipes = None
            result = []
            ending = None
            my_ending = None
            for c in gr.children:
                result = self.eval(c,xending=my_ending)
            return result
        elif gr.is_("cmd"):
            #here("cmd:",gr.dump())
            args = []
            skip = False

            if self.last_ending == "&&" and self.vars["?"] != "0":
                skip = True
            if self.last_ending == "||" and self.vars["?"] == "0":
                skip = True
            if gr.has(-1,"ending"):
                self.curr_ending = gr.group(-1).substring()
            if self.curr_ending == "|":
                self.curr_pipe = os.pipe()
            else:
                self.curr_pipe = None
            if self.curr_pipe is not None:
                self.save_out += [self.stdout]
                self.stdout = self.curr_pipe[1]
            if self.last_pipe is not None:
                self.save_in += [self.stdin]
                self.stdin = self.last_pipe[0]

            redir = None
            for k in gr.children:
                if k.has(0,"redir"):
                    redir = k.children[0]
                if not k.is_("ending") and not k.has(0,"redir"):
                     args += self.mkargs(k)
    
            return self.evalargs(args, redir, skip, xending, index, gr)

        elif gr.is_("glob"):
            return [gr]
        elif gr.is_("expand"):
            return [gr]
        elif gr.is_("word") or gr.is_("word2") or gr.is_("words2"):
            s = []
            for c in gr.children:
                #s += self.eval(c)
                cat(s, self.eval(c))
            if gr.has(-1,"eword"):
                here("eword found:",gr.dump())
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
        elif gr.is_("squote"):
            return gr.substring()[1:-1]
        elif gr.is_("dlit"):
            s = gr.substring()
            if s == "\\n":
                return "\n"
            elif s == "\\r":
                return "\r"
            else:
                return s[1]
        elif gr.is_("var"):
            return self.lookup_var(gr)
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
        elif gr.is_("case"):
            if gr.has(0,"word"):
                args = self.mkargs(gr.group(0))
                assert len(args)==1
                self.case_stack += [[args[0],False]]
            assert gr.has(-1,"casepattern")
            self.do_case(gr.group(-1))
        elif gr.is_("case2"):
            if gr.has(0,"casepattern"):
                self.do_case(gr.group(0))
            elif gr.has(0,"esac"):
                self.case_stack = self.case_stack[:-1]
            else:
                assert False
        else:
            here(gr.dump())
            raise Exception(gr.substring())
            return [gr.substring()]

    def evalargs(self, args, redir, skip, xending, index, gr):
        try:
            if len(args)>0:
                if args[0] == "do":
                    f = self.for_loops[-1]
                    if f.docmd == -1:
                        f.docmd = index
                    args = args[1:]
                    if len(args) == 0:
                        return

                if args[0] == 'export':
                    for a in args[1:]:
                        g = re.match(r'^(\w+)=(.*)',a)
                        if g:
                            varname = g.group(1)
                            value = g.group(2)
                            #self.vars[varname] = value
                            self.set_var(varname,value)
                            self.exports.add(value)
                        elif a in self.vars:
                            self.exports.add(value)
                    return

                if args[0] == "for":
                    f = For(args[1],args[3:])
                    assert args[2] == "in", "Syntax: for var in ..."
                    self.for_loops += [f]
                    if f.index < len(f.values):
                        #self.vars[f.variable] = f.values[f.index]
                        self.set_var(f.variable, f.values[f.index])
                    return

                if args[0] == "done":
                    f = self.for_loops[-1]
                    assert f.docmd != -1
                    f.donecmd = index
                    if len(f.values) > 1:
                        for ii in range(1,len(f.values)):
                            f.index = ii
                            #self.vars[f.variable] = f.values[f.index]
                            self.set_var(f.variable, f.values[f.index])
                            for cmdnum in range(f.docmd,f.donecmd):
                                self.eval(self.cmds[cmdnum], cmdnum)
                    self.for_loops = self.for_loops[:-1]
                    return

                if args[0] == "then":
                    args = args[1:]
                    if len(args) == 0:
                        return

                elif args[0] == "else":
                    args = args[1:]
                    self.stack[-1][1].toggle()

                if args[0] == "if":
                    testresult = None
                    if len(self.stack) > 0 and not self.stack[-1][1]:
                        self.stack += [("if",TFN(Never))]
                    else:
                        # if [ a = b ] ;
                        #  7 6 5 4 3 2 1
                        # if [ a = b ] 
                        #  6 5 4 3 2 1 
                        testresult = self.evaltest(args)
                        if testresult is None:
                            pass #here(gr.dump())
                        self.stack += [("if",TFN(testresult))]
                elif args[0] == "fi":
                    self.stack = self.stack[:-1]
                g = re.match(r'(\w+)=(.*)', args[0])
                if g:
                    varname = g.group(1)
                    value = g.group(2)
                    #self.vars[varname] = value
                    self.set_var(varname, value)
                    return

            if len(self.stack) > 0:
                skip = not self.stack[-1][1]
            if len(self.case_stack) > 0:
                if not self.case_stack[-1][1]:
                    skip = True
            if len(self.for_loops)>0:
                f = self.for_loops[-1]
                if f.index >= len(f.values):
                    skip = True
            if skip:
                return []
            if len(args)==0:
                return []

            if args[0] == "exit":
                try:
                    rc = int(args[1])
                except:
                    rc = 1
                self.vars["?"] = str(rc)
                return []
            if args[0] == "cd":
                if len(args) == 1:
                    if self.allow_cd(home):
                        os.chdir(home)
                else:
                    if self.allow_cd(args[1]):
                        os.chdir(args[1])
                self.vars["PWD"] = os.getcwd()
                return

            if args[0] in self.funcs:
                for c in self.funcs[args[0]]:
                    self.eval(c)
                return []
            elif args[0] not in ["if","then","else","fi","for","done","case","esac"]:
                sout = self.stdout
                serr = self.stderr
                sin = self.stdin
                if not os.path.exists(args[0]):
                    args[0] = which(args[0])
                if args[0] in ["/usr/bin/bash","/bin/bash","/bin/sh"]:
                    args = [sys.executable,sys.argv[0]] + args[1:]
                # We don't have a way to tell Popen we want both
                # streams to go to stderr, so we add this flag
                # and swap the output and error output after the
                # command is run
                out_is_error = False
                if redir is not None:
                    fd_from = None
                    rn = 0
                    if redir.has(0,"fd_from"):
                        fd_from = redir.children[0].substring()
                        rn += 1
                    if redir.has(rn,"ltgt"):
                        ltgt = redir.group(rn).substring()
                        if redir.has(rn+1,"word"):
                            fname = redir.group(rn+1).substring()
                            if ltgt == "<":
                                if not self.allow_read(fname):
                                    fname = "/dev/null"
                                sin = open(fname, "r")
                            elif ltgt == ">":
                                if not self.allow_write(fname):
                                    pass
                                elif fd_from is None or fd_from == "1":
                                    sout = open(fname, "w")
                                elif fd_from == "2":
                                    serr = open(fname, "w")
                                else:
                                    assert False, redir.dump()
                            elif ltgt == ">>":
                                if not self.allow_append(fname):
                                    pass
                                elif fd_from is None or fd_from == "1":
                                    sout = open(fname, "a")
                                elif fd_from == "2":
                                    serr = open(fname, "a")
                                else:
                                    assert False, redir.dump()
                            else:
                                assert False, redir.dump()
                        elif redir.has(rn+1,"fd_to"):
                            if redir.group(rn+1).substring() == "&2":
                                assert fd_from is None or fd_from=="1"
                                if sout == -1 and serr == -1:
                                    stderr = STDOUT
                                    out_is_error = True
                                elif sout == -1 or serr == -1:
                                    assert False
                                sout = serr
                            elif redir.group(rn+1).substring() == "&1":
                                assert fd_from is None or fd_from=="2"
                                if sout == -1 and serr == -1:
                                    stderr = STDOUT
                                    here()
                                serr = sout
                            else:
                                here(redir.dump())
                                raise Exception()
                        else:
                            here(redir.dump())
                            raise Exception()
                    else:
                        here(redir.dump())
                        raise Exception()
                if os.path.exists(args[0]):
                    try:
                        with open(args[0],"r") as fd:
                            first_line = fd.readline()
                            if first_line.startswith("#!"):
                                args = re.split(r'\s+',first_line[2:].strip()) + args
                    except:
                        pass
                if not os.path.exists(args[0]):
                    print(f"Command '{args[0]}' not found")
                    self.vars["?"] = 1
                    return ""
                if not self.allow_cmd(args):
                    return ""
                self.log_fd.write(str(args)+"\n")
                self.log_fd.flush()
                try:
                    p = PipeThread(args, stdin=sin, stdout=sout, stderr=serr, universal_newlines=True)
                except OSError as e:
                    args = ["/bin/sh"]+args
                    p = PipeThread(args, stdin=sin, stdout=sout, stderr=serr, universal_newlines=True)
                if xending == "|":
                    p.setDaemon(True)
                    p.start()
                    return []
                else:
                    p.start()
                    o, e = p.communicate()
                    if out_is_error:
                        o, e = e, o
                    if type(o) == str:
                        self.output += o
                    if type(e) == str:
                        self.error += e
                    self.vars["?"] = str(p.returncode)
                    return o
            return []
        finally:
            if self.curr_pipe is not None:
                self.stdout = self.save_out[-1]
                self.save_out = self.save_out[:-1]
            if self.last_pipe is not None:
                self.stdin = self.save_in[-1]
                self.save_in = self.save_in[:-1]
            self.last_ending = self.curr_ending
            self.last_pipe = self.curr_pipe

    def run_text(self,txt):
        #here(colored("="*50,"yellow"))
        #here(txt)
        txt = self.txt + txt
        if txt.endswith("\\\n"):
            self.txt = txt
            return "CONTNUE"

        #print(colored(txt,"cyan"))
        m = Matcher(pp, "whole_cmd", txt)
        if m.matches():
            for gr in m.gr.children:
                if gr.is_("case"):
                    if not gr.has(-1,"casepattern"):
                        self.txt = txt+'\n'
                        return "CONTINUE"
                elif gr.is_("case2"):
                    if not gr.has(0):
                        self.txt = txt+'\n'
                        return "CONTINUE"
                else:
                    pass
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
            if len(self.stack) > 0 or len(self.for_loops) > 0:
                return "EVALCONTINUE"
            else:
                return "EVAL"
        elif m.maxTextPos == len(txt):
            self.txt = txt
            #print()
            #m.showError()
            #print("continue...")
            return "CONTNUE"
        else:
            self.txt = ''
            print()
            m.showError()
            #m.showError(sys.stderr)
            here("done")
            exit(0)
            return "SYNTAX"

def interactive(shell):
    try:
        import readline
    except:
        print(colored("Import of readline failed","red"))
    msg = "EVAL"
    while True:
        if msg == "EVAL":
            ps = colored('\U0001f370> ','yellow')
        else:
            ps = colored('\U0001f370? ','cyan')
        sys.stdout.flush()
        try:
            inp = input(ps)
            msg = shell.run_text(inp)
        except KeyboardInterrupt as ke:
            print(colored("Interrupt","red"))
        except EOFError as ee:
            return shell.vars["?"]

if __name__ == "__main__":
    s = shell()
    ssh_cmd = os.environ.get("SSH_ORIGINAL_COMMAND",None)
    if ssh_cmd is not None:
        s.run_text(ssh_cmd)
    elif len(sys.argv) == 1:
        rc = interactive(s)
        exit(rc)
    else:
        for n in range(1,len(sys.argv)):
            f = sys.argv[n]
            if f == "-c":
                n += 1
                s.run_text(sys.argv[n])
            elif os.path.exists(f):
                with open(f,"r") as fd:
                    s.run_text(fd.read())
