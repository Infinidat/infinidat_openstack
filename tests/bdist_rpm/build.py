import os

# TODO deduce system python and arch
PYTHON = os.environ.get("PYTHON")
ARCH = os.environ.get("ARCH")
PROJECTDIR = os.path.abspath(os.path.curdir)

SCRIPT = """PROJECTDIR={0} PYTHON={1} {1} setup.py bdist_rpm --binary-only --force-arch {2} --requires python-setuptools \
--install-script=tests/bdist_rpm/_install_script.sh \
--build-script=tests/bdist_rpm/_build_script.sh"""

os.system(SCRIPT.format(PROJECTDIR, PYTHON, ARCH))
