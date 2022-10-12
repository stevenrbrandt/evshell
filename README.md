# Pieshell

Pieshell is an implementation of most of the bash shell features in Python. One of the main goals is to provide a fine-grained limitation of what users are allowed to do. It's also just fun.

Installation:

```
python3 -m pip install --user 'git+https://github.com/stevenrbrandt/piraha-peg/#subdirectory=py/'
python3 -m pip install --user 'git+https://github.com/stevenrbrandt/pieshell/'
```

Demo:
```
$ pieshell
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
