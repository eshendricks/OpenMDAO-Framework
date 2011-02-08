"""
Routines for handling 'projects' in python.
"""

import os
import sys
import inspect
import tarfile
import cPickle as pickle

from pkg_resources import get_distribution, DistributionNotFound

from openmdao.util.fileutil import get_module_path

class Project(object):
    def __init__(self, projpath):
        self.path = projpath
        self.files = set()
        self.top = None
        
    @property
    def name(self):
        return os.path.basename(self.path)
    
    def add_file(self, name):
        if os.path.exists(name):
            self.files.add(name)
        else:
            raise IOError("File %s does not exist" % name)
        
    def remove_file(self, name):
        if name in self.files:
            self.files.remove(name)
        else:
            raise KeyError("File %s is not a member of this project" % name)
    
    def activate(self):
        """Puts this project's directory on sys.path."""
        if self.path not in sys.path:
            sys.path = [self.path]+sys.path
        
    def deactivate(self):
        """Removes this project's directory from sys.path."""
        try:
            sys.path.remove(self.path)
        except:
            pass

    def save(self):
        """Saves the state of the project to its project directory."""
        fname = os.path.join(self.path, '_project_state')
        pickle.dump(self.__dict__, fname)
    
    @staticmethod
    def load(dirname, archive_name=None):
        """Returns a Project object containing the project found in the 
        specified directory or archive file.  If archive_name is not None
        then dirname is assumed to be the parent directory where the archive
        will be expanded.  If archive_name is None then dirname is assumed
        to be the name of the directory containing the project to be loaded.
        """
        # if we're dealing with an archive file, extract it inside of dirname
        if archive_name is not None:
            with tarfile.open(archive_name) as tf:
                tf.extractall(dirname)
                projname = os.path.basename(archive_name).split('.')[0]
                if not os.path.isdir(os.path.join(dirname, projname)):
                    raise IOError("No %s directory was found after expansion of archive %s" % (projname,archive_name))
            projpath = os.path.join(dirname, projname)
        else:
            projname = os.path.basename(dirname)
            projpath = dirname
            
        # locate the state file containing the state of the project
        statefile = os.path.join(projpath, '_project_state')
        if not os.path.isfile(statefile):
            raise IOError("Can't find state file for project in %s" % projpath)
        
        proj = Project(projpath)
        proj.activate()
        with open(statefile, 'r') as f:
            proj.__dict__ = pickle.load(f)
        proj.path = projpath  # could be different than the one we loaded
                
        return proj
    
def find_distrib_for_obj(obj):
    """Return the name of the distribution containing the module that
    contains the given object, or None if it's not part of a distribution.
    """
    try:
        fname = inspect.getfile(obj)
    except TypeError:
        return None
    
    modpath = get_module_path(fname)
    parts = modpath.split('.')
    l = len(parts)
    for i in range(l):
        try:
            dist = get_distribution('.'.join(parts[:l-i]))
        except DistributionNotFound:
            continue
        return dist
    return None
    
    
def model_to_class(model, classname, stream):
    """Takes a model and creates a new class inherited from the model's
    class that is initialized with the current model's non-default
    configuration.  The class definition is written to the given stream.
    Note that this does not save the exact state of the model, but only
    key inputs and attributes recommended by the model and its children.
    """
    cfg = model.get_configinfo()
    cfg.save_as_class(stream, classname)

def model_to_package(model, classname, version, destdir='.'):
    startdir = os.getcwd()
    try:
        os.chdir(destdir)
        pkgname = classname.lower()
        os.makedirs(os.path.join(pkgname, pkgname))
        fname = os.path.join(pkgname, pkgname, "%s.py" % pkgname)
        with open(fname, 'w') as f:
            model_to_class(model, classname, f)
        make_pkg('.', classname, version=version)
    finally:
        os.chdir(startdir)

def create_setup_py_file(stream, header='', footer='', **kwargs):
    """Writes the contents of a setup.py file to the given stream.
    kwargs contains options to the setup command. Entries of
    'name' (the distribution name) and 'version' are required. Others
    (desc,author,author_email,license,url,depends,entrypts) are optional.
    """
    
    setuptemplate = '''
from setuptools import setup

setup(
    name='%(name)s',
    version='%(version)s',
    description='%(desc)s',
    author='%(author)s',
    author_email='%(author_email)s',
    license='%(license)s',
    url='%(url)s',
    packages=['%(name)s'],
    zip_safe=%(zipped)s,
    install_requires=%(depends)s,
    entry_points=%(entrypts)s
)

   '''
    
    setupdict = { 'name': kwargs['name'],
                  'version': kwargs['version'],
                  'desc': kwargs.get('desc', ''),
                  'author': kwargs.get('author', ''),
                  'author_email': kwargs.get('author_email', ''),
                  'license': kwargs.get('license', ''),
                  'url': kwargs.get('url', ''),
                  'entrypts': kwargs.get('entrypts', {}),
                  'zipped': False,
                  'depends': kwargs.get('depends',[]),
                  }
    
    stream.write("%s\n" % header)
    stream.write(setuptemplate % setupdict)
    stream.write("\n%s\n" % footer)
    
def new_project(destdir, name, version='0.0.1', 
                base='openmdao.main.assembly.Assembly', **kwargs):
    """Creates a directory structure, default setup.py file, and __init__.py
    file in the specified destination directory for a project (python package)
    with the given name. Optional keyword arguments to the setup call can be
    supplied in kwargs.
    """
    if not os.path.exists(destdir):
        raise IOError("destination directory '%s' doesn't exist" % destdir)
    pkgname = name.lower()
    os.makedirs(os.path.join(destdir, pkgname, pkgname))
    header = """
    # GENERATED FILE - DO NOT EDIT!
    """
    kwargs['name'] = pkgname
    kwargs['version'] = version
    with open(os.path.join(destdir, pkgname, 'setup.py'), 'w') as f:
        create_setup_py_file(f, header, **kwargs)
    with open(os.path.join(destdir, pkgname, pkgname, '%s.py' % pkgname), 'w') as f:
        module, cname = base.rsplit('.', 1)
        f.write("""
from %s import %s

class %s(%s):
    pass
    
        """ % (module, cname, name, cname))
    with open(os.path.join(destdir, pkgname, pkgname, '__init__.py'), 'w') as f:
        f.write("""
from %s import %s
        """ % (pkgname, name))

def update_package(pkgpath, **kwargs):
    """Updates the setup.py file in the package with the given location.
    Options to the setup call inside of setup.py can be passed in kwargs.
    """
    destdir, pkgname = os.path.split(pkgpath)
    
    # find plugins and create entry points
    sta = PythonSourceTreeAnalyser(startdir=pkgpath, excludes=['setup.py'])
    drivers = sta.find_inheritors('openmdao.main.driver.Driver')
    comps = sta.find_inheritors('openmdao.main.component.Component')
    comps = list(set(comps)-set(drivers))
    drv_entrypts = []
    comp_entrypts = []
    for drv in drivers:
        parts = drv.split('.')
        drv_entrypts.append("%s=%s:%s" % (drv,'.'.join(parts[:-1]),parts[-1]))
    for comp in comps:
        parts = comp.split('.')
        comp_entrypts.append("%s=%s:%s" % (comp,'.'.join(parts[:-1]),parts[-1]))
    if drv_entrypts:
        setupdict['entrypts']['openmdao.drivers'] = drv_entrypts
    if comp_entrypts:
        setupdict['entrypts']['openmdao.components'] = comp_entrypts
        
    print 'done'