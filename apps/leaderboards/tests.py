import subprocess
from pathlib import Path

MEM_ADDR_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check-mem-addr.sh"


def run_mem_addr_checker(*mem_addrs):
    return subprocess.run(
        ["bash", str(MEM_ADDR_CHECKER), *mem_addrs],
        capture_output=True,
        text=True,
        check=False,
    )


def test_checker_accepts_a_valid_leaderboard():
    result = run_mem_addr_checker("STA:0xH0001=1::CAN:0=1::SUB:0xH0002=1::VAL:M:1=1")
    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_rejects_a_malformed_leaderboard():
    result = run_mem_addr_checker("STA:0xH01=::VAL:M:1=1")
    assert result.returncode == 1, result.stdout + result.stderr
