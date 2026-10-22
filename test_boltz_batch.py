import json
import tempfile
import unittest
from pathlib import Path

from boltz_batch_core import read_seq, fingerprint, split_a3m, atomic_json
from boltz_batch_runner import Batch, Cancelled


class Inputs(unittest.TestCase):
    def test_multiline_complex_repeated_header(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "복합체.seq"
            file.write_text("\ufeff>same\nacde\nFG\n>same\nMK L\n", encoding="utf-8")
            records = read_seq(file)
            self.assertEqual([r["id"] for r in records], ["A", "B"])
            self.assertEqual([r["sequence"] for r in records], ["ACDEFG", "MKL"])
            changed = [dict(r) for r in records]
            changed[1]["sequence"] = "MKV"
            self.assertNotEqual(fingerprint(records), fingerprint(changed))

    def test_invalid_inputs(self):
        for text in ["ACDE", ">empty\n", ">x\nACD*", ">x\nACD1", ">x\nACDB", ">\nACD"]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                file = Path(temp) / "bad.seq"
                file.write_text(text)
                with self.assertRaises(ValueError):
                    read_seq(file)

    def test_paired_msa_blocks(self):
        text = ">101\nACD\n>hit1\nA-D\n\x00>102\nMKT\n>hit2\n---\n\x00"
        self.assertEqual(split_a3m(text, 2), [["ACD", "A-D"], ["MKT", "---"]])

    def test_msa_unknown_query_rejected(self):
        with self.assertRaises(ValueError):
            split_a3m(">999\nACD\n", 1)

    def test_resume_checks_actual_output_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            runner = Batch(temp, "")
            runner.result.mkdir()
            output = runner.result / "x_0.pdb"
            output.write_text("original")
            manifest = runner.result / "manifest.json"
            atomic_json(manifest, {"fingerprint": "abc", "rendered": True,
                                  "files": {"x_0.pdb": hashlib.sha256(output.read_bytes()).hexdigest()}})
            self.assertIsNotNone(runner.reusable(manifest, "abc"))
            self.assertIsNone(runner.reusable(manifest, "changed"))
            output.write_text("modified")
            self.assertIsNone(runner.reusable(manifest, "abc"))

    def test_stop_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "stop"
            runner = Batch(temp, "", marker)
            runner.check_cancel()
            marker.touch()
            with self.assertRaises(Cancelled):
                runner.check_cancel()

    def test_batch_continues_after_bad_file_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a_bad.seq").write_text("NOT_FASTA")
            (folder / "b_good.SEQ").write_text(">A\nACDE\n>B\nMKL\n")
            seen, events = [], []
            class ValidationBatch(Batch):
                def emit(self, kind, **data):
                    events.append({"kind": kind, **data})
                def one(self, source):
                    seen.append(source.name)
                    read_seq(source)
                    return "completed"
            runner = ValidationBatch(temp, "")
            self.assertEqual(runner.run(), 1)
            self.assertEqual(seen, ["a_bad.seq", "b_good.SEQ"])
            done = [e for e in events if e["kind"] == "finished"][0]
            self.assertEqual(done["counts"]["failed"], 1)
            self.assertEqual(done["counts"]["completed"], 1)
            self.assertFalse(runner.lock.exists())
            self.assertEqual(len(list((runner.result / "logs").glob("*.log"))), 3)


if __name__ == "__main__":
    unittest.main()
