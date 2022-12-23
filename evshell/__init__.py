#!/usr/bin/env python3 
# Purpose of Everglades Shell
# (1) Security for Science Gateways
# (2) Supercharge Jupyter: Allow in-process calling of bash from Python, save ENVIRON variables, etc.
# (3) Call python functions from bash or bash functions from python
from pwd import getpwnam, getpwuid
from piraha import parse_peg_src, Matcher, Group, set_trace
from subprocess import Popen, PIPE, STDOUT
from .pipe_threads import PipeThread, get_lastpid, get_running, pwait
import os
import sys
import re
import io
from traceback import print_exc
from .here import here
from shutil import which
from datetime import datetime
from .tmpfile import tmpfile
from .version import __version__
from .completer import Completer
from time import time
import json

def prepJson(arg):
    if arg is None:
        return []
    t = type(arg)
    if t == dict:
        narg = {}
        for k in arg:
            narg[k] = prepJson(arg[k])
    elif t == list:
        narg = []
        for k in range(len(arg)):
            narg += [prepJson(arg[k])]
    elif t == set:
        narg = prepJson(list(arg))
    elif t in [int,float,bool]:
        narg = arg
    else:
        narg = str(arg)
    return narg


def _serGroup(g):
    children = [_serGroup(child) for child in g.children]
    return {"start":g.start, "end":g.end, "name":g.name, "children":children}

def serGroup(g):
    """
    Serialize a Piraha group data structure (parse tree).
    """
    return {"text":g.text, "root":_serGroup(g)}

def _deserGroup(data, text):
    g = Group(data["name"], text, data["start"], data["end"])
    g.children = [_deserGroup(c,text) for c in data["children"]]
    return g

def deserGroup(data):
    return _deserGroup(data["root"],data["text"])


# The way exit works is to raise SystemExit,
# which may be caught. When we want to exit our
# simulated shell, we should raise ShellExit
# instead.
class ShellExit(Exception):
    def __init__(self, rc):
        self.rc = rc

