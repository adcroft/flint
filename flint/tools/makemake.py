"""flint gendoc command

:copyright: Copyright 2022 Marshall Ward, see AUTHORS for details.
:license: Apache License, Version 2.0, see LICENSE for details.
"""

import flint
import os
import time

subparser_params = {
    'description': '''Generates MAKEFILE with dependencies and rules for compiling and linking.

 - The link stage only links necessary object files.
 - An executable is assumed for each "program" encountered, and a target created
   in the makefile with the name following "program". Encountering multiple
   programs with same name causes an error.
 - Target "all:" lists all target executables.
''',
    'help': 'Generate a Makefile with dependencies and rules for compiling and linking',
    }

subparser_arguments = {
        ('--output', '-o'):
        {
            'action': 'store',
            'dest': 'makefile',
            'default': 'Makefile.dep',
            'help': 'Makefile to create (default: %(default)r)',
        },
        ('--fcline', '-f'):
        {
            'action': 'store',
            'dest': 'fcline',
            'default': '\t$(FC) $(FFLAGS) $(CPPFLAGS) -c $<',
            'help': 'Line(s) to used in Makefile to compile an source file (default: %(default)r)',
        },
        ('--ldline', '-l'):
        {
            'action': 'store',
            'dest': 'ldline',
            'default': '\t$(LD) -o $@ $^ $(LDFLAGS)',
            'help': 'Line(s) to used in Makefile to link object files (default: %(default)r)',
        },
        ('--executable', '-x'):
        {
            'action': 'store',
            'dest': 'executable',
            'default': None,
            'help': 'Name of target if only one program is provided. It is an error to specify this option with more than one program'
        },
        ('--timers', '-t'):
        {
            'action': 'store_true',
            'dest': 'timers',
            'default': False,
            'help': 'Report times taken for each stage of the processing. Informational only'
        }
    }

def __generate_link_list(objects, needed_for_link_by, obj_list=[], level=0):
    """Recursively follow through "needed_for_link_by" building a list of object files
    encountered, starting with "objects"."""
    if level<=99: # Avoid a complete run away in case of circular referencing
        for o in objects:
            if o not in obj_list:
                obj_list = obj_list + [ o ]
                if o in needed_for_link_by:
                    for n in needed_for_link_by[o]:
                        obj_list = __generate_link_list( [n], needed_for_link_by, obj_list, level+1 )
    return obj_list

class __Timer:
    def __init__(self, active=True):
        self.tic = time.time()
        self.active = active
    def toc(self, msg):
        """Write a message about time since last call that return tic"""
        t = time.time()
        if self.active: print('%f spent on %s'%(t-self.tic,msg))
        self.tic = t

