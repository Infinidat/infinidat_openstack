"""openstack-infinibox-config

Usage:
    openstack-infinibox-config [options] list
    openstack-infinibox-config [options] set <address> <pool-name> <username> <password>
    openstack-infinibox-config [options] remove <address> <pool-name>
    openstack-infinibox-config [options] enable <key>
    openstack-infinibox-config [options] disable <key>
    openstack-infinibox-config -h | --help
    openstack-infinibox-config -v | --version


Options:
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --dry-run                            don't save changes
"""

import docopt
import sys
import os

CONFIGURATION_MODIFYING_KWARGS = ("add", "update", "remove", "enable", "disable")


def system_list(config_parser):
    from prettytable import PrettyTable
    from .config import get_systems, get_enabled_backends
    from infinipy import System
    systems = get_systems(config_parser)
    table = PrettyTable(["address", "pool name", "username", "enabled", "status"])
    backends = get_enabled_backends(config_parser)
    for system in systems:
        status = "connection successul"
        try:
            System(system['address'], username=system['username'], password=system['password']).get_name()
        except Exception, error:
            status = error.message
        table.add_row([system['address'], system['pool'], system['username'], system['key'] in backends, status])
    print table


def main(argv=sys.argv[1:]):
    from ..__version__ import __version__
    from . import config, exceptions
    from json import dumps
    arguments = docopt.docopt(__doc__, argv=argv, version=__version__)
    config_file = arguments['--config-file']
    write_on_exit = not arguments.get("--dry-run") or any(arguments[kwarg] for kwarg in CONFIGURATION_MODIFYING_KWARGS)
    if not os.path.exists(config_file):
        print "configuration file %s does not exist" % config_file, sys.stderr
        sys.exit(1)
    try:
        with config.get_config_parser(config_file, write_on_exit) as config_parser:
            if arguments['list']:
                return system_list(config_parser)
            elif arguments['set']:
                config.apply(config_parser, arguments['<address>'], arguments['<pool-name>'],
                             arguments['<username>'], argumentsp['<password>'])
            elif arguments['remove']:
                raise NotImplementedError()
            elif arguments['enable']:
                config.enable(config_parser, arguments['<key>'])
            elif arguments['disable']:
                config.disable(config_parser, arguments['<key>'])
    except exceptions.UserException, error:
        print error.message
        sys.exit(1)
