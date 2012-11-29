# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/server/__init__.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright © 2012 Matthew W. Samsonoff <matthew.samsonoff@makerbot.com>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import collections
import errno
import lockfile
import lockfile.pidlockfile
import logging
import makerbot_driver
import os
import os.path
import signal
import sys
import threading

try:
    import unittest2 as unittest
except ImportError:
    import unittest

import conveyor.address
import conveyor.connection
import conveyor.domain
import conveyor.jsonrpc
import conveyor.main
import conveyor.machine.s3g
import conveyor.recipe
import conveyor.slicer.miraclegrue
import conveyor.slicer.skeinforge
import conveyor.stoppable

class ServerMain(conveyor.main.AbstractMain):
    def __init__(self):
        conveyor.main.AbstractMain.__init__(self, 'conveyord', 'server')

    def _initparser_common(self, parser):
        conveyor.main.AbstractMain._initparser_common(self, parser)
        parser.add_argument(
            '--nofork', action='store_true', default=False,
            help='do not fork nor detach from the terminal')

    def _initsubparsers(self):
        return None

    def _run(self):
        has_daemon = False
        code = -17 #failed to run err
        try:
            import daemon
            import daemon.pidfile
            has_daemon = True
        except ImportError:
            self._log.debug('handled exception', exc_info=True)
        def handle_sigterm(signum, frame):
            self._log.info('received signal %d', signum)
            sys.exit(0)
        pidfile = self._config['common']['pidfile']
        try:
            if self._parsedargs.nofork or not has_daemon:
                signal.signal(signal.SIGTERM, handle_sigterm)
                lock = lockfile.pidlockfile.PIDLockFile(pidfile)
                lock.acquire(0)
                try:
                    code = self._run_server()
                finally:
                    lock.release()
            else:
                files_preserve = list(conveyor.log.getfiles())
                dct = {
                    'files_preserve': files_preserve,
                    'pidfile': daemon.pidfile.TimeoutPIDLockFile(pidfile, 0)
                }
                if not self._config['server']['chdir']:
                    dct['working_directory'] = os.getcwd()
                context = daemon.DaemonContext(**dct)
                # The daemon module's implementation of terminate() raises a
                # SystemExit with a string message instead of an exit code. This
                # monkey patch fixes it.
                context.terminate = handle_sigterm # monkey patch!
                with context:
                    code = self._run_server()
        except lockfile.AlreadyLocked:
            self._log.debug('handled exception', exc_info=True)
            self._log.error('pid file exists: %s', pidfile)
            code = 1
        except lockfile.UnlockError:
            self._log.warning('error while removing pidfile', exc_info=True)
        return code

    def _run_server(self):
        self._initeventqueue()
        listener = self._address.listen()
        with listener:
            server = Server(self._config, listener)
            code = server.run()
            return code

def export(name):
    def decorator(func):
        return func
    return decorator

def getexception(exception):
    if None is not exception:
        exception = {
            'name': exception.__class__.__name__,
            'args': exception.args,
            'errno': getattr(exception, 'errno', None),
            'strerror': getattr(exception, 'strerror', None),
            'filename': getattr(exception, 'filename', None),
            'winerror': getattr(exception, 'winerror', None)
        }
    return exception 

class _VerifyS3gTaskFactory(conveyor.jsonrpc.TaskFactory):

    def __init__(self):
        pass

    def __call__(self, s3gpath):
        return conveyor.recipe.Recipe.verifys3gtask(s3gpath)

class _WriteEepromTaskFactory(conveyor.jsonrpc.TaskFactory):
    def __init__(self, clientthread):
        self._clientthread = clientthread
        self._log = logging.getLogger(self.__class__.__name__)

    def __call__(self, printername, eeprommap):
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                printerthread = self._clientthread._findprinter(printername)
                printerthread.writeeeprom(eeprommap, task)
            except Exception as e:
                self._log.debug('handled exception')
                exception = getexception(e)
                task.fail(exception)
            else:
                task.end(None)
        task.runningevent.attach(runningcallback)
        return task

