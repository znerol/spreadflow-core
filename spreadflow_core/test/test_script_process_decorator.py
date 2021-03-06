# -*- coding: utf-8 -*-
# pylint: disable=too-many-public-methods

"""
Tests for the flowmap
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import unittest

from spreadflow_core.component import Compound
from spreadflow_core.dsl.stream import SetDefaultTokenOp, AddTokenOp
from spreadflow_core.dsl.tokens import \
    AliasToken, \
    ComponentToken, \
    ConnectionToken, \
    DescriptionToken, \
    LabelToken, \
    ParentElementToken, \
    PartitionToken
from spreadflow_core.script import Chain, Context, Duplicate, Process, ProcessTemplate

class ProcessDecoratorTestCase(unittest.TestCase):
    """
    Unit tests for the process decorator.
    """

    def test_process_class(self):
        """
        Process decorator replaces class definition with instantiated process.
        """
        process = object()

        with Context(self) as ctx:
            @Process()
            class TrivialProcess(ProcessTemplate):
                """
                Docs for the trivial process.
                """
                def apply(self):
                    yield AddTokenOp(ComponentToken(process))

        self.assertIs(TrivialProcess, process)

        tokens = ctx.tokens
        self.assertIn(SetDefaultTokenOp(LabelToken(process, 'TrivialProcess')), tokens)
        self.assertIn(SetDefaultTokenOp(DescriptionToken(process, 'Docs for the trivial process.')), tokens)
        self.assertIn(AddTokenOp(AliasToken(process, 'TrivialProcess')), tokens)

    def test_process_def(self):
        """
        Process decorator replaces function definition with compound.
        """

        port = object()

        with Context(self) as ctx:
            @Process()
            def trivial_proc():
                """
                Docs for another trivial process.
                """
                yield port


        self.assertIsInstance(trivial_proc, Compound)

        tokens = ctx.tokens
        self.assertIn(SetDefaultTokenOp(AliasToken(trivial_proc, 'trivial_proc')), tokens)
        self.assertIn(SetDefaultTokenOp(LabelToken(trivial_proc, 'trivial_proc')), tokens)
        self.assertIn(SetDefaultTokenOp(DescriptionToken(trivial_proc, 'Docs for another trivial process.')), tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port, trivial_proc)), tokens)

    def test_process_port_chain(self):
        """
        Process decorator replaces function definition with compound.
        """

        port1 = lambda item, send: send(item)
        port2 = lambda item, send: send(item)
        port3 = lambda item, send: send(item)

        with Context(self) as ctx:
            @Process()
            def proc_chain():
                yield port1
                yield port2
                yield port3

        self.assertIn(AddTokenOp(ConnectionToken(port1, port2)), ctx.tokens)
        self.assertIn(AddTokenOp(ConnectionToken(port2, port3)), ctx.tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port1, proc_chain)), ctx.tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port2, proc_chain)), ctx.tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port3, proc_chain)), ctx.tokens)

    def test_process_params(self):
        """
        Process decorator parameters for alias, label, description and partition.
        """
        process = object()

        with Context(self) as ctx:
            @Process(alias='trivproc', label='trivial process',
                     description='...', partition='trivia')
            class TrivialProcess(ProcessTemplate):
                """
                Docs for the trivial process.
                """
                def apply(self):
                    yield AddTokenOp(ComponentToken(process))

        tokens = ctx.tokens
        self.assertIn(AddTokenOp(AliasToken(process, 'trivproc')), tokens)
        self.assertIn(AddTokenOp(LabelToken(process, 'trivial process')), tokens)
        self.assertIn(AddTokenOp(DescriptionToken(process, '...')), tokens)
        self.assertIn(AddTokenOp(PartitionToken(process, 'trivia')), tokens)

    def test_process_tokens_from_template(self):
        """
        Template can provide additional tokens.
        """
        class MyToken(object):
            pass

        token = MyToken()

        process = object()

        with Context(self) as ctx:
            @Process()
            class TrivialProcess(ProcessTemplate):
                """
                Docs for the trivial process.
                """
                def apply(self):
                    yield AddTokenOp(token)
                    yield AddTokenOp(ComponentToken(process))

        self.assertIn(AddTokenOp(token), ctx.tokens)

class LegacyScriptTestCase(unittest.TestCase):
    """
    Unit tests for the config script module.
    """

    def test_legacy_chain(self):
        port1 = lambda item, send: send(item)
        port2 = lambda item, send: send(item)
        port3 = lambda item, send: send(item)

        with Context(self) as ctx:
            process = Chain('legacy_chain', port1, port2, port3,
                            description='some legacy chain', partition='legacy')

        tokens = ctx.tokens
        self.assertIn(AddTokenOp(AliasToken(process, 'legacy_chain')), tokens)
        self.assertIn(AddTokenOp(LabelToken(process, 'legacy_chain')), tokens)
        self.assertIn(AddTokenOp(DescriptionToken(process, 'some legacy chain')), tokens)
        self.assertIn(AddTokenOp(PartitionToken(process, 'legacy')), tokens)

        self.assertIn(AddTokenOp(ConnectionToken(port1, port2)), tokens)
        self.assertIn(AddTokenOp(ConnectionToken(port2, port3)), tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port1, process)), tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port2, process)), tokens)
        self.assertIn(AddTokenOp(ParentElementToken(port3, process)), tokens)

    def test_legacy_duplicate(self):
        with Context(self) as ctx:
            process = Duplicate('other chain')

        self.assertIn(AddTokenOp(ConnectionToken(process.out_duplicate, 'other chain')), ctx.tokens)
        self.assertIn(AddTokenOp(ParentElementToken(process.out_duplicate, process)), ctx.tokens)
