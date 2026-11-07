"""Restricted Python execution for the benchmark, not an OS security sandbox.

AST policy plus audit hooks resist evaluator edits, filesystem writes, dynamic imports,
networking, subprocesses and ordinary reflection. Native-code exploits are out of scope.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

IMPORTS = {"json", "typing", "pydantic", "sqlite3"}
BANNED = {
    "open",
    "exec",
    "eval",
    "compile",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "input",
    "print",
    "breakpoint",
    "help",
    "exit",
    "quit",
    "memoryview",
}
ATTRIBUTES = {
    "connect",
    "set_authorizer",
    "set_progress_handler",
    "set_trace_callback",
    "enable_load_extension",
    "load_extension",
    "backup",
    "deserialize",
    "serialize",
    "cursor_factory",
    "executescript",
}


def check_source(source):
    tree = ast.parse(source)
    if len(source.encode()) > 24000:
        raise ValueError("candidate exceeds 24 KB")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and node.level:
                raise ValueError("relative imports are outside repair scope")
            if any(m.split(".")[0] not in IMPORTS or m == "pydantic.v1" for m in modules):
                raise ValueError("import outside repair scope")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in BANNED):
            raise ValueError("unsafe builtin or reflection")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in ATTRIBUTES):
            raise ValueError("unsafe attribute")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Attribute) for t in targets):
                raise ValueError("monkeypatching is outside repair scope")
    return source


GUARD = """
import sys, os, json, sqlite3, resource, contextlib, io
resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
resource.setrlimit(resource.RLIMIT_FSIZE, (2000000, 2000000))
resource.setrlimit(resource.RLIMIT_NOFILE, (64,64))
request = json.loads(sys.stdin.read())
source = request["source"]
code = compile(source, "candidate.py", "exec")
allowed_db = request.get("db_path")
read_roots = [os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix)]
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        readable = isinstance(path,str) and any(os.path.realpath(path).startswith(base + os.sep) for base in read_roots)
        writing = isinstance(mode,str) and any(c in mode for c in "wax+") or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
        if not readable or writing:
            raise PermissionError("candidate filesystem access is forbidden")
    if event in ("os.listdir", "os.scandir"):
        if not isinstance(args[0],str) or not any(os.path.realpath(args[0]).startswith(base + os.sep) for base in read_roots):
            raise PermissionError("candidate directory access is forbidden")
    if event.startswith(("socket.", "subprocess.", "ctypes.", "os.exec", "os.spawn", "os.fork", "os.system", "os.remove", "os.rename", "os.mkdir", "os.chmod", "os.link", "os.symlink", "shutil.", "sys.set")):
        raise PermissionError("candidate operation is forbidden")
    if event == "sqlite3.connect" and args[0] != allowed_db:
        raise PermissionError("only the supplied database is accessible")
    if event == "import" and args[0].split(".")[0] not in {"json", "typing", "pydantic", "sqlite3"}:
        raise PermissionError("candidate dynamic import is forbidden")
namespace = {}
"""


def run(source, payload, prelude, body):
    check_source(source)
    script = (
        GUARD
        + "\n"
        + prelude
        + """
sys.addaudithook(audit)
capture = io.StringIO()
with contextlib.redirect_stdout(capture):
    exec(code, namespace)
"""
        + body
    )
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0"}
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        input=json.dumps({**payload, "source": source}),
        capture_output=True,
        text=True,
        env=env,
        timeout=12,
    )
    if completed.returncode:
        raise ValueError("Restricted worker failed: " + completed.stderr[-1600:])
    if len(completed.stdout) > 1000000:
        raise ValueError("worker output exceeds limit")
    return json.loads(completed.stdout)
