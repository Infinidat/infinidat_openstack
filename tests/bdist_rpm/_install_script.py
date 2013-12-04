import glob
import os
import urllib
import shutil

# TODO deduce dependencies
DEPS = ["infinipy", "infi.execute"]
CURDIR = os.path.abspath('.')


def urlretrieve(*args, **kwargs):
    print args, kwargs
    urllib.urlretrieve(*args, **kwargs)


def system(*args, **kwargs):
    print args, kwargs
    os.system(*args, **kwargs)



[os.remove(path) for path in glob.glob("INSTALLED_FILES*")]
for dependency in DEPS:
    for fname in glob.glob(".cache/dist/{}*egg".format(dependency)):
        [os.remove(path) for path in glob.glob(".cache/dist/{}*tar.gz".format(dependency))]
        tgz = os.path.basename(fname)[:-10] + ".tar.gz"  # -py2.7.egg
        url = "http://pypi01/media/dists/{}".format(tgz)
        filepath = ".cache/dist/{}".format(tgz)
        urlretrieve(url, filepath)
    for fname in glob.glob(".cache/dist/{}*tar.gz".format(dependency)):
        os.chdir(CURDIR)
        system("tar zxf {}".format(fname))
        dirname = [item for item in glob.glob("{}*".format(dependency)) if os.path.isdir(item)][0]
        os.chdir(dirname)
        system("python2.6 setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record=../INSTALLED_FILES.{}".format(dependency))
        os.chdir(CURDIR)
        shutil.rmtree(dirname)

system("python2.6 setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES")
with open("INSTALLED_FILES", 'a') as fd:
    for filename in glob.glob("INSTALLED_FILES.*"):
        with open(filename) as rfd:
            fd.write(rfd.read())

with open("INSTALLED_FILES") as fd:
    files = fd.readlines()

buildroot = os.environ.get("RPM_BUILD_ROOT")
existing_files = [item for item in files if os.path.exists(os.path.join(buildroot, item.strip()[1:]))]
with open("INSTALLED_FILES", 'w') as fd:
    fd.write("\n".join(set(existing_files)))
