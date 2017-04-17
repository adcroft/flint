from flint.construct import Construct


class Unit(object):
    unit_types = [
        'program',
        'function',
        'subroutine',
        'module',
        'submodule',
        'block',
    ]

    # TODO: Will probably move all this to a Types class...
    intrinsic_types = [
        'integer',      # R405
        'real',         # R404
        'double',       # R404 (DOUBLE PRECISION)
        'complex',      # R404
        'character',    # R404
        'logical',      # R404
    ]

    attribute_specs = [
        'codimension',
        'contiguous',
        'dimension',
        'external',
        'intent',
        'namelist',
        'optional',
        'pointer',
        'protected',
        'save',
        'target',
        'volatile',
        'value',
        'common',       # Deprecated
        'equivalence',  # Deprecated
    ]

    declaration_types = intrinsic_types + attribute_specs + [
        'type',         # R426, R403
        'enum',         # R459 ("ENUM, BIND(C)")
        'generic',      # R1210
        'interface',    # R1201
        'parameter',    # R551
        'procedure',    # R1213: Procedure declaration statement
        'data',         # R537
        'format',       # R1001
        'entry',        # R1242 (obsolete)
    ]

    unit_prefix = intrinsic_types + [
        'elemental',
        'impure',
        'non_recursive',
        'pure',
        'recursive',
    ]

    def __init__(self):
        self.name = None
        self.utype = None

    @staticmethod
    def statement(line):
        # TODO: If this ends up being a full type-statement parser, then it
        # needs to be moved into its own class
        idx = next((i for i, w in enumerate(line) if w in Unit.unit_types), -1)

        if idx == 0:
            return True
        elif idx > 0:
            words = iter(line[:idx])

            word = next(words)
            while True:
                try:
                    if word in Unit.intrinsic_types:
                        word = next(words)
                        if word == '(':
                            # TODO: Parse this more formally
                            while word != ')':
                                word = next(words)
                    elif word not in Unit.unit_prefix:
                        return False

                    word = next(words)
                except StopIteration:
                    break
            return True

        else:
            return False

    def end_statement(self, line):
        assert self.utype

        # TODO: Very similar to construct... can I merge somehow?
        if line[0].startswith('end'):
            if len(line) == 1 and line[0] in ('end', 'end' + self.utype):
                return True
            elif len(line) >= 2 and (line[0], line[1]) == ('end', self.utype):
                return True
            else:
                return False

    def parse(self, lines):
        """Parse the lines of a program unit.

        Program units are generally very similar, but we leave it undefined
        here due to some slight differences.
        """
        self.parse_name(lines.current_line)
        self.parse_specification(lines)
        self.parse_execution(lines)
        self.parse_subprogram(lines)

        # Finalisation
        print('{}: {}'.format(self.utype[0].upper(),
                              ' '.join(lines.current_line)))

    def parse_name(self, line):
        """Parse the name of the program unit, if present.

        Each program unit has a different header format, so this method must be
        overridden by each subclass.
        """
        self.utype = next(w for w in line if w in Unit.unit_types)

        if len(line) >= 2:
            self.name = line[1]
        else:
            self.name = None

        print('{}: {} '.format(self.utype[0].upper(), ' '.join(line)))

    # Specification

    def parse_specification(self, lines):
        """Parse the specification part (R204) of a program unit (R202).

        Specification parts contain the following:

        1. USE statements (R1109)
        2. IMPORT statements (R1211)
        3. IMPLICIT statements (R205)
        4. Declaration constructs (R207)
        """
        # TODO: `use`, `implicit`, and declarations must appear in that order.
        #       This loop does not check order.
        for line in lines:
            if line[0] == 'use':
                self.parse_use_stmt(line)
            elif line[0] == 'import':
                self.parse_import_stmt(line)
            elif line[0] in 'implicit':
                # TODO: PARAMETER, FORMAT, ENTRY
                self.parse_implicit_stmt(line)
            elif line[0] in Unit.declaration_types:
                self.parse_declaration_construct(line)
            else:
                break

    def parse_use_stmt(self, line):
        """Parse the use statement (R1109) within a specification (R204)."""
        print('U: {}'.format(' '.join(line)))

    def parse_import_stmt(self, line):
        print('i: {}'.format(' '.join(line)))

    def parse_implicit_stmt(self, line):
        print('I: {}'.format(' '.join(line)))

    def parse_declaration_construct(self, line):
        print('D: {}'.format(' '.join(line)))

    # Execution

    def parse_execution(self, lines):
        # First parse the line which terminated specification
        # TODO: How to merge with iteration below?

        line = lines.current_line

        if Construct.statement(line):
            cons = Construct()
            cons.parse(lines)
        elif self.end_statement(line) or line[0] == 'contains':
            return
        else:
            # Unhandled
            print('E: {}'.format(' '.join(line)))

        # Now iterate over the rest of the lines
        for line in lines:
            # Execution constructs
            if Construct.statement(line):
                cons = Construct()
                cons.parse(lines)
            elif self.end_statement(line) or line[0] == 'contains':
                # TODO: Use return?
                break
            else:
                # Unhandled
                print('E: {}'.format(' '.join(line)))

    def parse_subprogram(self, lines):
        # TODO: I think the first line of subprogram is always CONTAINS, so
        # this check may be pointless.

        line = lines.current_line

        if Unit.statement(line):
            subprog = Unit()
            subprog.parse(lines)
        elif self.end_statement(line):
            return
        else:
            print('{}: {}'.format(self.utype[0].upper(), ' '.join(line)))

        for line in lines:
            if Unit.statement(line):
                subprog = Unit()
                subprog.parse(lines)
            elif self.end_statement(line):
                # TODO: Use return?
                break
            else:
                print('X: {}'.format(' '.join(line)))
