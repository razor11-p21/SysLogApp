# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from unittest.mock import patch
from syslogapp import overview as o

MEMINFO = ('MemTotal: 1048576 kB\nMemFree: 1024 kB\nMemAvailable: 786432 kB\n'
           'Cached: 500000 kB\nSwapTotal: 2097152 kB\nSwapFree: 1361100 kB\n')


class MemoryClarityTests(unittest.TestCase):
    def test_available_and_used_estimate_do_not_confuse_free_ram_with_available(self):
        result = o.memory_snapshot(MEMINFO)
        self.assertEqual(result['total'], 1024**3)
        self.assertEqual(result['available'], 768 * 1024**2)
        self.assertEqual(result['used'], 256 * 1024**2)
        self.assertEqual(result['swap_used'], (2097152 - 1361100) * 1024)
        self.assertIsNone(result['ram_error'])
        self.assertIsNone(result['swap_error'])

    def test_one_meminfo_read_per_collection(self):
        with patch.object(o, 'read_text', return_value=MEMINFO) as read:
            o.memory_snapshot()
        read.assert_called_once_with('/proc/meminfo')

    def test_zero_swap_is_disabled_not_unavailable(self):
        result = o.memory_snapshot(MEMINFO.replace('2097152', '0').replace('1361100', '0'))
        self.assertEqual(result['swap_total'], 0)
        self.assertEqual(result['swap_used'], 0)
        self.assertIsNone(result['swap_error'])

    def test_missing_ram_or_swap_keeps_the_other_check_available(self):
        result = o.memory_snapshot('SwapTotal: 10 kB\nSwapFree: 5 kB\n')
        self.assertIsNotNone(result['ram_error'])
        self.assertEqual(result['swap_used'], 5120)
        result = o.memory_snapshot('MemTotal: 1000 kB\nMemAvailable: 750 kB\n')
        self.assertIsNotNone(result['swap_error'])
        self.assertEqual(result['used'], 250 * 1024)

    def test_inconsistent_or_malformed_values_are_not_zero_usage(self):
        for source in ('MemTotal: 10 kB\nMemAvailable: 20 kB\n',
                       'MemTotal: -10 kB\nMemAvailable: 0 kB\n',
                       'MemTotal: 10 MB\nMemAvailable: 1 kB\n',
                       'MemTotal: bad kB\nMemAvailable: 1 kB\n'):
            result = o.memory_snapshot(source)
            self.assertIsNotNone(result['ram_error'])
            self.assertIsNone(result['used'])
        result = o.memory_snapshot('SwapTotal: 10 kB\nSwapFree: 20 kB\n')
        self.assertIsNotNone(result['swap_error'])
        self.assertIsNone(result['swap_used'])

    def test_unreadable_meminfo_is_explicitly_unavailable(self):
        with patch.object(o, 'read_text', side_effect=PermissionError('fixture denied')):
            result = o.memory_snapshot()
        self.assertIn('denied', result['ram_error'])
        self.assertIn('denied', result['swap_error'])
        self.assertIsNone(result['total'])
        self.assertIsNone(result['swap_used'])

    def test_snapshot_labels_estimated_ram_and_occupied_swap(self):
        memory = o.memory_snapshot(MEMINFO)
        with patch.object(o, 'memory_snapshot', return_value=memory), \
             patch.object(o, 'filesystem_snapshot', return_value=dict(items=[], error='fixture')), \
             patch.object(o, 'failed_services', return_value=dict(items=[], limited=False, error=None)), \
             patch.object(o, 'reboot_status', return_value=dict(state='not_reported', message='No marker')):
            result = o.snapshot()
        rows = {name:value for name,value,_color in result['rows']}
        self.assertIn('used (estimate)', rows['Memory'])
        self.assertIn('available for applications', rows['Available RAM'])
        self.assertIn('occupied', rows['Swap'])
        self.assertEqual(result['memory'], memory)