class _ReadEepromTaskFactory(conveyor.jsonrpc.TaskFactory):
    def __init__(self, clientthread):
        self._clientthread = clientthread
        self._log = logging.getLogger(self.__class__.__name__)

    def __call__(self, printername):
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                printerthread = self._clientthread._findprinter(printername)
                eeprommap = printerthread.readeeprom(task)
            except Exception as e:
                self._log.debug('handled exception')
                exception = getexception(e)
                task.fail(exception)
            else:
                task.end(eeprommap)
        task.runningevent.attach(runningcallback)
        return task

class _UploadFirmwareTaskFactory(conveyor.jsonrpc.TaskFactory):
    def __init__(self, clientthread):
        self._clientthread = clientthread
        self._log = logging.getLogger(self.__class__.__name__)

    def __call__(self, printername, machinetype, filename):
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                printerthread = self._clientthread._findprinter(printername)
                printerthread.uploadfirmware(machinetype, filename, task)
            except Exception as e:
                self._log.debug('handled exception')
                message = unicode(e)
                task.fail(message)
            else:
                task.end(None)
        task.runningevent.attach(runningcallback)
        return task

class _GetUploadableMachinesTaskFactory(conveyor.jsonrpc.TaskFactory):

    def __init__(self):
        pass

    def __call__(self):
        import urllib2
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                uploader = makerbot_driver.Firmware.Uploader()
                machines = uploader.list_machines()
                task.end(machines)
            except Exception as e:
                message = unicode(e)
                task.fail(message)
        task.runningevent.attach(runningcallback)
        return task

class _GetMachineVersionsTaskFactory(conveyor.jsonrpc.TaskFactory):

    def __init__(self):
        pass

    def __call__(self, machine_type):
        import urllib2
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                uploader = makerbot_driver.Firmware.Uploader()
                versions = uploader.list_firmware_versions(machine_type)
                task.end(versions)
            except Exception as e:
                message = unicode(e)
                task.fail(message)
        task.runningevent.attach(runningcallback)
        return task

class _DownloadFirmwareTaskFactory(conveyor.jsonrpc.TaskFactory):
    def __init__(self):
        pass

    def __call__(self, machinetype, version):
        import urllib2
        task = conveyor.task.Task()
        def runningcallback(task):
            try:
                uploader = makerbot_driver.Firmware.Uploader()
                hex_file_path = uploader.download_firmware(machinetype, version)
                task.end(hex_file_path)
            except Exception as e:
                message = unicode(e)
                task.fail(message)
        task.runningevent.attach(runningcallback)
        return task

class _Method(object):
    pass

