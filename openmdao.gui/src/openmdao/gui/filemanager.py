import os.path
import shutil
import traceback
import zipfile

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, PatternMatchingEventHandler

from openmdao.gui.util import filedict
from openmdao.main.publisher import Publisher
from openmdao.util.log import logger


# FIXME: The pattern matching bit seems to be causing random errors
#        See Pivotal story # 39063129
#        It has been disabled until the error can be investigated and fixed

#class FilesPublisher(PatternMatchingEventHandler):
#    ''' publishes file collection when ANY file system event occurs
#    '''

#    def __init__(self, files):
#        super(FilesPublisher, self).__init__(
#                ignore_patterns=[
#                    "*/_macros/*",
#                    "*.pyc", "*.pyd"])

#        self.files = files
#
#    def on_any_event(self, event):
#        ''' publishes file collection when ANY file system event occurs
#        '''

#        try:
#            self.files.publish_files()
#        except Exception:
#            traceback.print_exc()


class FilesPublisher(FileSystemEventHandler):
    ''' Publishes file collection when ANY file system event occurs.
    '''

    def __init__(self, files):
        self.files = files

    def dispatch(self, event):
        ''' Just publish the updated file collection.
        '''
        try:
            self.files.publish_files()
        except Exception:
            traceback.print_exc()


class FileManager(object):
    ''' Object that keeps track of a collection of files (i.e., a directory)
        and optionally publishes an update when the collection is modified.
    '''

    def __init__(self, name, path, publish_updates=False):
        self.name = name

        self.orig_dir = os.getcwd()
        self.root_dir = path

        self.publish_updates = publish_updates
        self.publisher = None

        if self.publish_updates:
            self.observer = Observer()
            self.observer.daemon = True
            self.observer.schedule(FilesPublisher(self),
                                   path=self.root_dir,
                                   recursive=True)
            self.observer.start()
        else:
            self.observer = None

    def publish_files(self):
        ''' Publish the current file collection.
        '''
        if not self.publisher:
            try:
                self.publisher = Publisher.get_instance()
            except Exception, err:
                print 'Error getting publisher:', err
                self.publisher = None

        if self.publisher:
            self.publisher.publish(self.name, self.get_files())

    def cleanup(self):
        ''' Stop observer and cleanup the file directory.
        '''
        if self.observer:
            self.observer.unschedule_all()
            self.observer.stop()
            self.observer.join()
        os.chdir(self.orig_dir)

    def get_files(self, root=None):
        ''' Get a nested dictionary of files in the working directory.
        '''
        if root is None:
            cwd = self.root_dir
        else:
            cwd = root
        return filedict(cwd)

    def _get_abs_path(self, name):
        '''Return the absolute pathname of the given file/dir.
        '''
        return os.path.join(self.root_dir, str(name).lstrip('/'))

    def get_file(self, filename):
        ''' Get contents of file in working directory.
            Returns None if file was not found.
        '''
        filepath = self._get_abs_path(filename)
        if os.path.exists(filepath):
            contents = open(filepath, 'rb').read()
            return contents
        else:
            return None

    def ensure_dir(self, dirname):
        ''' Create directory in working directory.
            (Does nothing if directory already exists.)
        '''
        try:
            dirpath = self._get_abs_path(dirname)
            if not os.path.isdir(dirpath):
                os.makedirs(dirpath)
            return str(True)
        except Exception, err:
            return str(err)

    def write_file(self, filename, contents):
        ''' Write contents to file in working directory.
        '''
        try:
            filename = str(filename)
            fpath = self._get_abs_path(filename)
            if filename.endswith('.py'):
                initpath = os.path.join(os.path.dirname(fpath), '__init__.py')
                files = os.listdir(os.path.dirname(fpath))
                # FIXME: This is a bit of a kludge, but for now we only create
                # an __init__.py file if it's the very first file in the
                # directory where a new file is being added.
                if not files and not os.path.isfile(initpath):
                    with open(initpath, 'w') as f:
                        f.write(' ')
            with open(fpath, 'wb') as fout:
                fout.write(contents)
            return True
        except Exception, err:
            logger.error(str(err))
            return err

    def add_file(self, filename, contents):
        ''' Add file to working directory.
            If it's a zip file, unzip it.
        '''
        self.write_file(filename, contents)
        fpath = self._get_abs_path(filename)
        if zipfile.is_zipfile(fpath):
            userdir = self.root_dir
            zfile = zipfile.ZipFile(fpath, "r")
            zfile.printdir()
            for fname in zfile.namelist():
                if fname.endswith('/'):
                    dirname = userdir + '/' + fname
                    if not os.path.exists(dirname):
                        os.makedirs(dirname)
            for fname in zfile.namelist():
                if not fname.endswith('/'):
                    data = zfile.read(fname)
                    fname = userdir + '/' + fname
                    fname = fname.replace('\\', '/')
                    fout = open(fname, "wb")
                    fout.write(data)
                    fout.close()
            zfile.close()
            os.remove(fpath)

    def delete_file(self, filename):
        ''' Delete file in working directory.
            Returns False if file was not found; otherwise, returns True.
        '''
        filepath = self._get_abs_path(filename)
        if os.path.exists(filepath):
            if os.path.isdir(filepath):
                shutil.rmtree(filepath)
            else:
                os.remove(filepath)
            return True
        else:
            return False

    def rename_file(self, oldpath, newname):
        ''' Rename last component of `oldpath` to `newname`.
        '''
        filepath = self._get_abs_path(oldpath)
        if os.path.exists(filepath):
            newpath = os.path.join(os.path.dirname(filepath), newname)
            os.rename(filepath, newpath)
            return True
        else:
            return False

