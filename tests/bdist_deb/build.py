from infi.execute import execute_assert_success
from infi.recipe.application_packager import utils
from contextlib import contextmanager
import tempfile
import glob
import os
import shutil
import logging


logger = logging.getLogger(__name__)

def get_name():
    from infinidat_openstack.config import get_config_parser
    with get_config_parser("buildout.cfg", False) as buildout:
        return buildout.get("project", "name").replace("_", "-")

def execute(command_line):
    return execute_assert_success(command_line, shell=True)

def get_deb_package_name(package_name):
    PREFIX = "python-"
    package_name = "{}{}".format(PREFIX, package_name) if not package_name.startswith(PREFIX) else package_name
    return package_name.lower()

def package_in_apt_cache(deb_package_name):
    return deb_package_name in execute("apt-cache search {}".format(deb_package_name)).get_stdout()

def get_level1_dependencies(package_name):
    from infi.pypi_manager.depends import get_dependencies
    return [dep for dep in get_dependencies(package_name) if dep[0] and dep[0].startswith(package_name)]

def find_pacakge_in_cache_dist(package_name):
    cache_dist_dir = ".cache/dist"
    path_no_ver_underscore = os.path.abspath(os.path.join(cache_dist_dir, package_name.replace("-","_")))
    path_no_ver = os.path.abspath(os.path.join(cache_dist_dir, package_name))
    extensions = [".tar.gz", '.zip', '.egg']
    for filename in os.listdir(cache_dist_dir):
        if not filename.lower().replace("-", "_").startswith(package_name.replace("-", "_").lower()):
            continue
        # package-<version>
        prefix = os.path.basename(filename).lower().replace("-", "_").replace(package_name.replace("-", "_").lower(), '')
        if prefix[0] != '_' or not prefix[1].isdigit():
            continue
        for extension in extensions:
            if filename.endswith(extension):
                return os.path.join(cache_dist_dir, filename)
    msg = "Couldn't find package {} in {}".format(package_name, cache_dist_dir)
    logger.error(msg)
    raise Exception(msg)

def unzip(filename, dest_dir):
    if filename.endswith('.tar.gz'):
        execute("tar -xzf {} -C {}".format(filename, dest_dir))
    elif filename.endswith('.zip'):
        execute("unzip -o {} -d {}".format(filename, dest_dir))
    else:
        msg = "Unknown zip file extension"
        logger.error(msg)
        raise Exception(msg)

@contextmanager
def change_directory_context(directory):
    cwd = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(cwd)

def format_dependency_string(dependency_list):
    """python-docopt (>= 0.6.2),  functools32 (>= 2.3.3)"""
    if not dependency_list:
        return ""
    formatted_dep_list = []
    for package, dep, version_specific_dep in dependency_list:
        specific = " (>= {})".format(version_specific_dep.split(">=")[-1]) if ">=" in version_specific_dep else ""
        formatted_dep_list.append("{}{}".format(get_deb_package_name(dep), specific))
    return " --depends " + "\"" + ", ".join(formatted_dep_list) + "\""

def remove_pyc_files():
    execute("find . -name \"*.pyc\" -exec rm -rf \{\} \;")

def remove_zip_extension(filename):
    from os.path import splitext
    if filename.endswith('.tar.gz'):
        return splitext(splitext(filename)[0])[0]
    elif filename.endswith('.zip'):
        return splitext(filename)[0]
    else:
        msg = "Unknown zip file extension"
        logger.error(msg)
        raise Exception(msg)

def convert_egg_to_tar_gz(compressed_egg_path):
    new_basename = os.path.basename(compressed_egg_path).replace('-py2.7.egg', '.tar.gz')
    dirname = os.path.dirname(compressed_egg_path)
    compressed_egg_path = os.path.join(dirname, new_basename)
    execute("wget -P {} http://pypi.infinidat.com/media/dists/{}".format(dirname, new_basename))
    return compressed_egg_path

def build_bdist_deb():
    built_packages = set()

    def build_deb(package_name, dependencies):
        dependecies_str = format_dependency_string(dependencies)
        msg = "Building package {}, with dependencies: {}".format(package_name, dependencies)
        logger.info(msg)
        execute("/usr/bin/python setup.py --command-packages=stdeb.command sdist_dsc --package={}".format(get_deb_package_name(package_name)) + dependecies_str)
        package_dir = sorted([item for item in glob.glob(os.path.join('deb_dist', '*')) if os.path.isdir(item)])[-1]
        with change_directory_context(package_dir):
            execute("dpkg-buildpackage -b")

    def copy_deb_to_parts(egg_dir):
        from infi.os_info import get_platform_string
        for debfile in glob.glob(os.path.join(egg_dir, 'deb_dist', '*.deb')):
            basename = os.path.basename(debfile.replace('_all', '-' + get_platform_string()))
            basename = basename.replace('_amd64', '-' + get_platform_string())
            basename = basename.replace('_i386', '-' + get_platform_string())
            shutil.copy(debfile, os.path.join('parts', basename))

    def build_dependency(package_name):
        dependencies = get_level1_dependencies(package_name)
        if package_name != get_name():
            deb_package_name = get_deb_package_name(package_name)
            # if package_in_apt_cache(deb_package_name):
            #     return

            compressed_egg_path = find_pacakge_in_cache_dist(package_name)
            temp_dir = tempfile.gettempdir()
            if compressed_egg_path.endswith(".egg"):
                compressed_egg_path = convert_egg_to_tar_gz(compressed_egg_path)
            extracted_egg_dir = os.path.join(temp_dir, os.path.basename(remove_zip_extension(compressed_egg_path)))
            if os.path.exists(extracted_egg_dir):
                shutil.rmtree(extracted_egg_dir)
            unzip(compressed_egg_path, temp_dir)
            with change_directory_context(extracted_egg_dir):
                remove_pyc_files()
                build_deb(package_name, dependencies)
            copy_deb_to_parts(extracted_egg_dir)
            built_packages.add(package_name.lower())
        else:
            build_deb(package_name, dependencies)
            copy_deb_to_parts('.')

        for package, dep, version_specific_dep in dependencies:
            if not dep.lower() in built_packages:
                build_dependency(dep)


    utils.download_setuptools(os.path.join('.cache', 'dist'))
    utils.download_buildout(os.path.join('.cache', 'dist'))
    build_dependency(get_name())


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    os.system("projector devenv build --use-isolated-python")
    build_bdist_deb()
