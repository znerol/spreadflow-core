# -*- coding: utf-8 -*-
"""Event Dispatcher

Implements an priority queue based event dispatcher.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import collections
import itertools
import bisect

from twisted.internet import defer
from twisted.logger import Logger
from twisted.python.failure import Failure

Key = collections.namedtuple('Key', ['priority', 'serial'])
Handler = collections.namedtuple('Handler', ['callback', 'args', 'kwds'])
Entry = collections.namedtuple('Entry', ['key', 'handler'])

class FailMode(object): # pylint: disable=too-few-public-methods
    """Failure modes enumeration

    Attributes:
        RAISE (int): Raise an exception if a handler fails.
        RETURN (int): Include failures into the result returned by the dispatch
            method.
    """
    RAISE = 0
    RETURN = 1

class HandlerError(Exception):
    """An exception wrapping an error generated by an event handler.

    Attributes:
        handler: The handler record responsible for the error.
        wrapped_failure: A failure instance.
    """
    def __init__(self, handler, wrapped_failure):
        super(HandlerError, self).__init__()
        self.handler = handler
        self.wrapped_failure = wrapped_failure

    def __repr__(self):
        return 'HandlerError[{:s}, {:s}]'.format(
            str(self.handler), str(self.wrapped_failure.value))

    def __str__(self):
        return 'HandlerError[{:s}, {:s}]'.format(
            str(self.handler), str(self.wrapped_failure))

class EventDispatcher(object):
    """ Event dispatcher.

    An event dispatcher specifically designed for twisted deferreds.

    Event handlers can be registered for user defined event types. An event
    handler may return a deferred causing the dispatcher to wait on it. When
    dispatching an event, the handlers are called according to their priority.
    The dispatcher only advances to the next priority when all handlers with a
    lower priority have completed.

    Additional positional and keyword arguments provided while registering the
    event handler are passed to the callback upon invocation.

    Example:

        The following example illustrates how to register event handlers and
        dispatch events::

            from __future__ import print_function
            from spreadflow_core.eventdispatcher import EventDispatcher

            class GreetEvent(object):
                def __init__(self, message='hello'):
                    self.message = message

            def simple_greeter(event):
                print(event.message)

            def complex_greeter(event, prefix, suffix):
                print(prefix + event.message + suffix)

            dispatcher = EventDispatcher()

            dispatcher.add_listener(GreetEvent, 99, simple_greeter)
            dispatcher.add_listener(GreetEvent, 0, complex_greeter,
                'oh, ', suffix=' world!')

            dispatcher.dispatch(GreetEvent())

        This example will generate the following output::

            oh, hello world!
            hello

        Any exception raised by a handler will immediately stop any callbacks
        in progress unless fail_mode=FailMode.RETURN is specified. The utility
        method log_failures provides an easy way to log any exceptions.

            event = GreetEvent()
            deferred = dispatcher.dispatch(event)
            deferred.addCallback(dispatcher.log_failures, event)
    """

    log = Logger()

    def __init__(self):
        self._counter = itertools.count()
        self._listeners = {}

    def add_listener(self, event_type, priority, callback, *args, **kwds):
        """
        Register a callback function for events of the given type.

        Args:
            event_type: Type of the event. Pass the class in here for events
                based on classes.
            priority (int): Priority of this handler.
            callback (callable): The function to call when an event of the
                given type is dispatched.
            *args: Positional parameters passed to the function upon
                invocation.
            **kwds: Keyword parameters passed to the function upon invocation.

        Returns:
            :class:`spreadflow_core.eventdispatcher.Key`: A reference to the
            registered listener. This can be used to subsequently remove it
            again.
        """
        listeners = self._listeners.setdefault(event_type, [])
        key = Key(priority, next(self._counter))
        bisect.insort(listeners, Entry(key, Handler(callback, args, kwds)))
        return key

    def remove_listener(self, event_type, key):
        """
        Removes an event handler from the list of listeners for the given type.

        Args:
            event_type: Type of the event. Pass the class in here for events
                based on classes.
            key: A key as returned by add_listeners.

        Returns:
            :class:`spreadflow_core.eventdispatcher.Handler`: A reference to
            the removed callback, positional parameters and keyword arguments.
        """
        result = None

        listeners = self._listeners[event_type]
        idx = bisect.bisect(listeners, (key,), hi=len(listeners)-1)

        if listeners[idx].key == key:
            result = listeners.pop(idx)
        else:
            raise KeyError(key)

        if len(listeners) == 0:
            del self._listeners[event_type]

        return result.handler

    def get_listeners(self, event_type):
        """
        Returns an iterator over listeners for the given event type.

        Args:
            event_type: Type of the event. Pass the class in here for events
            based on classes.

        Returns:
            An iterator over the listeners for the given event type.
        """
        return iter(self._listeners.get(event_type, []))

    def get_listeners_grouped(self, event_type):
        """
        Returns a group iterator over listeners for the given event type.

        Args:
            event_type: Type of the event. Pass the class in here for events
            based on classes.

        Returns:
            An iterator over the listeners grouped by priority.
        """
        listeners = self.get_listeners(event_type)
        keyfunc = lambda entry: entry.key.priority
        return itertools.groupby(listeners, keyfunc)


    @defer.inlineCallbacks
    def dispatch(self, event, fail_mode=FailMode.RAISE):
        """
        Dispatch an event, calling all the registered listeners in turn.

        Args:
            event: An event instance.
            fail_mode: One of FailMode.RAISE (default) and FailMode.RESULT.

        Returns:
            A list of tuples (priority, list-of-results) where each entry in
            the nested list is of the form (success, result).

            When a handler fails and FailMode.RAISE is specified, errbacks with
            a :class:`spreadflow_core.eventdispatcher.HandlerError`. When
            FailMode.RETURN is specified, the failures are returned as part of
            the result.
        """
        results = []

        fire_on_fail = (fail_mode == FailMode.RAISE)

        for priority, group in self.get_listeners_grouped(type(event)):
            self.log.debug('Calling handlers with priority {priority} for {event}', event=event, priority=priority) # pylint: disable=line-too-long

            handlers = [handler for _, handler in group]
            batch = []
            for handler in handlers:
                deferred = defer.maybeDeferred(handler.callback, event,
                                               *handler.args, **handler.kwds)
                deferred.addErrback(lambda failure, handler=handler:
                                    Failure(HandlerError(handler, failure)))
                batch.append(deferred)

            if len(batch):
                deferred = defer.DeferredList(batch, consumeErrors=True,
                                              fireOnOneErrback=fire_on_fail)
                if fire_on_fail:
                    deferred.addErrback(_trap_first_error, handlers)
                group_results = yield deferred
                results.append((priority, group_results))

            self.log.debug('Called {n} handlers with priority {priority} for {event}', n=len(batch), event=event, priority=priority) # pylint: disable=line-too-long


        defer.returnValue(results)

    def log_failures(self, result, event):
        """
        Inspects the result returned by dispatch and logs any failures.

        Args:
            result: The result as returned by dispatch.
            event: An event instance.

        Returns:
            The result as passed into the method. Thus this method also can be
            used in the callback chain of the deferred returned by dispatch.
        """
        for priority, group_results in result:
            for success, result in group_results:
                if not success:
                    if result.check(HandlerError):
                        self.log.failure('Failure while handling event {event} with {handler}', result, event=event, priority=priority, handler=result.value.handler) # pylint: disable=line-too-long

                    else:
                        self.log.failure('Failure while handling event {event}', result, event=event, priority=priority) # pylint: disable=line-too-long

        return result

def _trap_first_error(failure, handlers):
    """Traps defer.FirstError and turns it into a HandlerError"""
    failure.trap(defer.FirstError)
    if isinstance(failure.value.subFailure, HandlerError):
        raise failure.value.subFailure
    else:
        handler = handlers[failure.value.index]
        raise HandlerError(handler, failure.value.subFailure)
