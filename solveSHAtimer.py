import hashlib
import math
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count

TARGET = "66c2edd163a7283b1e76ed401f910fd56abc4ce314dfe50f8195e8c5e1ec7994"
SALT = b"GC-PUZZLE-CALIBRATION-V1"
ITERS = 8570
DKLEN = 32

# Center of the search circle
C_LAT_MIN = 22.100
C_LON_MIN = 10.000
CENTER_LAT_DEG = 53 + C_LAT_MIN / 60.0
MAX_MILES = 2.0

# Miles per degree
MI_PER_DEG_LAT = 69.0547
MI_PER_DEG_LON = MI_PER_DEG_LAT * math.cos(math.radians(CENTER_LAT_DEG))

# Search box in thousandths of a minute (padded a touch beyond 2 mi)
LAT_LO, LAT_HI = 20300, 23900   # lat minutes * 1000
LON_LO, LON_HI = 7000, 13000    # lon minutes * 1000


def within_circle(lat_min, lon_min):
    dlat = (lat_min - C_LAT_MIN) / 60.0 * MI_PER_DEG_LAT
    dlon = (lon_min - C_LON_MIN) / 60.0 * MI_PER_DEG_LON
    return dlat * dlat + dlon * dlon <= MAX_MILES * MAX_MILES


def search_lat(lat_thousandths):
    lat_min = lat_thousandths / 1000.0
    for lon_t in range(LON_LO, LON_HI + 1):
        lon_min = lon_t / 1000.0
        if not within_circle(lat_min, lon_min):
            continue
        candidate = f"N 53\u00b0 {lat_min:06.3f} W 2\u00b0 {lon_min:06.3f}"
        h = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"),
                                SALT, ITERS, dklen=DKLEN).hex()
        if h == TARGET:
            return candidate
    return None


def fmt_duration(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d} ({seconds:.1f}s)"


def main():
    # Sanity check against the puzzle's known test vector
    test = "N 53\u00b0 22.111 W 2\u00b0 10.111"
    tv = hashlib.pbkdf2_hmac("sha256", test.encode("utf-8"), SALT, ITERS, dklen=DKLEN).hex()
    assert tv == "5a8d62ca8501772f7bd829941046aaa74e774deee5ac7ff52481dfc897a7d803", \
        f"Format/test-vector mismatch: {tv}"
    print("Test vector OK — format is correct.")

    start_wall = datetime.now()
    start_perf = time.perf_counter()
    print(f"Start:  {start_wall:%Y-%m-%d %H:%M:%S}")

    found = None
    lat_range = list(range(LAT_LO, LAT_HI + 1))
    with Pool(cpu_count()) as pool:
        done = 0
        for result in pool.imap_unordered(search_lat, lat_range, chunksize=4):
            done += 1
            if result:
                found = result
                pool.terminate()
                break
            if done % 100 == 0:
                print(f"...scanned {done}/{len(lat_range)} latitude rows", flush=True)

    end_wall = datetime.now()
    elapsed = time.perf_counter() - start_perf

    if found:
        print(f"\nFOUND: {found}")
    else:
        print("\nNo match in the searched box — widen LAT/LON bounds.")

    print(f"Start:  {start_wall:%Y-%m-%d %H:%M:%S}")
    print(f"Finish: {end_wall:%Y-%m-%d %H:%M:%S}")
    print(f"Total:  {fmt_duration(elapsed)}")


if __name__ == "__main__":
    main()