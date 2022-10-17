from . import shell, ShellExit, run_shell
import sys, re, os
from subprocess import Popen, PIPE
from .here import here
from .colored import colored
from .tmpfile import tmpfile

s = shell()

os.environ["A"] = "B"
s.bind_to_env()
s.run_text("export A=C")
assert os.environ["A"] == "C"
os.environ["A"] = "D"
save_io = s.stdout
s.stdout = tmpfile()
s.run_text("echo $A")
sv = s.stdout.getvalue()
assert sv.strip() == "D"
s.stdout = save_io

s.unbind_from_env()

def test(cmd,fname=None):
    varsave = {}
    outsave = s.stdout
    errsave = s.stderr
    insave = s.stdin
    flags = s.flags.copy()
    for k in s.vars:
        varsave[k] = s.vars[k]
    try:
        print(colored("TEST","blue"),cmd)

        # First, bash...
        if fname is None:
            pcmd = ["bash","-c",cmd]
        else:
            pcmd = ["bash",fname]
        p = Popen(pcmd,universal_newlines=True,stdout=PIPE,stderr=PIPE)
        o, e = p.communicate()

        # Second, Snake Shell...
        fd1 = tmpfile()
        s.stdout = fd1

        fd2 = tmpfile()
        s.stderr = fd2

        s.stdin = open("/dev/null","r")
        if fname is None:
            s.run_text(cmd)
        else:
            try:
                s2 = shell([fname])
                s2.stdout = fd1
                s2.stderr = fd2
                run_shell(s2)
            except ShellExit as se:
                pass
        o2, e2 = fd1.getvalue(), fd2.getvalue()
        try:
            print("   bash: (",colored(re.sub(r'\n',r'\\n',o),"green"),")",sep='')
            print("evshell: (",colored(re.sub(r'\n',r'\\n',o2),"magenta"),")",sep='')
        except BrokenPipeError as bpe:
            with open("/dev/tty","w") as fd:
                here("Broken pipe!",file=fd)
                print("   bash: (",colored(re.sub(r'\n',r'\\n',o),"green"),")",sep='',file=fd)
                print("evshell: (",colored(re.sub(r'\n',r'\\n',o2),"magenta"),")",sep='',file=fd)
        assert o == o2
        assert e == e2, f"bash: <{e}> != evshell: <{e2}>"
        here("test passed")
    finally:
        s.vars = {}
        for k in varsave:
            s.vars[k] = varsave[k]
        s.stdout = outsave
        s.stderr = errsave
        s.stdin = insave
        s.flags = flags


skip = False
for f in sys.argv[1:]:
    print("Running test file:", f)
    with open(f, "r") as fd:
        test(fd.read())
    skip = True
if skip:
    here("Done")
    exit(0)
test("for i in $(seq 1 10); do echo $i; done")
test("""for i in $(seq 1 10)
do echo $i
done
""")
test("echo hi; for a in 1 2 3; do echo $a; done")
test("echo hi; for a in 1 2 3; do for b in 4 5 6; do echo $a$b; done; done")
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
os.chdir('tests')
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
for f in os.listdir("."):
    if not f.endswith(".sh"):
        continue
    print(colored("Running test file:","cyan"), f)
    with open(f, "r") as fd:
        test(fd.read(),fname=f)
here("All tests passed")