def makemake(srcdirs, includes=None, excludes=None, makefile='Makefile.dep',
             fcline=None, ldline=None, executable=None, add_hfile_deps=True, timers=False):
    """Build "makefile" using "srcdirs".

    fcline - the commands to use to compile. Starts with tab character.
    ldline - the commands to link. Starts with tab character."
    executable - the name to give the executable if only one program is encountered.
    add_hfile_deps - find and add .h files to dependencies.
    """
    tic = __Timer(active=timers)

    # Parse all the source code
    project = flint.parse(*srcdirs, includes=includes, excludes=excludes)
    tic.toc("parsing source code")

    # Need to find location of .h files in srcdirs
    dot_h_paths = []
    for dir in srcdirs:
        for root, folders, files in os.walk(dir):
            for f in files:
                if f.endswith('.h'):
                    if root not in dot_h_paths:
                        dot_h_paths.append( root )
    includes_for_doth = ' '.join( '-I'+s for s in dot_h_paths ) # -Ia -Ib ...
    tic.toc("finding .h files")

    programs = {} # Dict of program -> object file
    src_to_obj = {} # Dict for source -> object
    modules_in_src = [] # List of modules created by all src
    object_file_for = {} # Dict of module/program -> object
    all_objs = [] # All objects

    # Create convenient list of external functions/modules (given in .name of project.externals)
    externals = []
    for e in project.externals:
        externals.append( e.name )
    tic.toc("collating external functions")

    with open(makefile, 'w') as ofile:
        print('# %s created by flint makemake'%(makefile), file=ofile)
        print('', file=ofile)

        # First pass
        # - find all programs (needed in order to have target "all:" at the top)
        for src in project.sources: # For each source file
            this_src = src.path
            this_obj = this_src.split('/')[-1].replace('.f90','.o').replace('.F90','.o') # object file
            src_to_obj[this_src] = this_obj
            assert this_obj not in all_objs, "%f would create an object file that already has a rule"%(this_src)
            all_objs.append( this_obj )

            for unit in src.units:
                if unit.utype == 'program':
                    assert unit.name not in programs, "program name %s from %s has already been seen"%(unit.name,this_src)
                    programs[unit.name] = this_obj
                if unit.utype == 'module':
                    assert unit.name.lower() not in modules_in_src, "module name %s from %s has already been defined"%(unit.name.lower(),this_src)
                    modules_in_src.append( unit.name.lower() )
        tic.toc("listing programs and modules")

        # Create target "all:"
        if executable is not None:
            assert len(programs)<2, "Option --executable was given but %i programs were found in source"%(len(programs))
            programs[executable] = programs.pop(list(programs.keys())[0]) # Replace key with "a.out"
        print('all:', ' '.join(['%s'%p for p in programs]), file=ofile)
        print('', file=ofile)
        tic.toc('writing target "all:"')

        # Second pass
        # - generate .o.src rules
        # - generate .o.mod rules
        # - populate dictionaries in order to create list of objects to link with
        modules_used_by_object = {} # Dict of object file -> list[names of modules used]
        externals_used_by_object = {} # Dict of object file -> list[names of external fns]
        for src in project.sources: # For each source file
            this_src = src.path
            this_obj = src_to_obj[this_src]
            uses_modules = []
            uses_externals = []
            modules_provided = []

            for unit in src.units:
                if unit.utype == 'module':
                    assert unit.name.lower() not in modules_provided, "module name %s from %s has already been defined"%(unit.name.lower(),this_src)
                    modules_provided.append( unit.name.lower() )
                    object_file_for[unit.name.lower()] = this_obj

                if unit.used_modules:
                    for m in unit.used_modules:
                        if m.lower() in modules_in_src:
                            uses_modules.append( m.lower() )

                if unit.subprograms:
                    for sub in unit.subprograms:
                        if sub.callees:
                            for c in sub.callees:
                                if c in externals:
                                    uses_externals.append( c )

                        if sub.name in externals:
                            assert c not in object_file_for, "external fn %s from %s has already been defined"%(c,this_src)
                            object_file_for[c] = this_obj

                if unit.name in externals:
                    assert unit.name not in object_file_for, "external fn %s from %s has already been defined"%(unit.name,this_src)
                    object_file_for[unit.name] = this_obj

            if uses_modules:
                modules_used_by_object[this_obj] = uses_modules
            if uses_externals:
                externals_used_by_object[this_obj] = uses_externals

            # Write rule for this source file
            if modules_provided: # This rule serializes the dependencies following https://www.gnu.org/software/automake/manual/1.15.1/html_node/Multiple-Outputs.html
                print(' '.join(['%s.mod'%m for m in modules_provided])+':', '%s'%(this_obj), file=ofile)
            print('%s: %s'%(this_obj,this_src), end='', file=ofile) # this object is produced by this source file ...
            if add_hfile_deps: # ... and depends on these .h files ...
                lib_cpp_out = os.popen( f"/lib/cpp -E -M {includes_for_doth} {this_src}" ).read().replace('\\','').replace('\n',' ').split()
                if len(lib_cpp_out)>3: # (ignore .o: .F90 std-lib in output from /lib/cpp)
                    print('',' '.join(lib_cpp_out[3:]), end='', file=ofile)
            if uses_modules: # ... and on these module files
                print(''.join([' %s.mod'%m for m in uses_modules]), end='', file=ofile)
            print('', file=ofile)
            print(fcline, includes_for_doth, file=ofile)
        tic.toc("writing .o.F rules")

        # Third pass
        # - create dictionary object file -> object files for modules and externals used by the key object file
        needed_for_link_by = {}
        for this_obj in src_to_obj.values():
            objects = [] # objects this_obj needs at link time

            if this_obj in modules_used_by_object:
                for m in modules_used_by_object[this_obj]:
                    if m in object_file_for:
                        o = object_file_for[m]
                        if o not in objects:
                            objects.append( o )
            if this_obj in externals_used_by_object:
                for e in externals_used_by_object[this_obj]:
                    if e in object_file_for:
                        o = object_file_for[e]
                        if o not in objects:
                            objects.append( o )

            needed_for_link_by[this_obj] = objects
        tic.toc("constructing tree of .o and .mod files")

        # Rules for executable targets with objects to link to
        print('', file=ofile)
        for prog in programs:
            lst = __generate_link_list([object_file_for[prog]], needed_for_link_by)
            print('%s:'%prog,' '.join(['%s'%o for o in lst]), file=ofile)
            print(ldline, file=ofile)
        tic.toc("writing link rules")

        # Cleanup rules
        print('', file=ofile)
        print('clean:', file=ofile)
        print('\trm -f *.o *.mod', file=ofile)
