"""infini-openstack v{0}

Usage:
    infini-openstack [options] volume-backend list
    infini-openstack [options] volume-backend set <management-address> <username> <password> <pool-name> [--thick-provisioning]
    infini-openstack [options] volume-backend remove <management-address> <pool-id>
    infini-openstack [options] volume-backend enable <management-address> <pool-id>
    infini-openstack [options] volume-backend disable <management-address> <pool-id>
    infini-openstack [options] volume-backend update (all | <management-address> <pool-id>)
    infini-openstack (-h | --help)
    infini-openstack (-v | --version)

Commands:
    list                                 print information about configured InfiniBox systems
    refresh                              refresh volume types display
    set                                  add or update an existing InfiniBox system to Cinder
    remove                               delete an existing InfiniBox system from Cinder
    enable                               configure Cinder to load driver for this InfiniBox system
    disable                              configure Cinder not to load driver for this InfiniBox system
    update                               update volume type display name to match the pool name

Options:
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --rc-file=<rc-file>                  openstack rc file [default: ~/keystonerc_admin]
    --commit                             commit the changes into cinder's configuration file (also erases the comments inside it)
"""


import docopt
import sys
import os
import warnings
warnings.catch_warnings(warnings.simplefilter("ignore")).__enter__() # sentinels has deprecation warning
with warnings.catch_warnings():
    import infinisdk # infinisdk import requests, and requests.packagers.urllib3 calls warning.simplefilter


CONFIGURATION_MODIFYING_KWARGS = ("set", "remove", "enable", "disable", "update")
DONE_MESSAGE = "done, restarting cinder-volume service is requires for changes to take effect"
DONE_NO_RESTART_MESSAGE = "done"
TRACEBACK_FILE = sys.stderr
TABLE_HEADER = ["address", "username", "enabled", "status", "system serial", "system name", "pool id", "pool name"]
NO_SYSTEMS_MESSAGE = "no systems configured"


def system_list(config_parser):
    from prettytable import PrettyTable
    from .config import get_systems, get_enabled_backends
    systems = get_systems(config_parser)
    if not systems:
        _print(NO_SYSTEMS_MESSAGE, sys.stderr)
        return
    table = PrettyTable(TABLE_HEADER)  # v0.6.1 installed by openstack does not print empty tables
    backends = get_enabled_backends(config_parser)
    for system in systems:
        status = "connection successul"
        system_serial = system_name = pool_name = 'n/a'
        try:
            infinisdk = get_infinisdk_for_system(system)
            system_serial = infinisdk.get_serial()
            system_name = infinisdk.get_name()
            pool = infinisdk.pools.get(id=system['pool_id'])
            pool_name = pool.get_name()
        except Exception, error:
            status = error.message
        table.add_row([system['address'], system['username'], system['key'] in backends, status,
                       system_serial, system_name, system['pool_id'], pool_name])
    _print(table)


def parse_environment(text):
    """:returns: a 4tuple (username, password, project, url"""
    return_value = []
    items = [(line.split("=")[0].split()[1], line.split("=")[1])
            for line in text.splitlines()
            if "=" in line and line.startswith("export ")]
    env = dict(items) # no dict comprehension in Python-2.6
    return env["OS_USERNAME"], env["OS_PASSWORD"], env["OS_TENANT_NAME"], env["OS_AUTH_URL"]


def get_cinder_client(rcfile):
    from cinderclient.v1 import client
    with open(os.path.expanduser(rcfile)) as fd:
        args = parse_environment(fd.read())
    return client.Client(*args)


def assert_config_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        _print("cinder configuration file {0} does not exist".format(config_file), sys.stderr)
        raise SystemExit(1)


def assert_rc_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        _print("cinder environment file {0} does not exist".format(config_file), sys.stderr)
        raise SystemExit(1)


def get_infinisdk_for_system(system):
    return get_infinisdk_from_arguments({'<management-address>':system['address'], '<username>':system['username'],
                                        '<password>':system['password']})


def get_infinisdk_from_arguments(arguments):
    from infinisdk import InfiniBox
    from infinidat_openstack.versioncheck import raise_if_unsupported, get_system_version
    address, username, password = arguments.get('<management-address>'), arguments.get('<username>'), arguments.get('<password>')
    system = InfiniBox(address, use_ssl=True, auth=(username, password))
    raise_if_unsupported(get_system_version(address, username, password, system))
    return system


