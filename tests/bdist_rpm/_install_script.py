import glob
import os
import urllib
import shutil
import infi.traceback

CURDIR = os.path.abspath('.')
INSTALL_LINE = "$PYTHON setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record={0}"
EXCLUDED_PACKAGES = ("distribute", "setuptools", "pip",
                     "six", "requests", "bson", "pymongo", "ipython", "oslo.config",
                     "python-cinderclient", "babel", "pbr", "simplejson", "prettytable",
                     "python-dateutil", "contextlib2", "pyparsing")


def get_name():
    from infinidat_openstack.config import get_config_parser
    with get_config_parser("buildout.cfg", False) as buildout:
        return buildout.get("project", "name")


def get_dependencies():
    from infi.pypi_manager import depends
    name = get_name()
    return [item[1] for item in depends.get_dependencies(get_name())]


def urlretrieve(*args, **kwargs):
    print args, kwargs  # helpful in debugging
    urllib.urlretrieve(*args, **kwargs)


def system(*args, **kwargs):
    print args, kwargs  # helpful in debugging
    os.system(*args, **kwargs)


def remove_glob(pattern):
    for path in insensitive_glob(pattern):
        os.remove(path)


def add_import_setuptools_to_setup_py():
    with open("setup.py") as fd:
        content = fd.read()
    content = content.replace("from distutils.core import setup", "from setuptools import setup")
    content = content.replace("from distutils import core", "import setuptools as core")
    with open("setup.py", 'w') as fd:
        fd.write(content)


def insensitive_glob(pattern):
    def either(c):
        return '[%s%s]'%(c.lower(),c.upper()) if c.isalpha() else c
    return glob.glob(''.join(map(either,pattern)))


def build_dependency(dependency):
    for fname in insensitive_glob(".cache/dist/{}-*egg".format(dependency)):
        remove_glob(".cache/dist/{}-*tar.gz".format(dependency))
        tgz = os.path.basename(fname)[:-10] + ".tar.gz"  # -py2.7.egg
        url = "http://pypi.infinidat.com/media/dists/{}".format(tgz)
        filepath = ".cache/dist/{}".format(tgz)
        urlretrieve(url, filepath)
    for fname in insensitive_glob(".cache/dist/{}-*zip".format(dependency)):
        remove_glob(".cache/dist/{}-*zip".format(dependency))
        tgz = os.path.basename(fname)[:-4] + ".tar.gz"
        url = "http://pypi.infinidat.com/media/dists/{}".format(tgz)
        filepath = ".cache/dist/{}".format(tgz)
        urlretrieve(url, filepath)
    # handle packages like json_rest, infinibox_sysdefs and python-cinderclient
    files = set.union(set(insensitive_glob(".cache/dist/{}-*tar.gz".format(dependency.replace('-', '_')))),
                      set(insensitive_glob(".cache/dist/{}-*tar.gz".format(dependency.replace('_', '-')))))
    for fname in files:
        os.chdir(CURDIR)
        system("tar zxf {}".format(fname))
        # handle packages like json_rest, infinibox_sysdefs and python-cinderclient
        directories = set.union(set(insensitive_glob("{}*".format(dependency.replace('-', '_')))),
                                set(insensitive_glob("{}*".format(dependency.replace('_', '-')))))
        dirname = [item for item in directories if os.path.isdir(item)][0]
        os.chdir(dirname)
        add_import_setuptools_to_setup_py()
        system(INSTALL_LINE.format("../dist/INSTALLED_FILES." + dependency))
        os.chdir(CURDIR)
        system("tar czf {} {}".format(fname, dirname))
        shutil.rmtree(dirname)


def cleanup():
    remove_glob("dist/INSTALLED_FILES*")


def install_files():
    for dependency in set(get_dependencies()):
        if dependency.lower() in EXCLUDED_PACKAGES:
            continue
        build_dependency(dependency)
    system(INSTALL_LINE.format("dist/INSTALLED_FILES"))


def delete_uneeded_files():
    buildroot = os.environ.get("RPM_BUILD_ROOT")
    for filepath in glob.glob(os.path.join(buildroot, "usr", "bin", "*")):
        if not filepath.endswith("infini-openstack"):
            os.remove(filepath)
    for filepath in glob.glob(os.path.join(buildroot, "usr", "lib", "python*", "site-packages", "*", "requires.txt")):
        os.remove(filepath)


def write_install_files():
    files = []
    for filename in glob.glob("dist/INSTALLED_FILES*"):
        with open(filename) as fd:
            files.extend(fd.read().splitlines())
    buildroot = os.environ.get("RPM_BUILD_ROOT")
    existing_files = [item for item in files if
                      os.path.exists(os.path.join(buildroot, item.strip()[1:]))
                      and not item.startswith("/usr/bin/") and not item.endswith("/requires.txt")]
    with open("dist/INSTALLED_FILES", 'w') as fd:
        fd.write("/usr/bin/infini-openstack\n")
        fd.write("\n".join(sorted(set(existing_files))))


@infi.traceback.pretty_traceback_and_exit_decorator
def main():
    cleanup()
    install_files()
    delete_uneeded_files()
    write_install_files()


if __name__ == "__main__":
    main()
