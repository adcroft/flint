from flint.calls import get_callable_symbols
from flint.construct import Construct
from flint.document import is_docstring, docstrip, Document
from flint.interface import Interface
from flint.intrinsics import intrinsic_fns
from flint.report import Report
from flint.statement import Statement
from flint.variable import Variable


class Unit(object):
    unit_types = [
        'program',
        'function',
        'subroutine',
        'module',
        'submodule',
        'block',
        # XXX: Currently `type` shares enough with program units to justify its
        # presence here.  But it should not be here.
        'type',
    ]

    # R507 access-spec
    access_specs = [
        'public',
        'private',
    ]

    # R502 attr-spec
    attribute_specs = access_specs + [
        'allocatable',
        'asynchronous',
        'codimension',
        'contiguous',
        'dimension',
        'external',
        'intent',
        'intrinsic',
        'namelist',     # NOTE: Not an attribute...
        # language-binding-spec
        'optional',
        'pointer',
        'protected',
        'save',
        'target',
        'value',
        'volatile',
        'common',       # Deprecated
        'equivalence',  # Deprecated
    ]

    declaration_types = Variable.intrinsic_types + attribute_specs + [
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

    unit_prefix = Variable.intrinsic_types + [
        'elemental',
        'impure',
        'non_recursive',
        'pure',
        'recursive',
    ]

    def __init__(self, report=None):
        self.name = None
        self.utype = None
        self.debug = False

        self.subprograms = []
        self.variables = []
        self.interfaces = []
        self.derived_types = []
        self.namelists = {}
        self.report = report if report else Report()

        # Call tree properties
        self.used_modules = set()
        self.callees = set()
        self.callers = set()

        self.doc = Document()
        # XXX: Does this need to be here?
        self.grp_docstr = None

        # Testing
        self.statements = []

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
                    if word in Variable.intrinsic_types:
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

    # Call graph construction

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
        # Parse program unit statements
        self.parse_header(lines.current_line)
        self.parse_specification(lines)
        self.parse_execution(lines)
        self.parse_subprogram(lines)

        # Remove intrinsic functions from the set of callables
        self.callees = self.callees - set(intrinsic_fns)

        # Finalisation
        stmt = Statement(lines.current_line, tag=self.utype[0].upper())
        self.statements.append(stmt)

        self.doc.footer = docstrip(lines.current_line[0].head, oneline=False)

    def parse_header(self, line):
        """Parse the name of the program unit, if present.

        Each program unit has a different header format, so this method must be
        overridden by each subclass.
        """
        try:
            self.utype = next(w for w in line if w in Unit.unit_types)
        except StopIteration:
            print(line)
            raise

        self.doc.header = docstrip(line[0].head)
        self.doc.docstring = docstrip(line[-1].tail)
        self.doc.statement = line

        # TODO: A safer approach may be to formally parse the first non-unit
        # type as a variable type.  A temporary step is to split the
        # declaration into its (potential) output type and the rest.
        # But for now we just grab the name and ignore the rest.
        # TODO: Could also be that `function` is the only one that is not
        # the first character...
        utype_idx = line.index(self.utype)

        if len(line) >= 2:
            self.name = line[utype_idx + 1]
        else:
            self.name = None

        stmt = Statement(line, tag=self.utype[0].upper())
        self.statements.append(stmt)

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
            elif line[0] == 'implicit':
                # TODO: PARAMETER, FORMAT, ENTRY
                self.parse_implicit_stmt(line)
            elif line[0] in Unit.declaration_types:
                self.parse_declaration_construct(lines, line)
            else:
                break

    def parse_use_stmt(self, line):
        """Parse the use statement (R1109) within a specification (R204)."""
        idx = 1
        if line[idx] == ',':
            idx = idx + 2
        if line[idx] == '::':
            idx = idx + 1

        self.used_modules.add(line[idx])

        stmt = Statement(line, tag='U')
        self.statements.append(stmt)

    def parse_import_stmt(self, line):
        stmt = Statement(line, tag='i')
        self.statements.append(stmt)

    def parse_implicit_stmt(self, line):
        stmt = Statement(line, tag='I')
        self.statements.append(stmt)

    def parse_declaration_construct(self, lines, line):
        if line[0] == 'interface' or (
                len(line) > 1 and line[:2] == ('abstract', 'interface')
            ):
            block = Interface()
            block.parse(lines)
            self.interfaces.append(block)
            self.statements.append(block.statements)

        # TODO: Parse out type
        elif (line[0] == 'enum' or (line[0] == 'type' and line[1] != '(')):
            dtype = Unit()
            dtype.parse(lines)

            # TODO: I think this is OK, since these are never defined as
            #   comma-separated lists, but need to check into this
            dtype.name = line[-1]
            self.derived_types.append(dtype)
            self.statements.append(dtype.statements)

        elif line[0] in Unit.access_specs:
            stmt = Statement(line, tag='d')
            self.statements.append(stmt)

        # R357 (placeholder)
        elif line[0] == 'data':
            stmt = Statement(line, tag='d')
            self.statements.append(stmt)

        # R551 (placeholder)
        elif line[0] == 'parameter':
            stmt = Statement(line, tag='p')
            self.statements.append(stmt)

        else:
            tokens = iter(line)

            tok = next(tokens)

            # Check for any group tokens
            # XXX: This probably should only happen for intrinsics and type/class
            if (is_docstring(tok.head)
                    and any(tok.startswith('!>@{') for tok in tok.head)
                ):
                # XXX: Use [2:] to strip '{ ', maybe do this in docstrip...?
                self.grp_docstr = docstrip(tok.head)[2:]

            if tok in Variable.intrinsic_types:
                vtype = tok
            elif tok in ('type', 'class'):
                assert next(tokens) == '('
                vtype = next(tokens)
                assert next(tokens) == ')'
            elif tok == 'namelist':
                self.parse_namelist(line)
                return
            else:
                # Unhandled
                stmt = Statement(line, tag='X')
                self.statements.append(stmt)
                return

            # Character length parsing
            tok = next(tokens)
            if vtype == 'character':
                if tok == '*':
                    tok = next(tokens)

            # Kind (or len) statement
            if tok == '(':
                while tok != ')':
                    tok = next(tokens)
                tok = next(tokens)

            # Attributes

            # Set defaults
            var_intent = None

            while tok == ',':
                tok = next(tokens)
                attr = tok

                if attr == 'intent':
                    tok = next(tokens)
                    assert tok == '('
                    var_intent = next(tokens)
                    assert var_intent in ('in', 'out', 'inout')
                    tok = next(tokens)

                    # Fortran permits a space between `inout`, so check the
                    # next token.  (NOTE: `out in` is not allowed!)
                    if var_intent == 'in' and tok == 'out':
                        var_intent += tok
                        tok = next(tokens)

                    assert tok == ')'

                # TODO: We mostly skip over this information
                elif attr == 'dimension':
                    tok = next(tokens)
                    assert tok == '('
                    par_count = 1
                    while par_count > 0:
                        tok = next(tokens)
                        if tok == '(':
                            par_count += 1
                        elif tok == ')':
                            par_count -= 1

                tok = next(tokens)

            if tok == '::':
                tok = next(tokens)

            var = Variable(tok, vtype)
            var.intent = var_intent

            # First doc attempt: After the variable name
            #   Also, attempt to apply the group docstring if it's been set
            #if is_docstring(tok.tail):
            if is_docstring(tok.tail) and not any(dtok.startswith('!>@}') for dtok in tok.tail):
                var.doc.docstring = docstrip(tok.tail)
            elif self.grp_docstr:
                var.doc.docstring = self.grp_docstr

            self.variables.append(var)

            for tok in tokens:
                if tok == '(':
                    while tok != ')':
                        tok = next(tokens)

                # Second doc attempt: After the index right parenthesis
                #if is_docstring(tok.tail):
                if is_docstring(tok.tail) and not any(dtok.startswith('!>@}') for dtok in tok.tail):
                    self.variables[-1].doc.docstring = docstrip(tok.tail)
                elif self.grp_docstr:
                    var.doc.docstring = self.grp_docstr

                if tok == ',':
                    # Third doc attempt: After the comma
                    # XXX: Can this one be removed?
                    #if is_docstring(tok.tail):
                    if is_docstring(tok.tail) and not any(dtok.startswith('!>@}') for dtok in tok.tail):
                        self.variables[-1].doc.docstring = docstrip(tok.tail)
                    elif self.grp_docstr:
                        var.doc.docstring = self.grp_docstr

                    try:
                        tok = next(tokens)
                    except StopIteration:
                        self.report.error_endcomma()

                    var = Variable(tok, vtype)
                    var.intent = var_intent
                    if is_docstring(tok.tail):
                        var.doc.docstring = docstrip(tok.tail)
                    self.variables.append(var)

            # Clear the group docstring
            if (is_docstring(line[-1].tail)
                    and any(dtok.startswith('!>@}') for dtok in line[-1].tail)
                ):
                self.grp_docstr = None

            stmt = Statement(line, tag='D')
            self.statements.append(stmt)

    def parse_namelist(self, line):
        assert(line[0] == 'namelist')
        tokens = iter(line[1:])

        tok = next(tokens)
        while tok:
            assert tok == '/'
            # TODO: Validate group name
            nml_group = next(tokens)
            self.namelists[nml_group] = []
            assert next(tokens) == '/'

            tok = next(tokens)
            while tok and tok != '/':
                # TODO: Validate object name
                self.namelists[nml_group].append(tok)
                tok = next(tokens, None)
                assert tok in (',', '/', None)
                if tok == ',':
                    tok = next(tokens)

        stmt = Statement(line, tag='N')
        self.statements.append(stmt)

    # Execution

    def parse_execution(self, lines):
        # TODO: The val = fn(...) test for self.callees is very speculative...

        line = lines.current_line

        # Gather up any callable symbols
        var_names = [v.name for v in self.variables]
        self.callees.update(get_callable_symbols(line, var_names))

        # First parse the line which terminated specification
        # TODO: How to merge with iteration below? Lookahead in parse_spec()?
        if Construct.statement(line):
            cons = Construct(self)
            cons.parse(lines)
            self.statements.append(cons.statements)
        elif self.end_statement(line) or line[0] == 'contains':
            return
        else:
            # Unhandled
            stmt = Statement(line, tag='E')
            self.statements.append(stmt)

        # Now iterate over the rest of the lines
        for line in lines:
            self.callees.update(get_callable_symbols(line, var_names))

            # Execution constructs
            if Construct.statement(line):
                cons = Construct(self)
                cons.parse(lines)
                self.statements.append(cons.statements)
            elif self.end_statement(line) or line[0] == 'contains':
                # TODO: Use return?
                break
            else:
                # Unhandled
                stmt = Statement(line, tag='E')
                self.statements.append(stmt)

    def parse_subprogram(self, lines):
        # TODO: I think the first line of subprogram is always CONTAINS, so
        # this check may be pointless. (No, not for interfaces)

        line = lines.current_line

        if Unit.statement(line):
            subprog = Unit()
            subprog.parse(lines)
            self.subprograms.append(subprog)
            self.statements.append(subprog.statements)
        elif self.end_statement(line):
            return
        else:
            stmt = Statement(line, tag=self.utype[0].upper())
            self.statements.append(stmt)

        for line in lines:
            if Unit.statement(line):
                subprog = Unit()
                subprog.parse(lines)
                self.subprograms.append(subprog)
                self.statements.append(subprog.statements)
            elif self.end_statement(line):
                # TODO: Use return?
                break
            else:
                stmt = Statement(line, tag='X')
                self.statements.append(stmt)
