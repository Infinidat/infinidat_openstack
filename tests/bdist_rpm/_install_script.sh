pushd .
cd $PROJECTDIR
bin/python tests/bdist_rpm/_install_script.py
popd
cp $PROJECTDIR/INSTALLED_FILES .