class _ClientThread(conveyor.stoppable.StoppableThread):
    @classmethod
    def create(cls, config, server, connection, id):
        jsonrpc = conveyor.jsonrpc.JsonRpc(connection, connection)
        clientthread = _ClientThread(config, server, jsonrpc, id)
        return clientthread

    def __init__(self, config, server, jsonrpc, id):
        conveyor.stoppable.StoppableThread.__init__(self)
        self._config = config
        self._log = logging.getLogger(self.__class__.__name__)
        self._server = server
        self._id = id
        self._jsonrpc = jsonrpc
        self._printers_seen = []

    def printeradded(self, params):
        self._jsonrpc.notify('printeradded', params)

    def printerchanged(self, params):
        self._jsonrpc.notify('printerchanged', params)

    def printerremoved(self, params):
        self._jsonrpc.notify('printerremoved', params)

    def jobadded(self, params):
        self._jsonrpc.notify('jobadded', params)

    def jobchanged(self, params):
        self._jsonrpc.notify('jobchanged', params)

    def _stoppedcallback(self, job):
        def callback(task):
            job.state = task.state
            job.conclusion = task.conclusion
            job.failure = None
            if None is not task.failure:
                job.failure = unicode(task.failure.failure)
            if conveyor.task.TaskConclusion.ENDED == task.conclusion:
                self._log.info('job %d ended', job.id)
            elif conveyor.task.TaskConclusion.FAILED == task.conclusion:
                self._log.info('job %d failed: %s', job.id, job.failure)
            elif conveyor.task.TaskConclusion.CANCELED == task.conclusion:
                self._log.info('job %d canceled', job.id)
            else:
                raise ValueError(task.conclusion)
            self._server.changejob(job)
        return callback

    @export('hello')
    def _hello(self):
        self._log.debug('')
        return 'world'

    @export('dir')
    def _dir(self):
        self._log.debug('')
        result = {}
        methods = self._jsonrpc.getmethods()
        result = {}
        for k, f in methods.items():
            doc = getattr(f, '__doc__', None)
            if None is not doc:
                result[k] = f.__doc__
        result['__version__'] = conveyor.__version__
        return result

    def _findprinter(self, name):
        printerthread = None
        if None is name:
            printerthread = self._findprinter_default()
            if None is printerthread:
                raise Exception('no printer connected') # TODO: custom exception
        else:
            printerthread = self._server.findprinter_printerid(name)
            if None is printerthread:
                printerthread = self._server.findprinter_portname(name)
            if None is printerthread:
                raise Exception('unknown printer: %s' % (name,)) # TODO: custom exception
        return printerthread

    def _findprinter_default(self):
        printerthreads = self._server.getprinterthreads()
        keys = printerthreads.keys()
        if 0 == len(keys):
            printerthread = None
        else:
            key = keys[0]
            printerthread = self._server._printerthreads[key]
        return printerthread

    def _findprofile(self, name):
        if None is name:
            name = self._config['common']['profile']
        profile = makerbot_driver.Profile(name, self._config['common']['profiledir'])
        return profile

    def _getbuildname(self, path):
        root, ext = os.path.splitext(path)
        buildname = os.path.basename(root)
        return buildname

    @export('print')
    def _print(
        self, printername, inputpath, gcodeprocessor, skip_start_end, archive_lvl,
        archive_dir, slicer_settings, material):
            self._log.debug(
                'printername=%r, inputpath=%r, gcodeprocessor=%r, skip_start_end=%r, archive_lvl=%r, archive_dir=%r, slicer_settings=%r, material=%r',
                printername, inputpath, gcodeprocessor, skip_start_end,
                archive_lvl, archive_dir, slicer_settings, material)
            slicer_settings = conveyor.domain.SlicerConfiguration.fromdict(slicer_settings)
            recipemanager = conveyor.recipe.RecipeManager(
                self._server, self._config)
            build_name = self._getbuildname(inputpath)
            printerthread = self._findprinter(printername)
            printerid = printerthread.getprinterid()
            profile = printerthread.getprofile()
            job = self._server.createjob(
                build_name, inputpath, self._config, printerid, profile,
                gcodeprocessor, skip_start_end, False, slicer_settings,
                profile.values['print_to_file_type'][0], material)
            recipe = recipemanager.getrecipe(job)
            process = recipe.print(printerthread)
            job.process = process
            def startcallback(task):
                self._server.addjob(job)
            process.startevent.attach(startcallback)
            def runningcallback(task):
                self._log.info(
                    'printing: %s (job %d)', inputpath, job.id)
            process.runningevent.attach(runningcallback)
            def heartbeatcallback(task):
                childtask = task.progress
                progress = childtask.progress
                job.currentstep = progress
                job.state = task.state
                job.conclusion = task.conclusion
                self._server.changejob(job)
                self._log.info('progress: (job %d) %r', job.id, progress)
            process.heartbeatevent.attach(heartbeatcallback)
            process.stoppedevent.attach(self._stoppedcallback(job))
            process.start()
            dct = job.todict()
            return dct

    @export('printtofile')
    def _printtofile(
        self, profilename, inputpath, outputpath, gcodeprocessor, skip_start_end, 
        archive_lvl, archive_dir, slicer_settings, print_to_file_type, material):
            self._log.debug(
                'profilename=%r, inputpath=%r, outputpath=%r, gcodeprocessor=%r, skip_start_end=%r, print_to_file_type=%r, printer=%r, archive_lvl=%r, archive_dir=%r, slicer_settings=%r, material=%r',
                profilename, inputpath, outputpath, gcodeprocessor,
                skip_start_end, print_to_file_type, archive_lvl, archive_dir, slicer_settings,
                material)
            slicer_settings = conveyor.domain.SlicerConfiguration.fromdict(slicer_settings)
            recipemanager = conveyor.recipe.RecipeManager(
                self._server, self._config)
            build_name = self._getbuildname(inputpath)
            profile = self._findprofile(profilename)
            job = self._server.createjob(
                build_name, inputpath, self._config, None, profile,
                gcodeprocessor, skip_start_end, False, slicer_settings,
                print_to_file_type, material)
            recipe = recipemanager.getrecipe(job)
            process = recipe.printtofile(profile, outputpath)
            job.process = process
            def startcallback(task):
                self._server.addjob(job)
            process.startevent.attach(startcallback)
            def runningcallback(task):
                self._log.info(
                    'printing to file: %s -> %s (job %d)', inputpath,
                    outputpath, job.id)
            process.runningevent.attach(runningcallback)
            def heartbeatcallback(task):
                childtask = task.progress
                progress = childtask.progress
                job.currentstep = progress
                job.state = task.state
                job.conclusion = task.conclusion
                self._server.changejob(job)
                self._log.info('progress: (job %d) %r', job.id, progress)
            process.heartbeatevent.attach(heartbeatcallback)
            process.stoppedevent.attach(self._stoppedcallback(job))
            process.start()
            dct = job.todict()
            return dct

    @export('slice')
    def _slice(
        self, profilename, inputpath, outputpath, gcodeprocessor,
        with_start_end, slicer_settings, material):
            self._log.debug(
                'profilename=%r, inputpath=%r, outputpath=%r, gcodeprocessor=%r, with_start_end=%r, slicer_settings=%r, material=%r',
                profilename, inputpath, outputpath, gcodeprocessor,
                with_start_end, slicer_settings, material)
            slicer_settings = conveyor.domain.SlicerConfiguration.fromdict(slicer_settings)
            recipemanager = conveyor.recipe.RecipeManager(
                self._server, self._config)
            build_name = self._getbuildname(inputpath)
            profile = self._findprofile(profilename)
            job = self._server.createjob(
                build_name, inputpath, self._config, None, profile,
                gcodeprocessor, False, with_start_end, slicer_settings,
                None, material)
            recipe = recipemanager.getrecipe(job)
            process = recipe.slice(profile, outputpath)
            job.process = process
            def startcallback(task):
                self._server.addjob(job)
            process.startevent.attach(startcallback)
            def runningcallback(task):
                self._log.info(
                    'slicing: %s -> %s (job %d)', inputpath, outputpath,
                    job.id)
            process.runningevent.attach(runningcallback)
            def heartbeatcallback(task):
                childtask = task.progress
                progress = childtask.progress
                job.currentstep = progress
                job.state = task.state
                job.conclusion = task.conclusion
                self._server.changejob(job)
                self._log.info('progress: (job %d) %r', job.id, progress)
            process.heartbeatevent.attach(heartbeatcallback)
            process.stoppedevent.attach(self._stoppedcallback(job))
            process.start()
            dct = job.todict()
            return dct

    @export('canceljob')
    def _canceljob(self, id):
        self._server.canceljob(id)

    @export('getprinters')
    def _getprinters(self):
        result = []
        profiledir = self._config['common']['profiledir']
        profile_names = list(makerbot_driver.list_profiles(profiledir))
        for profile_name in profile_names:
            if 'recipes' != profile_name:
                profile = makerbot_driver.Profile(profile_name, profiledir)
                printer = conveyor.domain.Printer.fromprofile(
                    profile, profile_name, None)
                printer.can_print = False
                dct = printer.todict()
                result.append(dct)
        printerthreads = self._server.getprinterthreads()
        for portname, printerthread in printerthreads.items():
            profile = printerthread.getprofile()
            printerid = printerthread.getprinterid()
            printer = conveyor.domain.Printer.fromprofile(
                profile, printerid, None)
            dct = printer.todict()
            result.append(dct)
        return result

    @export('getjobs')
    def _getjobs(self):
        jobs = self._server.getjobs()
        result = {}
        for job in jobs.values():
            dct = job.todict()
            result[job.id] = dct
        return result

    @export('getjob')
    def _getjob(self, id):
        job = self._server.getjob(id)
        result = job.todict()
        return result

    @export('resettofactory')
    def _resettofactory(self, printername):
        printerthread = self._findprinter(printername)
        task = conveyor.task.Task()
        printerthread.resettofactory(task)

    @export('compatiblefirmware')
    def _compatiblefirmware(self, firmwareversion):
        uploader = makerbot_driver.Firmware.Uploader(autoUpdate=False)
        return uploader.compatible_firmware(firmwareversion)

    def _load_services(self):
        self._jsonrpc.addmethod('hello', self._hello, "no params. Returns 'world'")
        self._jsonrpc.addmethod('print', self._print, 
            ": takes (thing-filename, gcodeprocessor, skip_start_end_bool, [endpoint)" )
        self._jsonrpc.addmethod('printtofile', self._printtofile,
            ": takes (inputfile, outputfile) pair" )
        self._jsonrpc.addmethod('slice', self._slice,
            ": takes (inputfile, outputfile) pair" )
        self._jsonrpc.addmethod('dir',self._dir, "takes no params ") 
        self._jsonrpc.addmethod('canceljob',self._canceljob,
                "takes {'port':string(port) 'job_id':jobid}"
                        "if Job is None, cancels by port. If port is None, cancels first bot")
        self._jsonrpc.addmethod('getprinters', self._getprinters)
        self._jsonrpc.addmethod('getjob', self._getjob)
        self._jsonrpc.addmethod('getjobs', self._getjobs)
        readeepromfactory = _ReadEepromTaskFactory(self)
        self._jsonrpc.addmethod('readeeprom', readeepromfactory, ": takes a printerthread")
        writeeepromfactory = _WriteEepromTaskFactory(self)
        self._jsonrpc.addmethod('writeeeprom', writeeepromfactory, ": takes a printerthread and json eeprommap")
        getuploadablemachinesfactory = _GetUploadableMachinesTaskFactory()
        self._jsonrpc.addmethod('getuploadablemachines', getuploadablemachinesfactory, ":takes no params")
        getmachineversionstaskfactory = _GetMachineVersionsTaskFactory()
        self._jsonrpc.addmethod('getmachineversions', getmachineversionstaskfactory, ': takes (machine_type)')
        downloadfirmwaretaskfactory = _DownloadFirmwareTaskFactory()
        self._jsonrpc.addmethod('downloadfirmware', downloadfirmwaretaskfactory, 'takes (machine, version)')
        uploadfirmwaretaskfactory = _UploadFirmwareTaskFactory(self)
        self._jsonrpc.addmethod('uploadfirmware', uploadfirmwaretaskfactory, ": takes (printername, machine_type, version)")
        verifys3gtaskfactory = _VerifyS3gTaskFactory()
        self._jsonrpc.addmethod('verifys3g', verifys3gtaskfactory, ": takes a path to the s3g file")
        self._jsonrpc.addmethod('resettofactory', self._resettofactory, ": takes no params")
        self._jsonrpc.addmethod('compatiblefirmware', self._compatiblefirmware, ": takes firmware_version")

    def run(self):
        # add our available functions to the json methods list
        self._load_services()
        self._server.appendclientthread(self)
        try:
            self._jsonrpc.run()
        finally:
            self._server.removeclientthread(self)

    def stop(self):
        self._jsonrpc.stop()

