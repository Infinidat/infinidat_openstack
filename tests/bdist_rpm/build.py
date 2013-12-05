import os
import sys


PYTHON26 = "/usr/bin/python2.6"
PYTHON27 = "/usr/bin/python2.7"
PYTHON = os.path.basename(PYTHON26) if os.path.exists(PYTHON26) else PYTHON27
ARCH = "x86_64" if sys.maxsize > 2**32 else "i686"
PROJECTDIR = os.path.abspath(os.path.curdir)

SCRIPT = """PROJECTDIR={0} PYTHON={1} {1} setup.py bdist_rpm --binary-only --force-arch {2} --requires python-setuptools \
--install-script=tests/bdist_rpm/_install_script.sh \
--build-script=tests/bdist_rpm/_build_script.sh \
--vendor Infinidat --packager Infinidat """

os.system(SCRIPT.format(PROJECTDIR, PYTHON, ARCH))
