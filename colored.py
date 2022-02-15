import sys

def not_colored(a,_):
    return a

installed = None

try:
    from termcolor import colored
    colored = colored
    installed = True
except:
    colored = not_colored
    installed = False

if not sys.stdout.isatty():
    colored = not_colored

if __name__ == "__main__":
    if installed:
        print(colored("Colored was installed","green"))
    else:
        print("Colored was NOT installed")
