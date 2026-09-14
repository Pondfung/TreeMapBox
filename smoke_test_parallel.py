import sys
import multiprocessing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "core"))
from parallel_mft_scanner import ParallelMFTScanner


def main():
    s = ParallelMFTScanner()
    print("supported:", s.supported)
    print("scanning C:\\ ...")
    res = s.scan("C:/", lambda msg, cnt: print(f"  [{cnt}%] {msg}"))
    print("files:", len(res) if res else 0)
    print("first 5:", res[:5] if res else None)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
