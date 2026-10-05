"""The one reviewed version of the Laya add-on: which package, which model, which exact bytes.

Everything the installer downloads is named here and checked against it. Moving to a newer Laya or model is a
change to this file, made on purpose, after reading what changed upstream.

The file list, sizes and hashes were read from the Hugging Face listing of the pinned commit. They have not been
checked against a downloaded copy: the first real install is that check, and it refuses to continue on any
mismatch (and prints the hash it saw, so the pin can be reviewed)."""
from __future__ import annotations

from dataclasses import dataclass

REPO = "convaiinnovations/laya-typed-decisions"        # Apache-2.0, ModernBERT-large, 421M parameters
REVISION = "1a793eb568e6718f15941d08f85432581df534e3"  # a commit, not a branch: its content cannot change
LAYA_VERSION = "0.3.26"                                 # the Python package that runs the model
WEIGHTS = "model.safetensors"                           # safetensors only: loading it cannot run code


@dataclass(frozen=True, slots=True)
class PinnedFile:
    path: str
    size: int
    git_blob: str            # git's own SHA-1 of the file, the listing's blob id; checked for every file
    sha256: str | None = None   # the listing gives a SHA-256 only for the large (LFS) file


FILES = (
    PinnedFile("encoder/config.json", 2084, "d4be4829750fb04c0aa8b9897c3ea827f76c0109"),
    PinnedFile(WEIGHTS, 842_609_220, "3fb9c9678050815e76d0c847115919d7871ace3e",
               "4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e"),
    PinnedFile("rl_agent_config.json", 847, "5f0e1d5f2366fe8ba2ff330dffaeed53b469e97e"),
    PinnedFile("tokenizer/tokenizer.json", 3_583_228, "2f4d8583e507b7466d2490e2d6c045647a822698"),
    PinnedFile("tokenizer/tokenizer_config.json", 337, "ed1ffabc2ce11120754705709569e365e46da71a"),
)
DOWNLOAD_BYTES = sum(f.size for f in FILES)
