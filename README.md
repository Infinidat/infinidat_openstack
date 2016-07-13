Overview
========
This project implements the InfiniBox Cinder Driver.


Checking out the code
=====================

Run the following:

    easy_install -U infi.projector
    projector devenv build


testing
=======

- bdist_rpm tests should be run before running the other tests,
  since they build the rpm which is used by the other tests.
- If you edit anything in the code, you have to commit (not push),
  otherwise your newest code won't be built (the bdist_rpm test uses git)


# Running DevStack on Ubuntu

    jfab openstack_devstack.install:stable/kilo -H localhost
    jfab openstack_devstack.reset_admin_password  -H localhost
    sudo -u stack screen -r

