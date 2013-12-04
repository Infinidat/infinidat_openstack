import glob
import os
import urllib
import shutil

CURDIR = os.path.abspath('.')
INSTALL_LINE = "$PYTHON setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record={0}"

def get_name():
    from infi.projector.helper.utils import open_buildout_configfile
    with open_buildout_configfile("buildout.cfg", False) as buildout:
        return buildout.get("project", "name")


def get_dependencies():
    from infi.pypi_manager import dependencies
    name = get_name()
    return [item[1] for item in dependencies.get_dependencies(get_name())]


def urlretrieve(*args, **kwargs):
    print args, kwargs
    urllib.urlretrieve(*args, **kwargs)


def system(*args, **kwargs):
    print args, kwargs
    os.system(*args, **kwargs)


def remove_glob(pattern):
    for path in glob.glob(pattern):
        os.remove(path)


def build_dependency(dependency):
    for fname in glob.glob(".cache/dist/{}*egg".format(dependency)):
        remove_glob(".cache/dist/{}*tar.gz".format(dependency))
        tgz = os.path.basename(fname)[:-10] + ".tar.gz"  # -py2.7.egg
        url = "http://pypi01/media/dists/{}".format(tgz)
        filepath = ".cache/dist/{}".format(tgz)
        urlretrieve(url, filepath)
    for fname in glob.glob(".cache/dist/{}*tar.gz".format(dependency)):
        os.chdir(CURDIR)
        system("tar zxf {}".format(fname))
        dirname = [item for item in glob.glob("{}*".format(dependency)) if os.path.isdir(item)][0]
        os.chdir(dirname)
        system(INSTALL_LINE.format("../INSTALLED_FILES." + dependency))
        os.chdir(CURDIR)
        shutil.rmtree(dirname)


def cleanup():
    remove_glob("INSTALLED_FILES*")


def install_files():
    for dependency in get_dependencies():
        build_dependency(dependency)
    system(INSTALL_LINE.format("INSTALLED_FILES"))


def write_install_files():
    files = []
    for filename in glob.glob("INSTALLED_FILES*"):
        with open(filename) as fd:
            files.extend(fd.read().splitlines())
    buildroot = os.environ.get("RPM_BUILD_ROOT")
    existing_files = [item for item in files if os.path.exists(os.path.join(buildroot, item.strip()[1:]))]
    with open("INSTALLED_FILES", 'w') as fd:
        fd.write("\n".join(set(existing_files)))


def main():
    cleanup()
    install_files()
    write_install_files()

if __name__ == "__main__":
    main()
