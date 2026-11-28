"""Run the official bucket with a time limit on each case's process group."""

import os
import runpy
import signal
import subprocess
import sys


def _run_case(
    *args, input=None, capture_output=False, timeout=None, check=False, **kwargs
):
    """Run a subprocess with the shorter of its timeout and CASE_TIMEOUT_SECONDS.

    Args:
        *args: Positional arguments for subprocess.Popen.
        input: Optional data to send to stdin.
        capture_output: Capture both stdout and stderr.
        timeout: Optional caller-supplied limit in seconds.
        check: Raise on a nonzero exit status.
        **kwargs: Additional subprocess.Popen options.

    Returns:
        A subprocess.CompletedProcess with the exit status and captured output.

    Raises:
        subprocess.TimeoutExpired: The case exceeded its time limit.
        subprocess.CalledProcessError: The case failed with check enabled.
    """
    case_timeout = int(os.environ.get("CASE_TIMEOUT_SECONDS", "600"))
    timeout = case_timeout if timeout is None else min(timeout, case_timeout)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input cannot both be supplied")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("capture_output conflicts with stdout or stderr")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE

    kwargs["start_new_session"] = True
    with subprocess.Popen(*args, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            # The case shell and its children can all hold the output pipe open.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise
        result = subprocess.CompletedProcess(
            process.args, process.returncode, stdout, stderr
        )
        if check:
            result.check_returncode()
        return result


def main():
    """Run the bucket in this interpreter so it inherits the subprocess patch."""
    runner, *rest = sys.argv[1:]
    sys.argv = [runner, *rest]
    sys.path[0] = os.path.dirname(os.path.abspath(runner))
    subprocess.run = _run_case
    runpy.run_path(runner, run_name="__main__")


if __name__ == "__main__":
    main()
