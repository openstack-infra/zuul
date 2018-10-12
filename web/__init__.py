# This file is here because without it python setup.py bdist_wheel does not
# pick up the built javascript files in zuul/web/static. It does not cause
# web/ itself to be put into the wheel, but without it built wheels do not
# have the built javascript files.
