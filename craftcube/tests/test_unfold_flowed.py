"""unfold_flowed oracle tests — expected outputs captured from
rcube_mime::unfold_flowed() on the reference Roundcube 1.7.5 pod
(k8s3 staging, 2026-11-03)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.util import unfold_flowed

C0 = ("The quick brown fox jumps over the lazy dog and keeps running beyond \r\n"
      "78....................\r\nsecond line\r\n\r\nnew para\r\n> quoted line")
C1 = " line starts with space\r\nFrom stuffed\r\n>quoted no space\r\n> quoted"
C2 = ("> flowed quote one \r\n> quote two \r\n>> deeper \r\n>> deeper2\r\nplain after quote")
C3 = "> \r\n>after blank quote"
C4 = "hello \r\nworld\r\n-- \r\nsig line one \r\nsig line two"
C5 = "a \nb\nc"
C6 = ("Le renard brun rapide saute par-dessus le chien paresseux et \r\ncontinue \r\nvers le lapin.")


def test_soft_fold_joins():
    assert unfold_flowed(C0) == (
        "The quick brown fox jumps over the lazy dog and keeps running beyond 78....................\r\n"
        "second line\r\n\r\nnew para\r\n> quoted line")


def test_delsp_strips_join_space():
    assert unfold_flowed(C0, delsp=True) == (
        "The quick brown fox jumps over the lazy dog and keeps running beyond78....................\r\n"
        "second line\r\n\r\nnew para\r\n> quoted line")


def test_space_stuffing_removed():
    assert unfold_flowed(C1) == (
        "line starts with space\r\nFrom stuffed\r\n>quoted no space\r\n> quoted")


def test_quote_levels():
    assert unfold_flowed(C2) == (
        "> flowed quote one quote two \r\n>> deeper deeper2\r\nplain after quote")
    assert unfold_flowed(C2, delsp=True) == (
        "> flowed quote onequote two \r\n>> deeperdeeper2\r\nplain after quote")


def test_blank_quote_guard():
    # previous line is only '> ' -> never joins
    assert unfold_flowed(C3) == "> \r\n>after blank quote"


def test_signature_marker_never_joins():
    assert unfold_flowed(C4) == (
        "hello world\r\n-- \r\nsig line one sig line two")
    assert unfold_flowed(C4, delsp=True) == (
        "helloworld\r\n-- \r\nsig line onesig line two")


def test_lone_lf_split():
    assert unfold_flowed(C5) == "a b\r\nc"


def test_delsp_multiline():
    assert unfold_flowed(C6) == (
        "Le renard brun rapide saute par-dessus le chien paresseux et continue vers le lapin.")
    assert unfold_flowed(C6, delsp=True) == (
        "Le renard brun rapide saute par-dessus le chien paresseux etcontinuevers le lapin.")
