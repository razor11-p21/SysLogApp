# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import unittest
from syslogapp.sorting import endpoint_key, network_sort_key, log_sort_key, process_fields, network_display_row


class SortingTests(unittest.TestCase):
    def test_ip_octets_and_ports_sort_numerically(self):
        endpoints = ['192.168.1.10:9', '192.168.1.2:443', '192.168.1.2:80', '192.168.1.2:9']
        self.assertEqual(sorted(endpoints, key=endpoint_key), [
            '192.168.1.2:9', '192.168.1.2:80', '192.168.1.2:443', '192.168.1.10:9'])

    def test_ipv6_scope_and_wildcard_endpoints_are_comparable(self):
        endpoints = ['[2001:db8::10]:443', '[2001:db8::2]:80', '[fe80::1%eth2]:9',
                     '[fe80::1%eth10]:9', '*:*', '127.0.0.1%lo:53', 'unknown:service']
        ordered = sorted(endpoints, key=endpoint_key)
        self.assertLess(ordered.index('[2001:db8::2]:80'), ordered.index('[2001:db8::10]:443'))
        self.assertLess(ordered.index('[fe80::1%eth2]:9'), ordered.index('[fe80::1%eth10]:9'))

    def test_state_sort_has_numeric_endpoint_ties(self):
        rows = [('TCP', 'LISTEN', '0.0.0.0', '443', '*', '*', '—', ''),
                ('TCP', 'ESTAB', '127.0.0.1', '10', '127.0.0.1', '11', '—', ''),
                ('UDP', 'UNCONN', '0.0.0.0', '53', '*', '*', '—', ''),
                ('TCP', 'LISTEN', '0.0.0.0', '80', '*', '*', '—', '')]
        ordered = sorted(rows, key=lambda row: network_sort_key(row, 1))
        self.assertEqual([row[1] for row in ordered], ['ESTAB', 'LISTEN', 'LISTEN', 'UNCONN'])
        self.assertEqual(ordered[1][3], '80')
        self.assertEqual(sorted(rows[::-1], key=lambda row: network_sort_key(row, 1)), ordered)

    def test_time_sort_uses_full_date_and_microseconds(self):
        older = ['2025-12-31 23:59:59', 'test', 'Info', 'message', 6, {}]
        newer = ['2026-01-01 00:00:00', 'test', 'Info', 'message', 6, {}]
        self.assertLess(log_sort_key(older, 0), log_sort_key(newer, 0))
        a = [*newer[:5], {'__REALTIME_TIMESTAMP': '2000001'}]
        b = [*newer[:5], {'__REALTIME_TIMESTAMP': '2000002'}]
        self.assertLess(log_sort_key(a, 0), log_sort_key(b, 0))

    def test_severity_is_priority_order_not_alphabetical(self):
        rows = [['2026-01-01 12:00:00', 'test', level, '', priority, {}]
                for level, priority in [('Debug', 7), ('Emergency', 0), ('Error', 3), ('Warning', 4)]]
        self.assertEqual([row[2] for row in sorted(rows, key=lambda row: log_sort_key(row, 2))],
                         ['Emergency', 'Error', 'Warning', 'Debug'])

    def test_process_display_is_compact_and_pids_sort_numerically(self):
        a = 'users:(("worker",pid=12,fd=4))'
        b = 'users:(("worker",pid=2,fd=3))'
        self.assertEqual(process_fields(a), ('12', 'worker'))
        self.assertLess(network_sort_key(network_display_row(dict(protocol='TCP',state='ESTAB',local='*:1',peer='*:2',process=b)), 6),
                        network_sort_key(network_display_row(dict(protocol='TCP',state='ESTAB',local='*:1',peer='*:2',process=a)), 6))


    def test_local_and_remote_ports_sort_independently_across_hosts(self):
        rows = [('TCP','ESTAB',f'10.0.0.{i}',str(port),'::1',str(port),'—','')
                for i, port in [(1,443),(2,9),(3,80)]]
        for column in (3,5):
            self.assertEqual([row[column] for row in sorted(rows, key=lambda row: network_sort_key(row,column))],
                             ['9','80','443'])

    def test_split_addresses_preserve_ipv6_scope_and_compact_process(self):
        row = network_display_row(dict(protocol='TCP',state='ESTAB',local='[fe80::1%eth0]:443',
                                       peer='[2001:db8::1]:80',process='users:(("ssh",pid=12,fd=3))'))
        self.assertEqual(row[2:8], ('fe80::1%eth0','443','2001:db8::1','80','12','ssh'))

    def test_multiple_process_owners_and_extended_names_have_stable_sort_order(self):
        raw = 'users:(("worker",pid=12,fd=3),("helper",pid=2,fd=4))'
        row = dict(protocol='TCP',state='ESTAB',local='*:1',peer='*:2',process=raw)
        compact = network_display_row(row)
        extended = network_display_row(row, extended=True)
        self.assertEqual(compact[6:8], ('2, 12','helper, worker'))
        self.assertEqual(extended[7], raw)
        self.assertEqual(network_sort_key(compact,7),network_sort_key(extended,7))

    def test_long_values_are_not_retained_by_global_caches(self):
        from syslogapp import sorting
        sorting._cached_natural_key.cache_clear()
        value='worker-'+'X'*8192+'12'
        expected=sorting.natural_key(value)
        self.assertEqual(sorting._cached_natural_key.cache_info().currsize,0)
        self.assertEqual(expected,sorting.natural_key(value.lower()))
        sorting._cached_process_fields.cache_clear()
        raw=f'users:(("{value}",pid=12,fd=3))'
        self.assertEqual(sorting.process_fields(raw),('12',value))
        self.assertEqual(sorting._cached_process_fields.cache_info().currsize,0)
