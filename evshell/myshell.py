from evshell import shell, run_shell, ShellAccess
import os
import re
import sys
from colored import colored
from here import here
from shutil import which

# This example limits shell access to a handful of commands
# and gives the user access only to files in the workpath or
# in the home directory (read access only).
# In addition, it limits the number and size of arguments
# supplied to any command in order to avoid buffer overrun.
workpath = os.path.join("/tmp",os.environ["USER"])
homepath = os.path.abspath(os.environ["HOME"])

def allow_access(fn):
    fn = os.path.abspath(fn)
    if fn == workpath or fn.startswith(workpath+"/"):
        return fn
    else:
        raise ShellAccess(f"Access of file '{fn}' not allowed.")

def allow_read(fn):
    fn = os.path.abspath(fn)
    if fn == homepath or fn.startswith(homepath+"/"):
        return fn
    else:
        return allow_access(fn)

def allow_set_var(var, val):
    if var in ["USER","LOGNAME","HOME","PATH","SHELL"]:
        raise ShellAccess(f"Setting of var '{var}' is not allowed.")
    else:
        return val

allowed_cmds = dict()

def add_cmd(nm,*flags):
    w = which(nm)
    allowed_cmds[w] = flags

class access_file():
    def __init__(self):
        pass
    def ok(self,f):
        return allow_access(f)

class read_file():
    def __init__(self):
        pass
    def ok(self,f):
        return allow_read(f)

class regex:
    def __init__(self,r):
        self.r = r
    def ok(self,a):
        return re.match(r"^"+self.r+r"$", a)

any_arg = regex(".*")

add_cmd("which",any_arg)
add_cmd("ls","-l","-s","-ls","-a",read_file())
add_cmd("file",access_file())
add_cmd("cat","-",read_file())
add_cmd("ps",any_arg)
add_cmd("mkdir","-p",access_file())
add_cmd("rmdir",access_file())
add_cmd("rm","-r",access_file())
add_cmd("exit",regex("[0-9]+"))
add_cmd("date",any_arg)
add_cmd("echo",any_arg)
add_cmd("cal",regex("[0-9]+"))
add_cmd("pwd")

def allow_cmd(args):
    """
    Validate the arguments supplied to any command
    """
    if args[0] == "/usr/libexec/openssh/sftp-server":
        args[0] = "/project/sbrandt/c/openssh-portable/sftp-server"
        return [args[0]]

    allow = True
    if len(args) > 20: # Limit the number of args to a command
        return False
    if args[0] in allowed_cmds:
        for a in args[1:]:
            if len(a) > 1024: # Limit each argument's size
                return False
            found = False
            for p in allowed_cmds[args[0]]:
                if type(p) == str:
                    if p == a:
                        found = True
                        break
                elif p.ok(a):
                    found = True
                    break
            if not found:
                allow = False
                break
    else:
        allow = False

    if allow:
        return args
    else:
        raise ShellAccess(f"Command '{args}' is not allowed.")

if __name__ == "__main__":

    # Get the full shell path
    shell_path = os.path.realpath(sys.argv[0])

    # Ensure the workpath exists
    os.makedirs(workpath,exist_ok=True)

    # Start in the workpath
    os.chdir(workpath)

    # Create the shell
    s = shell()
    s.args[0] = shell_path

    # Limit chdir
    s.allow_cd = allow_access

    # Limit read by the < mechanism
    s.allow_read = allow_read

    # Limit write by the > mechansim
    s.allow_write = allow_access

    # Limit append by the >> mechanism
    s.allow_append = allow_access

    # Limit shell variables that may be set
    s.allow_set_var = allow_set_var

    # Limit commands that may be run
    s.allow_cmd = allow_cmd

    run_shell(s)
