Overview
========
This is an Infinidat project.

Usage
-----
Nothing to use here.

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
