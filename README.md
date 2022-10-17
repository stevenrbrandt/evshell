# evshell - The Everglades Shell

<span style="display: inline-block"><p>Evhell is an implementation of most of the bash shell in Python. One of the main goals of this project is to provide a restricted shell that enables fine-grained limitation of what users are allowed to do. It's also just fun.</p></span>

Installation:

```
python3 -m pip install --user evshell
```

Demo:
```
$ evshell
🍰> echo hello
hello
🍰> for i in $(seq 1 10)
🍰? do
🍰? echo $i
1
🍰? done
2
3
4
5
6
7
8
9
10
🍰> echo $((3+4))
7
```