class Queue(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._log = logging.getLogger(self.__class__.__name__)
        self._queue = collections.deque()
        self._stop = False

    def _runiteration(self):
        with self._condition:
            if 0 == len(self._queue):
                self._log.debug('waiting')
                self._condition.wait()
                self._log.debug('resumed')
            if 0 == len(self._queue):
                self._log.debug('queue is empty')
                func = None
            else:
                self._log.debug('queue is not empty')
                func = self._queue.pop()
        if None is not func:
            try:
                self._log.debug('running func')
                func()
                self._log.debug('func ended')
            except:
                self._log.exception('unhandled exception')

    def appendfunc(self, func):
        with self._condition:
            self._queue.appendleft(func)
            self._condition.notify_all()

    def run(self):
        self._log.debug('starting')
        self._stop = False
        while not self._stop:
            self._runiteration()
        self._log.debug('ending')

    def stop(self):
        with self._condition:
            self._stop = True
            self._condition.notify_all()

class _TaskQueueThread(threading.Thread, conveyor.stoppable.StoppableInterface):
    def __init__(self, queue):
        threading.Thread.__init__(self, name='taskqueue')
        conveyor.stoppable.StoppableInterface.__init__(self)
        self._log = logging.getLogger(self.__class__.__name__)
        self._queue = queue

    def run(self):
        try:
            self._queue.run()
        except:
            self._log.error('internal error', exc_info=True)

    def stop(self):
        self._queue.stop()

class Server(object):
    def __init__(self, config, listener):
        self._clientthreads = []
        self._config = config
        self._detectorthread = None
        self._idcounter = 0
        self._jobcounter = 0
        self._jobs = {}
        self._lock = threading.Lock()
        self._listener = listener
        self._log = logging.getLogger(self.__class__.__name__)
        self._queue = Queue()
        self._printerthreads = {}

    def _invokeclients(self, methodname, *args, **kwargs):
        with self._lock:
            clientthreads = self._clientthreads[:]
        for clientthread in clientthreads:
            try:
                method = getattr(clientthread, methodname)
                method(*args, **kwargs)
            except conveyor.connection.ConnectionWriteException:
                self._log.debug('handled exception', exc_info=True)
                clientthread.stop()
            except:
                self._log.exception('unhandled exception')

    def getprinterthreads(self):
        with self._lock:
            printerthreads = self._printerthreads.copy()
        return printerthreads

    def findprinter_printerid(self, name):
        with self._lock:
            for printerthread in self._printerthreads.values():
                if name == printerthread.getprinterid():
                    return printerthread
            return None

    def findprinter_portname(self, name):
        with self._lock:
            for printerthread in self._printerthreads.values():
                if name == printerthread.getportname():
                    return printerthread
            return None

    # NOTE: the difference between createjob and addjob is that createjob
    # creates a new job domain object while add job takes a job domain object,
    # adds it to the list of jobs, and notifies connected clients.
    #
    # The job created by createjob will have None as its process. The job
    # passed to addjob must have a valid process.

    def createjob(
        self, build_name, path, config, printerid, profile, gcodeprocessor,
        skip_start_end, with_start_end, slicer_settings, print_to_file_type, material):
            # NOTE: The profile is not currently included in the actual job
            # because it can't be converted to or from JSON.
            with self._lock:
                id = self._jobcounter
                self._jobcounter += 1
                job = conveyor.domain.Job(
                    id, build_name, path, config, printerid, gcodeprocessor,
                    skip_start_end, with_start_end, slicer_settings, print_to_file_type, material)
                return job

    def addjob(self, job):
        with self._lock:
            self._jobs[job.id] = job
        dct = job.todict()
        self._invokeclients('jobadded', dct)

    def changejob(self, job):
        params = job.todict()
        self._invokeclients("jobchanged", params)

    def canceljob(self, id):
        with self._lock:
            job = self._jobs[id]
        if conveyor.task.TaskState.STOPPED != job.process.state:
            job.process.cancel()

    def getjobs(self):
        with self._lock:
            jobs = self._jobs.copy()
            return jobs

    def getjob(self, id):
        with self._lock:
            job = self._jobs[id]
            return job

    def appendclientthread(self, clientthread):
        with self._lock:
            self._clientthreads.append(clientthread)

    def removeclientthread(self, clientthread):
        with self._lock:
            self._clientthreads.remove(clientthread)

    def appendprinter(self, portname, printerthread):
        self._log.info('printer connected: %s', portname)
        with self._lock:
            self._printerthreads[portname] = printerthread
        printerid = printerthread.getprinterid()
        profile = printerthread.getprofile()
        printer = conveyor.domain.Printer.fromprofile(profile, printerid, None)
        dct = printer.todict()
        self._invokeclients('printeradded', dct)

    def changeprinter(self, portname, temperature):
        self._log.debug('portname=%r, temperature=%r', portname, temperature)
        printerthread = self.findprinter_portname(portname)
        printerid = printerthread.getprinterid()
        profile = printerthread.getprofile()
        printer = conveyor.domain.Printer.fromprofile(
            profile, printerid, temperature)
        dct = printer.todict()
        self._invokeclients('printerchanged', dct)

    def evictprinter(self, portname, fp):
        self._log.info('printer evicted due to error: %s', portname)
        self._detectorthread.blacklist(portname)
        self.removeprinter(portname)
        fp.close()

    def removeprinter(self, portname):
        self._log.info('printer disconnected: %s', portname)
        with self._lock:
            if portname in self._printerthreads:
                printerthread = self._printerthreads.pop(portname)
            else:
                printerthread = None
        if None is printerthread:
            self._log.debug(
                'disconnected unconnected printer: %s', portname)
        else:
            printerthread.stop()
            printerid = printerthread.getprinterid()
            params = {'id': printerid}
            self._invokeclients('printerremoved', params)

    def printtofile(self, profile, buildname, inputpath, outputpath,
            skip_start_end, slicer_settings, print_to_file_type, material,
            task, dualstrusion):
        def func():
            driver = conveyor.machine.s3g.S3gDriver()
            driver.printtofile(
                outputpath, profile, buildname, inputpath, skip_start_end,
                slicer_settings, print_to_file_type, material, task,
                dualstrusion)
        self._queue.appendfunc(func)

    def slice(
        self, profile, inputpath, outputpath, with_start_end,
        slicer_settings, material, dualstrusion, task):
            def func():
                if conveyor.domain.Slicer.MIRACLEGRUE == slicer_settings.slicer:
                    slicerpath = self._config['miraclegrue']['path']
                    configpath = self._config['miraclegrue']['config']
                    slicer = conveyor.slicer.miraclegrue.MiracleGrueSlicer(
                        profile, inputpath, outputpath, with_start_end,
                        slicer_settings, material, dualstrusion, task,
                        slicerpath, configpath)
                elif conveyor.domain.Slicer.SKEINFORGE == slicer_settings.slicer:
                    slicerpath = self._config['skeinforge']['path']
                    profilepath = self._config['skeinforge']['profile']
                    slicer = conveyor.slicer.skeinforge.SkeinforgeSlicer(
                        profile, inputpath, outputpath, with_start_end,
                        slicer_settings, material, dualstrusion, task,
                        slicerpath, profilepath)
                else:
                    raise ValueError(slicer_settings.slicer)
                slicer.slice()
            self._queue.appendfunc(func)

    def run(self):
        self._detectorthread = conveyor.machine.s3g.S3gDetectorThread(
            self._config, self)
        self._detectorthread.start()
        taskqueuethread = _TaskQueueThread(self._queue)
        taskqueuethread.start()
        try:
            while True:
                connection = self._listener.accept()
                with self._lock:
                    id = self._idcounter
                    self._idcounter += 1
                clientthread = _ClientThread.create(
                    self._config, self, connection, id)
                clientthread.start()
        finally:
            self._queue.stop()
            taskqueuethread.join(1)
        return 0
