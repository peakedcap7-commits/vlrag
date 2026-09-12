"""上传生命周期幂等且不覆盖用户其他规则。"""

import unittest
from unittest.mock import Mock

from minio.commonconfig import ENABLED, Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from tools.init_minio import RULE_ID, configure_upload_expiry


class LifecycleTest(unittest.TestCase):
    def test_preserves_other_rules_and_replaces_own_rule(self):
        client = Mock()
        other = Rule(ENABLED, Filter(prefix="archive/"), "user-owned", expiration=Expiration(days=90))
        ours = Rule(ENABLED, Filter(prefix="uploads/"), RULE_ID, expiration=Expiration(days=3))
        client.get_bucket_lifecycle.return_value = LifecycleConfig([other, ours])
        configure_upload_expiry(client, "test")
        rules = client.set_bucket_lifecycle.call_args.args[1].rules
        self.assertEqual(len(rules), 2)
        self.assertIs(rules[0], other)
        self.assertEqual(rules[1].expiration.days, 1)
        self.assertEqual(rules[1].rule_filter.prefix, "uploads/")
        client.get_bucket_lifecycle.return_value = LifecycleConfig(rules)
        configure_upload_expiry(client, "test")
        self.assertEqual(len(client.set_bucket_lifecycle.call_args.args[1].rules), 2)

    def test_permission_failure_is_not_ignored(self):
        client = Mock()
        client.get_bucket_lifecycle.side_effect = S3Error("AccessDenied", "denied", "", "", "", None)
        with self.assertRaises(S3Error):
            configure_upload_expiry(client, "test")
        client.set_bucket_lifecycle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
