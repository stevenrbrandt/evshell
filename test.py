from shell import shell
import sys, re, os
from subprocess import Popen, PIPE
from here import here
from colored import colored

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
