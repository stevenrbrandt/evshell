
def here(*args):
    import inspect
    stack = inspect.stack()
    frame = stack[1]
    print("HERE:","%s:%d" % (frame.filename, frame.lineno), *args, flush=True)
    frame = None
    stack = None
