import msgpack


class TestMsgpackSerialization:
    def test_round_trip_dict(self):
        data = {"ticker": "SPX", "price": 4.80, "action": "BUY", "quantity": 1}
        packed = msgpack.packb(data, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)
        assert unpacked == data

    def test_round_trip_nested(self):
        data = {
            "trade": {"id": "abc", "actions": [{"type": "BUY"}]},
            "meta": {"user_id": "u1"},
        }
        packed = msgpack.packb(data, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)
        assert unpacked == data

    def test_handles_none_values(self):
        data = {"key": None, "list": [None, 1, "a"]}
        packed = msgpack.packb(data, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)
        assert unpacked == data

    def test_binary_smaller_than_json(self):
        import json

        data = {
            "ticker": "SPX",
            "strike": 6940.0,
            "option_type": "CALL",
            "price": 4.80,
            "expiration": "2026-02-20",
        }
        json_bytes = json.dumps(data).encode("utf-8")
        msgpack_bytes = msgpack.packb(data, use_bin_type=True)
        assert len(msgpack_bytes) < len(json_bytes)

    def test_handles_unicode(self):
        data = {"name": "test unicode: \u00e9\u00e8\u00ea"}
        packed = msgpack.packb(data, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)
        assert unpacked == data
