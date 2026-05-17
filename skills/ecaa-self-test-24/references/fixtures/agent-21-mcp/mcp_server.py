# ruff: noqa
# Intentionally contains the bugs each detector should catch.
import subprocess

# MCP tool handler exposed to LLM clients. `tool_name` and `user_input`
# both come from untrusted client requests — command injection via
# shell=True is trivial (attacker can read any system-config file).
def run_tool(tool_name, user_input):
    cmd = f"{tool_name} {user_input}"
    return subprocess.run(cmd, shell=True, capture_output=True).stdout
