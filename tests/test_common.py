from glob import glob
from os import path
from infi.unittest import SkipTest
from infi.execute import execute, execute_assert_success, ExecutionError

INFINIOPENSTACK_EXECUTABLE = "/usr/bin/infini-openstack"
CINDER_CONFIG_FILE = "/etc/cinder/cinder.conf"

def install_package():
    packages = glob("dist/*rpm")
    if not packages:
        raise SkipTest("no packages found")
    execute_assert_success(["rpm", "-Uvh", packages[0]])


def remove_package():
    pid = execute(["rpm", "-e", "infinidat_openstack"])
    if pid.get_returncode() != 0 and 'not installed' not in pid.get_stderr():
        raise ExecutionError(pid)


def ensure_package_is_installed():
    remove_package()
    install_package()
    if not path.exists(INFINIOPENSTACK_EXECUTABLE):
        raise SkipTest("openstack plugin not installed")