# This exception is thrown for an access
# violation.
class ShellAccess(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return "SHELL ACCESS: "+self.msg

def shell_exit(rc):
    raise ShellExit(rc)

import io
home = os.environ["HOME"]

if sys.argv[0] == "-c":
    my_shell = sys.modules[__name__].__file__
else:
    my_shell = os.path.realpath(sys.argv[0])

Never = object()

class ContinueException(Exception):
    def __init__(self,message):
        super().__init__(message)
        self.message = message

class TFN:
    """
    This class has values of True, False, and Never.
    """

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
        """
        Toggling turns True to False, False to True,
        and leaves Never alone.
        """
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
    """
    Remove one level of escapes (backslashes) from a string.
    """
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

from colored import colored, is_jupyter

grammar = r"""
skipper=\b([ \t]|\\\n|\#.*)*
s=\b([ \t\n]|\\\n|\#.*)*
raw_word=(\\.|[^\\"'\t \n\$\#&\|;{}`()<>?*,])+
raw_word2=(\\.|[^()[\]{}]|\[{raw_word2}\]|\({raw_word2}\)|\{{raw_word2}\})*
dchar=[^"$\\]
dlit=\\.
dquote="({dlit}|{dchar}|{var}|{math}|{subproc}|{bquote})*"
bquote=`(\\.|[^`$]|{var}|{math}|{subproc})*`
squote='(\\.|[^'])*'
unset=:-
unsetp=:\+
unset_raw=-
rm_front=\#\#?
rm_back=%%?
def=:-
wchar=[@?$!-]
w=[a-zA-Z0-9_]+
var=\$({wchar}|{w}|\{(({w}|{wchar})({unset}{words2}|{unsetp}{raw_word2}|{unset_raw}{raw_word}|{rm_front}{word2}|{rm_back}{word2}|{def}{word2}?|))\})
func=function {ident} \( \) \{( {cmd})* \}({redir}|[ \t])*\n

worditem=({glob}|{redir}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote})
worditemex=({glob}|{redir}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote}|{expand})
word={expand}{-worditemex}+|{-worditem}{-worditemex}*

word2=({glob}|{redir}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote})
words2={word2}+

ending=(&&?|\|[\|&]?|;(?!;)|\n|$)
esac=esac
casepattern=[^ \t\)]*\)
case=case {word} in({-s}{casepattern}|)
case2=;;{-s}({esac}|{casepattern}|)

fd_from=[0-9]+
fd_to=&[0-9]*
ltgt=(<<<|<<|<|>>|>)
redir=({fd_from}|){ltgt}( {fd_to}| {word})
ident=[a-zA-Z0-9][a-zA-Z0-9_]*
mathchar=(\)[^)]|[^)])
math=\$\(\(({var}|{mathchar})*\)\)
subproc=\$\(( {cmd})* \)
cmd={subshell}|(( {word})+( {ending}|)|{ending})
glob=\?|\*|\[.-.\]
expand=[\{,\}]
subshell=\(( {cmd})* \)
whole_cmd=^( ({func}|{case}|{case2}|{cmd}))* $
"""
pp,_ = parse_peg_src(grammar)

class For:
    """
    A data structure used to keep track of
    the information needed to implement
    for loops.
    """
    def __init__(self,variable,values):
        self.variable = variable
        self.values = values
        self.index = 0
        self.docmd = -1
        self.donecmd = -1
    def __repr__(self):
        return f"For({self.variable},{self.values},{self.docmd},{self.donecmd})"

class Space:
    """
    This class represents a literal space
    """
    def __repr__(self):
        return " "

def spaceout(a):
    """
    Put a space between each member of a list
    """
    b = []
    for i in range(len(a)):
        if i > 0:
            b += [Space()]
        b += [a[i]]
    return b

def deglob(a):
    """
    Process a file glob
    """
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

class Expando:
    """
    Bookkeeping class used by expandCurly.
    """
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
    """
    Used by deglob() in processing globs in filenames.
    """
    while True:
        if fn is None:
            result = []
            if pat[0] == ('/',):
                for d in os.listdir(fn):
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
            # g? is a glob ? pattern
            i1 += 1
            i2 += 1
        elif pat[i2][0] == 'g*':
            # g* is a glob * pattern
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
                except Exception as ee:
                    pass
        return s
    elif type(s) == list and len(s)>0:
        return [expandtilde(s[0])] + s[1:]
    else:
        return s

def printf(*args):
    pyargs = []
    for arg in args[1:]:
        try:
            pyargs += [int(arg)]
            continue
        except:
            pass
        try:
            pyargs += [float(arg)]
            continue
        except:
            pass
        pyargs += [arg]
    print(args[0] % tuple(pyargs))

class shell:
    
    def __init__(self,args=sys.argv, shell_name=my_shell, stdout=None, stderr=None, stdin=None):
        self.shell_name = shell_name
        self.args = args
        self.scriptname = "bash"
        self.txt = ""
        self.wait_for = None
        self.flags = {}
        self.vars = {
            "?":"0",
            "PWD":os.path.realpath(os.getcwd()),
            "*":" ".join(self.args[1:]),
            "SHELL":os.path.realpath(shell_name),
            "PYTHON":sys.executable,
            "EVSHELL":__version__}
        pwdata = getpwuid(os.getuid())
        self.vars["USER"] = pwdata.pw_name
        self.vars["LOGNAME"] = pwdata.pw_name
        self.vars["HOME"] = pwdata.pw_dir

        # Command line args
        self.vars["@"] = " ".join(args)
        for vnum in range(len(args)):
            self.vars[str(vnum)] = args[vnum]

        self.exports = {}
        for var in os.environ:
            if var not in self.vars:
                self.vars[var] = os.environ[var]
            self.exports[var] = self.vars[var]
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.lines = []
        self.cmds = []
        self.stack = []
        self.for_loops = []
        self.case_stack = []
        self.funcs = {}
        self.pyfuncs = { "printf" : printf}
        self.save_in = []
        self.save_out = []
        self.last_ending = None
        self.curr_ending = None
        self.last_pipe = None
        self.recursion = 0
        self.max_recursion_depth = 2000
        log_file_dir = os.path.join(self.vars["HOME"],".evshell-logs")
        os.makedirs(log_file_dir, exist_ok = True)
        log_file = os.path.join(log_file_dir, f"log-{os.getpid()}.jtxt")
        self.log_fd = open(log_file,"w")
        self.log(msg="starting shell")

    def serialize(self, fd):
        print(json.dumps(self.vars),file=fd)
        print(json.dumps(self.exports),file=fd)
        print(json.dumps({
            "max_recursion_depth":self.max_recursion_depth,
            "cwd":os.getcwd(),
        }),file=fd)

        # Serialize shell functions
        funcser = {}
        for fname in self.funcs:
            funcser[fname] = json.dumps([serGroup(x) for x in self.funcs[fname]])
        print(json.dumps(funcser),file=fd)

        import inspect
        funcs = {}
        for func in self.pyfuncs:
            funcs[func] = inspect.getsource(self.pyfuncs[func])
        print(json.dumps(funcs),file=fd)

    def deserialize(self, fd):
        self.vars = json.loads(fd.readline())
        self.exports = json.loads(fd.readline())
        data = json.loads(fd.readline())
        self.max_recursion_depth = data["max_recursion_depth"]
        os.chdir(data["cwd"])

        # Deserialize shell functions
        funcser = json.loads(fd.readline())
        self.funcs = {}
        for fname in funcser:
            self.funcs[fname] = [deserGroup(x) for x in json.loads(funcser[fname])]

        funcs = json.loads(fd.readline())
        for func in funcs:
            eval(func)
            self.pyfuncs[func] = globals()[func]

    def err(self, e):
        print(colored(str(e),"red"),file=self.stderr)

    def open_file(self, fname, rwa, line):
        sout = None
        try:
            sout = open(fname, rwa)
            self.log(open=fname,rwa=rwa)
        except PermissionError as pe:
            self.log(exc=pe,open=fname,rwa=rwa)
            print(self.scriptname,":",
                " line ", line, ": ", fname,": ",
                pe.strerror.strip(),
                sep="", file=self.stderr)
        except OSError as e:
            self.log(exc=pe,open=fname,rwa=rwa)
            self.err(e)
        if sout is None:
            return open("/dev/null", rwa)
        if self.stderr is not None:
            self.stderr.flush()
        return sout
    
    def env_is_bound(self):
        return os.environ is self.exports

    def bind_to_env(self):
        assert self.exports is not os.environ
        for v in os.environ:
            self.vars[v] = os.environ[v]
        self.exports = os.environ

    def unbind_from_env(self):
        assert self.exports is os.environ
        new_exports = {}
        for v in os.environ:
            new_exports[v] = self.vars[v] =  os.environ[v]
        self.exports = new_exports

    def log_flush(self):
        self.log_fd.flush()

    def log_exc(self,e):
        print_exc()
        self.log_flush()
        self.log(exc=e)
        self.log_flush()

    def log(self,**kwargs):
        self.log_flush()
        args = prepJson(kwargs)
        if "time" not in args:
            args["time"] = time()
        args["script"] = self.scriptname
        print(json.dumps(args),file=self.log_fd)
        self.log_flush()

    def unset_var(self,vname):
        val = self.allow_set_var(vname, None)
        if val == None:
            unset = False
            try:
                del self.vars[vname]
                unset = True
            except KeyError as ke:
                pass
            try:
                del self.exports[vname]
                unset = True
            except KeyError as ke:
                pass
            self.log(unset=vname)

    def get_var(self,vname):
        if vname in self.exports:
            return self.exports[vname]
        else:
            return self.vars.get(vname,"")

    def set_var(self,vname,value):
        self.log(setvar=vname,value=value)
        assert vname != "2"
        value = self.allow_set_var(vname, value)
        self.vars[vname] = value
        if self.flags.get("a",False):
            self.exports[vname] = value

    def allow_cd(self, cd_dir):
        return cd_dir

    def allow_cmd(self, args):
        return args

    def allow_read(self, fname):
        return fname

    def allow_write(self, fname):
        return fname

    def allow_append(self, fname):
        return fname

    def allow_set_var(self,var,val):
        return val

    def allow_access_var(self,var):
        pass

    def lookup_var(self,gr):
        """
        lookup_var() converts a Piraha.Group to a list of strings.
        The output needs to be a list so that code like this runs
        correctly:
        ```
        a="1 2 3"
        for i in $a; do echo $i; done
        ```
        """
        varname = gr.has(0).substring()
        if varname == "$":
            return [str(os.getpid())]
        elif varname == "!":
            return [str(get_lastpid())]
        self.allow_access_var(varname)
        if varname in self.vars:
            v = spaceout(re.split(r'\s+', self.get_var(varname)))
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
            return [""]
        else:
            return v

    def evaltest(self, args, index=0):
        """
        Process calls to `test` or `if`, optimizing in some cases.
        """
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
        """
        k: An input of type Piraha.Group.
        return value: a list of strings
        """
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
            # here("wc:",gr.dump())
            pipes = None
            result = []
            ending = None
            my_ending = None
            for c in gr.children:
                if c.has(0,"ending"):
                    continue
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
    
            if args == ['']:
                return args
            return self.evalargs(args, redir, skip, xending, index, gr)

        elif gr.is_("glob"):
            return [gr]
        elif gr.is_("expand"):
            return [gr]
        elif gr.is_("word") or gr.is_("word2") or gr.is_("words2"):
            s = []
            for c in gr.children:
                cat(s, self.eval(c))
            if gr.has(-1,"eword"):
                here("eword found:",gr.dump())
            return s 
        elif gr.is_("raw_word"):
            return [unesc(gr.substring())]
        elif gr.is_("math"):
            mtxt = ''
            for gc in gr.children:
                if gc.is_("mathchar"):
                    mtxt += gc.substring()
                else:
                    mtxt += self.lookup_var(gc)[0]
            try:
                return str(eval(mtxt)).strip()
            except Exception as ee:
                return f"ERROR({mtxt})"
        elif gr.is_("func"):
            assert gr.children[0].is_("ident")
            ident = gr.children[0].substring()
            self.funcs[ident] = gr.children[1:]
        elif gr.is_("subproc"):
            out_pipe = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(1)
                os.dup(out_pipe[1])
                self.stdout = 1
                os.close(out_pipe[0])
                os.close(out_pipe[1])
                for c in gr.children:
                    self.eval(c)
                os._exit(int(self.vars["?"]))
            assert pid != 0
            os.close(out_pipe[1])
            result = os.read(out_pipe[0],10000).decode()
            os.close(out_pipe[0])
            rc=os.waitpid(pid,0)
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
        elif gr.is_("subshell"):
            out_pipe = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(1)
                self.stdout = 1
                os.dup(out_pipe[1])
                os.close(out_pipe[0])
                os.close(out_pipe[1])
                for gc in gr.children:
                    self.eval(gc)
                code = int(self.vars["?"])
                os._exit(int(self.vars["?"]))
            os.close(out_pipe[1])
            out = os.read(out_pipe[0],10000).decode()
            os.close(out_pipe[0])
            if type(self.stdout) == int:
                os.write(self.stdout, out.encode())
            else:
                self.stdout.write(out)
            rc=os.waitpid(pid,0)
            self.vars["?"] = str(rc[1])
            self.log(msg="end subshell",rc=self.vars["?"])
            if self.vars["?"] != "0" and self.flags.get("e",False):
                shell_exit(int(self.vars["?"]))
            return []
        else:
            here(gr.dump())
            raise Exception(gr.getPatternName()+": "+gr.substring())
            return [gr.substring()]

    def do_redir(self, redir, sout, serr, sin):
        out_is_error = False
        fd_from = None
        rn = 0
        if redir.has(0,"fd_from"):
            fd_from = redir.children[0].substring()
            rn += 1
        if redir.has(rn,"ltgt"):
            ltgt = redir.group(rn).substring()
            if redir.has(rn+1,"word"):
                line = redir.linenum()
                fname = expandtilde(redir.group(rn+1).substring())
                if ltgt == "<":
                    fname = self.allow_read(fname)
                    sin = self.open_file(fname, "r", line)
                elif ltgt == "<<":
                    # fname is not a file name here,
                    # but a symbol such as EOF
                    here()
                    self.wait_for = fname
                elif ltgt == ">":
                    fname = self.allow_write(fname)
                    if fd_from is None or fd_from == "1":
                        sout = self.open_file(fname,"w", line)
                    elif fd_from == "2":
                        serr = self.open_file(fname,"w", line)
                    else:
                        assert False, redir.dump()
                elif ltgt == ">>":
                    fname = self.allow_append(fname)
                    if fd_from is None or fd_from == "1":
                        sout = self.open_file(fname, "a", line)
                    elif fd_from == "2":
                        serr = self.open_file(fname, "a", line)
                    else:
                        assert False, redir.dump()
                else:
                    assert False, redir.dump()
            elif redir.has(rn+1,"fd_to"):
                here()
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
        return sout, serr, sin, out_is_error

    def update_env(self):
        for name in self.exports:
            os.environ[name] = self.vars[name]

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
                            self.set_var(varname,value)
                            self.exports[varname] = self.vars[varname]
                        elif a in self.vars:
                            self.exports[a] = self.vars[a]
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
                    if len(args) == 0:
                        return

                if args[0] == "if":
                    testresult = None
                    if len(self.stack) > 0 and not self.stack[-1][1]:
                        # initialize the if stack with never.
                        # Until a conditional is evaluated,
                        # it is not true.
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
                except Exception as ee:
                    rc = 1
                self.vars["?"] = str(rc)
                shell_exit(int(self.vars["?"]))
                return []
            if args[0] == "wait":
                result = None
                p = pwait(None)
                print("pid:",p.getpid(),"cmd:",p.args[0])
                self.log(msg="end wait",pid=p.getpid(),rc=p.returncode)
                return []
            if args[0] == "cd":
                if len(args) == 1:
                    cd_dir = home
                else:
                    cd_dir = args[1]
                cd_dir = self.allow_cd(cd_dir)
                os.chdir(cd_dir)
                self.log(chdir=cd_dir)
                self.vars["PWD"] = os.getcwd()
                return

            if args[0] in self.funcs:
                # Invoke a function
                try:
                    save = {}
                    for vnum in range(1,1000): #self.max_args):
                        vname = str(vnum)
                        if vname in self.vars:
                            save[vname] = self.vars[vname]
                        else:
                            break
                    save["@"] = self.vars["@"]
                    for vnum in range(1,len(args)):
                        vname = str(vnum)
                        self.vars[vname] = args[vnum]
                    self.vars["@"] = " ".join(args[1:])
                    for c in self.funcs[args[0]]:
                        if c.is_("redir"):
                            continue
                        self.recursion += 1
                        try:
                            assert self.recursion < self.max_recursion_depth, f"Max recursion depth {self.max_recursion_depth} exceeded"
                            self.eval(c)
                        finally:
                            self.recursion -= 1
                finally:
                    for vnum in range(1,1000): #self.max_args):
                        vname = str(vnum)
                        if vname in self.vars:
                            save[vname] = self.vars[vname]
                        else:
                            break
                    for k in save:
                        self.vars[k] = save[k]
                return []
            elif args[0] in self.pyfuncs:
                # Invoke a python function
                try:
                    return self.pyfuncs[args[0]](*args[1:])
                except Exception as e:
                    print(colored(f"'{args[0]}' threw '{type(e)}: {e}'","red"))
                    return []
            elif args[0] == "unset":
                for a in args[1:]:
                    self.unset_var(a)
                return
            elif args[0] == "set":
                for a in args[1:]:
                    if a[0] == '-':
                        for c in a[1:]:
                            self.flags[c] = True
                    elif a[0] == '+':
                        for c in a[1:]:
                            self.flags[c] = False
                return
            elif args[0] in ["source", "."]:
                assert len(args)==2
                with self.open_file(args[1],"r",gr.linenum()) as fd:
                    self.run_text(fd.read())
                    return
            elif args[0] not in ["if","then","else","fi","for","done","case","esac"]:
                sout = self.stdout
                serr = self.stderr
                sin = self.stdin
                if not os.path.exists(args[0]):
                    args0 = which(args[0])
                    if args0 is not None:
                        args0 = os.path.abspath(args0)
                        args[0] = args0
                #if args[0] in ["/usr/bin/bash","/bin/bash","/usr/bin/sh","/bin/sh"]:
                #    args = [my_shell] + args[1:]
                # We don't have a way to tell Popen we want both
                # streams to go to stderr, so we add this flag
                # and swap the output and error output after the
                # command is run
                out_is_error = False
                if redir is not None:
                    sout,serr,sin,out_is_error = self.do_redir(redir,sout,serr,sin)
                if len(args) == 0 or args[0] is None:
                    return ""
                if os.path.exists(args[0]):
                    if gr is None:
                        gr_line = 0
                    else:
                        gr_line = gr.linenum()
                    with self.open_file(args[0],"r",gr_line) as fd:
                        try:
                            first_line = fd.readline()
                        except UnicodeDecodeError as ude:
                            first_line = ""
                        if first_line.startswith("#!"):
                            args = re.split(r'\s+',first_line[2:].strip()) + args
                if args[0] == 'storeenv':
                    if len(args) != 2:
                        print(f"Usage: storeenv 'name'")
                    else:
                        envfile = os.path.join(home, args[1])
                        with open(envfile, "w") as fd:
                            self.serialize(fd)
                            print(f"Env stored to {envfile}")
                    return []
                elif args[0] == 'loadenv':
                    if len(args) != 2:
                        print(f"Usage: loadenv 'name'")
                    else:
                        envfile = os.path.join(home, args[1])
                        with open(envfile, "r") as fd:
                            self.deserialize(fd)
                            print(f"Env loaded from {envfile}")
                    return []
                elif len(args) == 4 and args[0] == 'pyfrom' and args[2] == 'import':
                    args = self.allow_cmd(args)
                    modname = args[1]
                    funcname = args[3]
                    module = __import__(modname)
                    self.pyfuncs[funcname] = getattr(module,funcname)
                    return []
                elif args[0] == 'exec':
                    exec_cmd = which(args[1])
                    args = self.allow_cmd(args[1:])
                    if exec_cmd is not None:
                        os.execve(exec_cmd,args,self.exports)
                if not os.path.exists(args[0]):
                    if gr is None:
                        fno = 0
                    else:
                        fno = gr.linenum()
                    print(f"{self.scriptname}: line {fno}: {args[0]}: command not found",file=self.stderr)
                    self.log(args=args,msg="command not found",line=fno)
                    self.vars["?"] = 1
                    if self.flags.get("e",False):
                        shell_exit(1)
                    return ""
                args = self.allow_cmd(args)
                env = {}
                if self.flags.get("x",False):
                    self.stderr.write("+ "+" ".join(args)+"\n")
                for e in self.exports:
                    env[e] = self.exports[e]
                try:
                    tstart = time()
                    p = PipeThread(args, stdin=sin, stdout=sout, stderr=serr, universal_newlines=True, env=env)
                    self.log(msg="start",pid=p.getpid(), args=args, time=tstart)
                except OSError as e:
                    args = ["/bin/sh"]+args
                    p = PipeThread(args, stdin=sin, stdout=sout, stderr=serr, universal_newlines=True, env=env)
                    self.log(msg="start",pid=p.getpid(), args=args)
                if self.curr_ending == "&":
                    p.background()
                    p.start()
                elif xending == "|":
                    p.setDaemon(True)
                    p.start()
                    return []
                else:
                    p.start()
                    p.communicate()
                    self.vars["?"] = str(p.returncode)
                    self.log(msg="end", rc=self.vars["?"], pid=p.getpid())
                    if self.vars["?"] != "0" and self.flags.get("e",False):
                        shell_exit(int(self.vars["?"]))
                    return None
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

    def run_file(self,fname):
        with open(fname, "r") as fd:
            self.scriptname = fname
            return self.run_text(fd.read())

    def run_text(self,txt):
        try:
            s0 = self.stdin
            s1 = self.stdout
            s2 = self.stderr
            if s1 is None:
                if is_jupyter:
                    self.stdout = tmpfile()
                else:
                    self.stdout = sys.stdout
            if s2 is None:
                if is_jupyter:
                    self.stderr = tmpfile()
                else:
                    self.stderr = sys.stderr
            return self.run_text_(txt)
        finally:
            if s1 is None and is_jupyter:
                print(self.stdout.getvalue(),end='')
            if s2 is None and is_jupyter:
                print(colored(self.stderr.getvalue(),"red"),end='')
            self.stdin = s0
            self.stdout = s1
            self.stderr = s2

    def run_text_(self,txt):
        #here(colored("="*50,"yellow"))
        nchars=50
        if len(txt) < nchars:
            self.log(txt=txt,full=True)
        else:
            self.log(txt=txt[0:nchars]+"...",full=False)
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
            self.log(msg="CONTINUE")
            return "CONTNUE"
        else:
            self.txt = ''
            m.showError()
            here("done")
            self.log(msg="SYNTAX")
            #m.showError(self.log_fd)
            return "SYNTAX"

def interactive(shell):
    try:
        import readline
        c = Completer()
        readline.set_completer(c.complete)
        readline.parse_and_bind("tab: complete")
    except Exception as ee:
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
            msg = "EVAL"
            shell.txt = ""
        except EOFError as ee:
            return shell.vars["?"]

def run_interactive(s):
    try:
        rc = interactive(s)
        s.log(msg="session ended normally",rc=rc)
    except ShellAccess as sa:
        s.err(sa) #,s.stderr)
        rc = -1
        s.log(msg="session ended with access error",rc=rc)
    except ShellExit as se:
        rc = se.rc
        s.log(msg="session ended normally",rc=rc)
        exit(rc)
    except Exception as ee:
        rc = 1
        s.log(msg="session ended with exception",rc=rc,exc=ee)
        s.log_exc(ee)
    exit(rc)

def run_shell(s):
    args = s.args
    ssh_cmd = os.environ.get("SSH_ORIGINAL_COMMAND",None)
    if ssh_cmd is not None:
        try:
            rc = s.run_text(ssh_cmd)
            s.log(rc=rc)
        except Exception as ee:
            s.log_exc(ee)
    elif os.path.realpath(s.shell_name) != os.path.realpath(s.args[0]):
        s.scriptname  = s.args[0]
        with s.open_file(s.args[0],"r",1) as fd:
            rc = s.run_text(fd.read())
            s.log(rc=rc)
    else:
        found = False
        for n in range(1,len(args)):
            f = args[n]
            if f == "-c":
                n += 1
                s.run_text(args[n])
                found = True
            elif os.path.exists(f):
                with s.open_file(f,"r",1) as fd:
                    try:
                        found = True
                        rc = s.run_text(fd.read())
                        s.log(rc=rc)
                        assert rc == "EVAL", f"rc={rc}"
                    except ShellAccess as sa:
                        rc = -1
                        s.err(sa)
                        exit(rc)
                    except ShellExit as se:
                        rc = se.rc
                        exit(rc)
                    except Exception as ee:
                        s.log_exc(ee)
        if not found:
            run_interactive(s)

def main():
    if len(sys.argv)>1 and os.access(sys.argv[0], os.R_OK):
        sh = my_shell
        args = sys.argv[1:]
    else:
        sh = sys.argv[0]
        args = sys.argv
    s = shell(args=args, shell_name=sh)
    args = sys.argv
    run_shell(s)

if __name__ == "__main__":
    main()
