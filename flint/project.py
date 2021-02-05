import os
import sys

from flint.source import Source
from flint.units import Module

class Project(object):

    def __init__(self, verbose=False):
        self.verbose = verbose

        # Source code
        self.path = None
        self.directories = []
        self.files = []

        # Program structure
        self.modules = []

    # TODO: *paths is generally a bad idea for a public API.  I am only using
    #   it here to get sensible output in my MOM6 tests.
    # TODO: `exclude` may prove more useful here.
    def parse(self, *paths):
        filepaths = []
        for path in paths:
            assert os.path.isdir(path)
            self.path = path

            for root, dirs, files in os.walk(self.path):
                self.directories.append(root)

                for fname in files:
                    fpath = os.path.join(root, fname)
                    if os.path.splitext(fname)[1] in ('.f90', '.F90'):
                        filepaths.append(fpath)
                    else:
                        print('SKIP file: {}'.format(fpath))

        for fpath in filepaths:
            f90file = Source(project=self, verbose=self.verbose)
            f90file.parse(fpath)
            self.files.append(f90file)

        # Generate list of modules
        for src in self.files:
            for unit in src.units:
                if isinstance(unit, Module):
                    self.modules.append(unit)
