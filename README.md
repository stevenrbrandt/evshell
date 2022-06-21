# Pieshell

Pieshell is an implementation of most of the bash shell features in Python. One of the main goals is to provide a fine-grained limitation of what users are allowed to do. It's also just fun.

Demo:
```
  $ python3 shell.py
shell> echo hello
hello
shell> for i in $(seq 1 10)
>> do
>> echo $i
1
>> done
2
3
4
5
6
7
8
9
10
shell> echo $((3+4))
7
```
