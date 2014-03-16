import os
import sys
import glob

def get_os_string():
    from platform import architecture, system, dist
    from sys import maxsize
    is_64 = maxsize > 2 ** 32
    arch_name = 'x64' if is_64 else 'x86'
    system_name = system().lower().replace('-', '').replace('_', '')
    dist_name, dist_version, dist_version_name = dist()
    dist_name = dist_name.lower()
    is_ubuntu = dist_name == 'ubuntu'
    dist_version_string = dist_version_name.lower() if is_ubuntu else dist_version.lower().split('.')[0]
    string_by_os = {
                    "Windows": '-'.join([system_name, arch_name]),
                    "Linux": '-'.join([system_name, dist_name, dist_version_string, arch_name]),
    }
    return string_by_os.get(system())


def get_name():
    from infinidat_openstack.config import get_config_parser
    with get_config_parser("buildout.cfg", False) as buildout:
        return buildout.get("project", "name")


def shorten_version(long_version):
    from pkg_resources import parse_version
    version_numbers = []
    parsed_version = list(parse_version(long_version))
    for item in parsed_version:
        if not item.isdigit():
            break
        version_numbers.append(int(item))
    while len(version_numbers) < 3:
        version_numbers.append(0)
    index = parsed_version.index(item)
    for item in parsed_version[index:]:
        if item.isdigit():
            version_numbers.append(int(item))
            break
    return '.'.join([str(item) for item in  version_numbers])


def change_version_in_setup_py():
    from brownie.importing import import_string
    long_version = import_string("{}.__version__".format(get_name())).__version__
    short_version = shorten_version(long_version)
    with open("setup.py") as fd:
        setup_py = fd.read()
    with open("setup.py", "w") as fd:
        fd.write(setup_py.replace(long_version, short_version))


def main():
    PYTHON26 = "/usr/bin/python2.6"
    PYTHON27 = "/usr/bin/python2.7"
    PYTHON = os.path.basename(PYTHON26) if os.path.exists(PYTHON26) else PYTHON27
    ARCH = "x86_64" if sys.maxsize > 2**32 else "i686"
    PROJECTDIR = os.path.abspath(os.path.curdir)

    SCRIPT = """PROJECTDIR={0} PYTHON={1} {1} setup.py bdist_rpm --binary-only --force-arch {2} \
    --requires python-setuptools --requires python-six --requires python-requests \
    --requires python-bson --requires python-pymongo \
    --requires python-cinderclient --requires python-simplejson --requires python-pbr \
    --requires python-pip --requires python-babel \
    --install-script=tests/bdist_rpm/_install_script.sh \
    --build-script=tests/bdist_rpm/_build_script.sh \
    --vendor Infinidat --packager Infinidat """

    change_version_in_setup_py()

    os.system(SCRIPT.format(PROJECTDIR, PYTHON, ARCH))
    for filename in glob.glob("dist/*rpm"):
        if get_os_string() in filename:
            continue
        new = filename.replace(filename[filename.rindex('-'):], "-{}.rpm".format(get_os_string()))
        os.rename(filename, new)

if __name__ == "__main__":
    main()
