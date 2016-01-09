from glob import glob
from os import path
from infi.unittest import SkipTest
from infi.execute import execute, execute_assert_success, ExecutionError
from infi.os_info import get_platform_string


INFINIOPENSTACK_EXECUTABLE = "/usr/bin/infini-openstack"
CINDER_CONFIG_FILE = "/etc/cinder/cinder.conf"


def is_devstack():
    return path.exists('/opt/stack')


def get_admin_password():
    return "stack" if 'ubuntu' in get_platform_string() else "admin"


def install_package():
    if 'ubuntu' not in get_platform_string():
        packages = [item for item in glob("dist/*rpm") if 'debuginfo' not in item]
        if not packages:
            raise SkipTest("no rpm packages found")
        execute_assert_success(["rpm", "-Uvh", packages[0]])
    else:
        packages = [item for item in glob("parts/*deb")]
        if not packages:
            raise SkipTest("no deb packages found")
        execute_assert_success(["dpkg", "-i"] + packages)


def remove_package():
    if 'ubuntu' not in get_platform_string():
        pid = execute(["rpm", "-e", "infinidat_openstack"])
        not_installed_str = "not installed"
    else:
        pid = execute(["dpkg", "-r", "python-infininidat-openstack"])
        not_installed_str = "isn't installed"
    if pid.get_returncode() != 0 and not_installed_str not in pid.get_stderr():
        raise ExecutionError(pid)


def ensure_package_is_installed():
    remove_package()
    install_package()
    if not path.exists(INFINIOPENSTACK_EXECUTABLE):
        raise SkipTest("openstack plugin not installed")
