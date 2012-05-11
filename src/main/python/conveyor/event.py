# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:

from __future__ import (absolute_import, print_function, unicode_literals)

import PyQt4.QtCore
import collections
import logging
import threading
import time
import unittest

_eventqueue = None

def geteventqueue():
    global _eventqueue
    if None is _eventqueue:
        _eventqueue = EventQueue()
    return _eventqueue

class EventQueue(PyQt4.QtCore.QThread):
    def __init__(self):
        PyQt4.QtCore.QThread.__init__(self)
        self._lock = threading.Lock()
        self._log = logging.getLogger(self.__class__.__name__)
        self._condition = threading.Condition(self._lock)
        self._queue = collections.deque()
        self._quit = False

    def runiteration(self, block):
        self._log.debug('block=%r', block)
        with self._condition:
            if block:
                while 0 == len(self._queue):
                    self._log.debug('waiting')
                    self._condition.wait()
                    self._log.debug('resumed')
            if 0 == len(self._queue):
                tuple_ = None
            else:
                tuple_ = self._queue.pop()
        if None is not tuple_:
            event, args, kwargs = tuple_
            event._deliver(args, kwargs)
        result = None is not tuple_
        self._log.debug('result=%r', result)
        return result

    def run(self):
        self._log.debug('starting')
        self._quit = False
        while not self._quit:
            self.runiteration(True)
        self._log.debug('ending')

    def quit(self):
        event = Event('EventQueue.quit', self)
        def func():
            self._quit = True
        event.attach(func)
        event()

    def _enqueue(self, event, args, kwargs):
        self._log.debug('event=%r, args=%r, kwargs=%r', event, args, kwargs)
        tuple_ = event, args, kwargs
        with self._condition:
            self._queue.appendleft(tuple_)
            self._condition.notify_all()

class Event(object):
    def __init__(self, name, eventqueue=None):
        self._name = name
        self._eventqueue = eventqueue
        self._handles = {}
        self._log = logging.getLogger(self.__class__.__name__)

    def attach(self, func):
        handle = object()
        self._handles[handle] = func
        self._log.debug(
            'name=%r, func=%r, handle=%r', self._name, func, handle)
        return handle

    def detach(self, handle):
        self._log.debug('handle=%r', handle)
        del self._handles[handle]

    def __call__(self, *args, **kwargs):
        self._log.debug(
            'name=%r, args=%r, kwargs=%r', self._name, args, kwargs)
        eventqueue = self._eventqueue
        if None is eventqueue:
            eventqueue = geteventqueue()
        eventqueue._enqueue(self, args, kwargs)

    def _deliver(self, args, kwargs):
        self._log.debug(
            'name=%r, args=%r, kwargs=%r', self._name, args, kwargs)
        for func in self._handles.itervalues():
            try:
                func(*args, **kwargs)
            except:
                self._log.error('internal error', exc_info=True)

    def __repr__(self):
        result = '%s(name=%r, eventqueue=%r)' % (
            self.__class__.__name__, self._name, self._eventqueue)
        return result

class Callback(object):
    def __init__(self):
        self._log = logging.getLogger(self.__class__.__name__)
        self.delivered = False
        self.args = None
        self.kwargs = None

    def reset(self):
        self._log.debug('')
        self.delivered = False
        self.args = None
        self.kwargs = None

    def __call__(self, *args, **kwargs):
        self._log.debug('args=%r, kwargs=%r', args, kwargs)
        self.delivered = True
        self.args = args
        self.kwargs = kwargs

class EventQueueTestCase(unittest.TestCase):
    def test(self):
        eventqueue = geteventqueue()
        eventqueue._queue.clear()

        event = Event('event')
        callback1 = Callback()
        callback2 = Callback()
        handle1 = event.attach(callback1)
        handle2 = event.attach(callback2)
        event.attach(eventqueue.quit)

        self.assertFalse(callback1.delivered)
        self.assertFalse(callback2.delivered)
        event()
        eventqueue.run()
        self.assertTrue(callback1.delivered)
        self.assertTrue(callback2.delivered)

        callback1.reset()
        callback2.reset()
        event.detach(handle1)
        self.assertFalse(callback1.delivered)
        self.assertFalse(callback2.delivered)
        event()
        eventqueue.run()
        self.assertFalse(callback1.delivered)
        self.assertTrue(callback2.delivered)

        callback1.reset()
        callback2.reset()
        event.detach(handle2)
        self.assertFalse(callback1.delivered)
        self.assertFalse(callback2.delivered)
        event()
        eventqueue.run()
        self.assertFalse(callback1.delivered)
        self.assertFalse(callback2.delivered)

    def test_wait(self):
        eventqueue = geteventqueue()
        eventqueue._queue.clear()

        event = Event('event')
        callback = Callback()
        event.attach(callback)
        event.attach(eventqueue.quit)
        def target():
            time.sleep(0.1)
            event()
        thread = threading.Thread(target=target)
        thread.start()
        eventqueue.run()
        self.assertTrue(callback.delivered)

    def test_quit(self):
        eventqueue = geteventqueue()
        eventqueue._queue.clear()

        event1 = Event('event1')
        callback1 = Callback()
        event1.attach(callback1)
        event2 = Event('event2')
        callback2 = Callback()
        event2.attach(callback2)
        event1()
        eventqueue.quit()
        event2()
        eventqueue.run()
        self.assertTrue(callback1.delivered)
        self.assertFalse(callback2.delivered)

    def test___repr__(self):
        event = Event('event')
        self.assertEqual(
            "Event(name=u'event', eventqueue=None)", repr(event))
