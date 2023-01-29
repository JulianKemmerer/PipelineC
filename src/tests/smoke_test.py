import subprocess


def test_pipelinec_no_exceptions():
    cmd = "python3 pipelinec.py"
    subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
