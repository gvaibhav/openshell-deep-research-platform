import unittest

from spike.contract import StageManifest
from spike.restricted import render_restricted_manifests
from test_worker import manifest_dict


class RestrictedComparatorTests(unittest.TestCase):
    def test_same_worker_image_fixture_and_result_shape_with_narrow_relay_egress(self):
        manifest = StageManifest.from_dict(manifest_dict())
        image = "research-worker@sha256:" + "a" * 64
        objects = render_restricted_manifests(
            manifest,
            image_ref=image,
            worker_namespace="research-spike-workers",
            relay_namespace="research-spike-relay",
            relay_pod_ip="10.20.30.40",
            relay_pod_id="relay-a1",
            relay_port=8765,
            model_id="approved-model-v1",
        )
        config, policy, job = objects["items"]
        self.assertEqual(job["spec"]["template"]["spec"]["containers"][0]["image"], image)
        command = job["spec"]["template"]["spec"]["containers"][0]["command"]
        self.assertIn("spike.worker", command)
        self.assertIn("--claimed-mode", command)
        self.assertIn("restricted", command)
        self.assertIn("--result", command)
        self.assertIn("-", command)
        self.assertIn('"fixture_id": "aurora-v1"', config["data"]["stage.json"])
        self.assertFalse(job["spec"]["template"]["spec"]["automountServiceAccountToken"])
        self.assertIn({"name": "PYTHONPATH", "value": "/opt/spike"}, job["spec"]["template"]["spec"]["containers"][0]["env"])
        self.assertEqual(policy["spec"]["egress"][0]["ports"], [{"protocol": "TCP", "port": 8765}])
        self.assertEqual(policy["spec"]["egress"][0]["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "research-spike-relay")
        self.assertEqual(policy["spec"]["egress"][0]["to"][0]["podSelector"]["matchLabels"], {"app": "research-spike-model-relay", "research-spike.org/relay-instance": "relay-a1"})


if __name__ == "__main__":
    unittest.main()
