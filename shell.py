#!/usr/bin/env python3 
from Piraha import parse_peg_src, Matcher
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
raw_word=[^"'\t \n\$\#&\|;{}`()<>]+
dchar=[^"$\\]
dlit=\\.
dquote="({dlit}|{dchar}|{var}|{math}|{subproc}|{bquote})*"
bquote=`(\\.|[^`$]|{var}|{math}|{subproc})*`
squote='(\\.|[^'])*'
unset=:-
unset_raw=-
rm_front=\#\#?
rm_back=%%?
var=\$([A-Za-z0-9_]+|\{([a-zA-Z0-9_]+({unset}{word}|{unset_raw}{raw_word}|{rm_front}{word}|{rm_back}{word}|))\})
func=function {ident} \( \) \{( {cmd})* \}
word=({redir}|{ml}|{var}|{math}|{subproc}|{raw_word}|{squote}|{dquote}|{bquote})+
ending=(&&?|\|[\|&]?|;|\n|$)
fd_from=[0-9]+
fd_to=&[0-9]+
redir=({fd_from}|)>({fd_to}|)
ident=[a-zA-Z0-9][a-zA-Z0-9_]*
ml=<< {ident}
math=\$\(\((\)[^)]|[^)])*\)\)
subproc=\$\(( {cmd})* \)
cmd=(( {word})+( {ending}|)|{ending})
whole_cmd=( {func}|{cmd})* $
"""
pp,_ = parse_peg_src(grammar)

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
    
    def __init__(self):
        self.txt = ""
        self.vars = {"?":"0", "*":" ".join(sys.argv[2:])}
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        self.if_stack = []
        self.funcs = {}

    def eval(self, gr):
        r = self.eval_(gr)
        if r is None:
            r = []
        assert type(r) in [list, str], gr.dump()+" "+repr(type(r))+" r="+repr(r)
        return r

    def eval_(self, gr):
        if gr.is_("whole_cmd"):
            result = []
            for c in gr.children:
                result = self.eval(c)
            return result
        elif gr.is_("cmd"):
            args = []
            for k in gr.children:
                if not k.is_("ending"):
                    ek = self.eval(k)
                    #here(ek)
                    #cat(args, ek)
                    if type(ek) == str:
                        args += [ek]
                    elif type(ek) == list:
                        args += ek
                    else:
                        assert False
                    #here(args,k.dump())
            if len(args)==0:
                return []
            if args[0] in self.funcs:
                for c in self.funcs[args[0]]:
                    self.eval(c)
                return []
            elif args[0] not in ["if","then","else","fi","for","do","done"]:
                sout = self.stdout
                serr = self.stderr
                p = Popen(args, stdout=sout, stderr=serr, universal_newlines=True)
                o, e = p.communicate("")
                self.vars["?"] = str(p.returncode)
                return o
            return []
        elif gr.is_("word"):
            s = []
            for c in gr.children:
                #s += self.eval(c)
                cat(s, self.eval(c))
            #here(s)
            return s #"".join(s)
        elif gr.is_("raw_word"):
            return [gr.substring()]
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
            for c in gr.children:
                save = self.stdout
                self.stdout = PIPE
                result = self.eval(c)
                self.stdout = save
            return result.strip()
        elif gr.is_("dquote"):
            s = ""
            for c in gr.children:
                r = self.eval(c)
                assert type(r) == str, "r=%s %s" % (r, c.dump())
                s += r
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
            v = re.split(r'\s+', self.vars.get(gr.substring()[1:], ""))
            #here(v)
            return v
        else:
            here(gr.dump())
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
            #here(m.gr.dump())
            if verbose:
                print(colored(txt,"cyan"))
                print(colored(m.gr.dump(),"magenta"))
            end = m.gr.end
            txt2 = txt[end:]
            if len(txt2)>0:
                s.run_text(txt2)
            self.txt = ''
            self.eval(m.gr)
            return "EVAL"
        elif m.maxTextPos == len(txt):
            self.txt = txt
            return "CONTNUE"
        else:
            self.txt = ''
            m.showError()
            m.showError(sys.stderr)
            return "SYNTAX"

s = shell()
s.run_text('if [ a = b ]; then echo $HOME; fi;')
s.run_text('''
for x in 1 2 3
do
  echo $x
done
'''.strip()+"\n")
s.run_text('echo ${b-date}')
s.run_text('echo ${b:-$(date)"y"$q}"x"')
s.run_text('echo ${date%.cpp}')
s.run_text('''echo hello 2>&1''')

s.run_text('echo "hello ')
s.run_text('world"')
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
s.run_text('python3 ./x.py a b c')
s.vars['q'] = "a b c"
s.run_text('python3 ./x.py $q')
