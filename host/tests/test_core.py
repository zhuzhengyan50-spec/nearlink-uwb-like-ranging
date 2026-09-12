import os
import tempfile
import unittest

import numpy as np

from algorithm import GnUlsPositioning
from gui.services.dataset_export_service import DatasetExportConfig, export_dataset
from gui.services.sensing_state_service import SensingStateService
from gui.services.iq_pair_store import IQPairStore
from parse_iq_raw import StreamParser, extract_iq_arrays


class PositioningTests(unittest.TestCase):
    def test_solver_accepts_more_than_four_anchors(self):
        anchors = np.array([
            [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [5.0, 15.0], [15.0, 5.0],
        ])
        expected = np.array([4.0, 6.0])
        distances = np.linalg.norm(anchors - expected, axis=1)
        solved = GnUlsPositioning(anchors).solve(distances)
        np.testing.assert_allclose(solved, expected, atol=1e-6)

    def test_distance_count_must_match_anchor_count(self):
        solver = GnUlsPositioning([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        with self.assertRaises(ValueError):
            solver.solve([1.0, 1.0])


class StreamParserTests(unittest.TestCase):
    def test_mode3_iq_decoding_is_fixed(self):
        payload = bytes([
            2, 190, 1, 0, 10, 0, 0, 0,
            1, 0, 255, 7,
            0, 4, 255, 3,
            0, 0, 0, 0,
        ])
        i_values, q_values = extract_iq_arrays(payload.hex(" "))
        self.assertEqual(i_values, [1.0, -1024.0])
        self.assertEqual(q_values, [-1.0, 1023.0])

    def test_collect_protocol_accepts_arbitrary_anchor_id(self):
        parser = StreamParser()
        parser.feed_line(
            "COLLECT_SAMPLE_META anchor=7 client=3 conn_id=2 sdk_dist_mm=1234 sdk_rssi=-51 "
            "local_timestamp=10 remote_timestamp=11 local_rssi=190 remote_rssi=188",
            now_ts=1.0,
        )
        payload = "02BE01000A0000000100020003000400000000"
        parser.feed_line(f"COLLECT_LOCAL_IQ seq=0 hex={payload}", now_ts=1.01)
        parser.feed_line(f"COLLECT_REMOTE_IQ seq=0 hex={payload}", now_ts=1.02)
        result = parser.flush_collect_if_idle(now_ts=1.20)

        self.assertIsNotNone(result)
        self.assertEqual(result.distances["A7"], 1.234)
        self.assertEqual(result.rssis["A7"], -51)
        self.assertEqual(len(result.iq_packets), 2)

    def test_legacy_protocol_is_ignored(self):
        parser = StreamParser()
        self.assertIsNone(parser.feed_line("FINAL_DATA: A1=1.000"))
        self.assertIsNone(parser.feed_line("client IQ RAW frame type:0x12 len:336"))
        self.assertIsNone(parser.flush())


class IQPairStoreTests(unittest.TestCase):
    def test_session_is_lazy_and_records_can_be_read_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = IQPairStore(temp_dir)
            path = store.get_current_path()
            self.assertFalse(os.path.exists(path))

            store.append_records([{
                "timestamp": 1.0,
                "anchor_id": "A1",
                "client_key": "client3",
                "anchor_packet": {"i_values": [1], "q_values": [2], "conn_id": 7},
                "client_packet": {"i_values": [3], "q_values": [4], "conn_id": 7},
                "cfr": {"blockage_score": 0.2, "dynamic_score": 0.3, "link_reliability_score": 0.76},
            }])
            records = store.read_records()
            store.close()

            self.assertTrue(os.path.exists(path))
            self.assertEqual(records[0]["schema"], "iq_pair_research_v3")
            self.assertEqual(records[0]["local_iq"]["i"], [3])
            self.assertEqual(records[0]["remote_iq"]["q"], [2])

            outputs = export_dataset(
                records,
                os.path.join(temp_dir, "export"),
                "session",
                DatasetExportConfig(scene_label="LOS", anchor_configs={"A1": {}}),
                calibers={"raw": True, "features": False, "time_features": False},
            )
            self.assertEqual(len(outputs), 1)
            self.assertTrue(os.path.exists(outputs[0][1]))


class SensingStateTests(unittest.TestCase):
    @staticmethod
    def _record(timestamp, anchor_id="A1", client_key="client3", dynamic=0.2):
        return {
            "timestamp": timestamp,
            "anchor_id": anchor_id,
            "client_key": client_key,
            "client_label": client_key,
            "cfr": {
                "blockage_score": 0.4,
                "dynamic_score": dynamic,
                "link_reliability_score": 0.68,
            },
        }

    def test_single_link_sensing_does_not_require_a_position(self):
        state = SensingStateService()
        samples = state.ingest_records([self._record(1.0)])

        self.assertEqual(len(samples), 1)
        self.assertEqual(state.link_keys(), [("A1", "client3")])
        self.assertAlmostEqual(state.latest("A1", "client3").dynamic_score, 0.2)

    def test_links_are_separated_by_anchor_and_client(self):
        state = SensingStateService()
        state.ingest_records([
            self._record(1.0, "A2", "client4"),
            self._record(2.0, "A1", "client3"),
        ])

        self.assertEqual(state.link_keys(), [("A1", "client3"), ("A2", "client4")])
        self.assertEqual(state.clients(), [("client3", "client3"), ("client4", "client4")])

    def test_history_is_bounded(self):
        state = SensingStateService(history_size=2)
        state.ingest_records([
            self._record(1.0, dynamic=0.1),
            self._record(2.0, dynamic=0.2),
            self._record(3.0, dynamic=0.3),
        ])

        history = state.history("A1", "client3")
        self.assertEqual([sample.timestamp for sample in history], [2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
