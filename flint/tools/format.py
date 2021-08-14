"""flint format command

:copyright: Copyright 2021 Marshall Ward, see AUTHORS for details.
:license: Apache License, Version 2.0, see LICENSE for details.
"""
from flint.project import Project
from flint.statement import Statement


def format_statements(srcdirs, includes=None, excludes=None):
    proj = Project()
    if includes:
        proj.include_dirs += includes

    proj.parse(*srcdirs, excludes=excludes)

    for src in proj.sources:
        for stmt in src.statements:
            print(stmt.reformat())