def handle_commands(arguments, config_file):
    from . import config
    from .exceptions import UserException
    any_modyfing_kwargs = any(arguments[kwarg] for kwarg in CONFIGURATION_MODIFYING_KWARGS)
    write_on_exit = arguments.get("--commit") and any_modyfing_kwargs
    if any_modyfing_kwargs and not arguments.get("--commit"):
        _print("this is a dry run, to commit the changes into cinder's configuration file, "\
            "you should pass --commit to this script (also erases the comments inside cinder's configuration file).")

    address, username, password = arguments.get('<management-address>'), arguments.get('<username>'), arguments.get('<password>')
    try:
        pool_name, pool_id = arguments.get('<pool-name>'), int(arguments.get("<pool-id>") or 0)
    except ValueError:
        raise UserException("invalid pool id: {0}".format(arguments.get("<pool-id>")))
    try:
        cinder_client = get_cinder_client(arguments['--rc-file'])
    except Exception, error:
        raise RuntimeError("failed to connect to cinder service: {0}".format(error.message or error))
    with config.get_config_parser(config_file, write_on_exit) as config_parser:
        system = config.get_system(config_parser, address, pool_id)
        if arguments['list']:
            return system_list(config_parser)
        elif arguments['set']:
            key = config.apply(config_parser, address, pool_name, username, password, arguments.get("--thick-provisioning"))
            if write_on_exit:
                _update_cg_policy()
                config.update_volume_type(cinder_client, key, get_infinisdk_from_arguments(arguments).get_name(), pool_name)
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['remove']:
            if system is None:
                _print("failed to remove '[InfiniBox] {0}/{1}', not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.disable(config_parser, system['key'])
            config.remove(config_parser, system['key'])
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['enable']:
            if system is None:
                _print("failed to enable '[InfiniBox] {0}/{1}', not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            config.enable(config_parser, system['key'])
            infinisdk = get_infinisdk_for_system(system)
            pool = infinisdk.objects.pools.get(id=pool_id)
            if write_on_exit:
                config.update_volume_type(cinder_client, system['key'], infinisdk.get_name(), pool.get_name())
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['update']:
            if arguments["all"]:
                for _system in config.get_systems(config_parser):
                    infinisdk = get_infinisdk_for_system(_system)
                    pool = infinisdk.pools.get(id=_system['pool_id'])
                    config.update_volume_type(cinder_client, _system['key'], infinisdk.get_name(), pool.get_name())
            else:
                if system is None:
                    _print("failed to update '[InfiniBox] {0}/{1}', not found".format(address, pool_id), sys.stderr)
                    sys.exit(1)
                infinisdk = get_infinisdk_for_system(system)
                pool = infinisdk.pools.get(id=system['pool_id'])
                config.update_volume_type(cinder_client, system['key'], infinisdk.get_name(), pool.get_name())
            _print(DONE_NO_RESTART_MESSAGE, sys.stderr)
        elif arguments['disable']:
            if system is None:
                _print("failed to disable '[InfiniBox] {0}/{1}', not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.disable(config_parser, system['key'])
            _print(DONE_MESSAGE, sys.stderr)


def _print(text, stream=sys.stdout):
    print >> stream, text


def _update_cg_policy():
    from re import compile, MULTILINE
    from os import path
    POLICY_FILENAME = '/etc/cinder/policy.json'
    if not path.exists(POLICY_FILENAME):
        return
    policy_data = open(POLICY_FILENAME).read()
    r = compile('"(consistencygroup:\w+)"\s*:\s*"group:nobody"', MULTILINE)
    policy_data = r.sub('"\\1" : ""', policy_data)
    open(POLICY_FILENAME, 'w').write(policy_data)


def main(argv=sys.argv[1:]):
    from .__version__ import __version__
    from .exceptions import UserException
    from traceback import print_exception
    from infinisdk.core.exceptions import APICommandFailed
    from logbook.handlers import NullHandler
    arguments = docopt.docopt(__doc__.format(__version__), argv=argv, version=__version__)
    config_file = arguments['--config-file']
    rc_file = arguments['--rc-file']

    if arguments['-v']:
        print __version__  # we don't use _print so it would act the same as --version which is handled by docopt
        return
    assert_config_file_exists(config_file)
    assert_rc_file_exists(rc_file)
    with NullHandler():
        try:
            return handle_commands(arguments, config_file)
        except SystemExit:
            raise
        except APICommandFailed, error:
            _print("InfiniBox API failed: {0}".format(error.message), sys.stderr)
            raise SystemExit(1)
        except UserException, error:
            _print(error.message or error, sys.stderr)
            raise SystemExit(1)
        except:
            _print("ERROR: Caught unhandled exception", sys.stderr)
            print_exception(*sys.exc_info(), file=TRACEBACK_FILE)
            raise SystemExit(1)
