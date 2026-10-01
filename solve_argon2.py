import math, os, time, sys
from datetime import datetime
from multiprocessing import Pool, cpu_count
from argon2 import low_level, extract_parameters
from argon2.exceptions import VerifyMismatchError

ENCODED = "$argon2id$v=19$m=50000,t=2,p=2$VkRLYjlPNGtkZm9EdnpsYw$Nw60b8bsy9AiFHDLrTfTx7W3Meb8gaVChWZU/uBomis"
ENCODED_B = ENCODED.encode("ascii")

# --- Origin (dummy coords) and search geometry (spherical model) ---
LAT_DEG, LON_DEG = 53, 2
C_LAT_MIN, C_LON_MIN = 21.555, 10.111
R = 6371000.0                 # mean Earth radius (m) -> matches their 1.85 m/step
MAX_M = 3218.688              # two statute miles
M_PER_MIN_LAT = 1853.0        # 1.853 m per 0.001'  => 1853 m per 1'
M_PER_MIN_LON = 1110.0        # 1.11  m per 0.001'  => 1110 m per 1' (approx, at 53N)

# Padded bounding box in thousandths of a minute
LAT_LO, LAT_HI = 19700, 23400
LON_LO_BOX, LON_HI_BOX = 7100, 13100

lat0 = math.radians(LAT_DEG + C_LAT_MIN / 60.0)
lon0 = math.radians(-(LON_DEG + C_LON_MIN / 60.0))

PROGRESS_FILE = "progress.txt"
RESULT_FILE = "FOUND.txt"
TOTAL_EST = 15_900_000        # for ETA only

def haversine_m(lat_min, lon_min):
    lat = math.radians(LAT_DEG + lat_min / 60.0)
    lon = math.radians(-(LON_DEG + lon_min / 60.0))
    dlat, dlon = lat - lat0, lon - lon0
    a = math.sin(dlat / 2) ** 2 + math.cos(lat0) * math.cos(lat) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def lon_window(lat_t):
    """Analytic lon span for this lat row, padded; haversine is the real gate."""
    dy = abs(lat_t / 1000.0 - C_LAT_MIN) * M_PER_MIN_LAT
    if dy > MAX_M:
        return None
    half_min = math.sqrt(MAX_M * MAX_M - dy * dy) / M_PER_MIN_LON
    lo = int(math.floor((C_LON_MIN - half_min) * 1000)) - 5
    hi = int(math.ceil((C_LON_MIN + half_min) * 1000)) + 5
    return max(lo, LON_LO_BOX), min(hi, LON_HI_BOX)

def check_lat_row(lat_t):
    win = lon_window(lat_t)
    if win is None:
        return (lat_t, None, 0)
    lo, hi = win
    lat_str = f"{lat_t // 1000:02d}.{lat_t % 1000:03d}"
    checked = 0
    for lon_t in range(lo, hi + 1):
        lon_min = lon_t / 1000.0
        if haversine_m(lat_t / 1000.0, lon_min) > MAX_M:
            continue
        lon_str = f"{lon_t // 1000:02d}.{lon_t % 1000:03d}"
        cand = f"N {LAT_DEG}\u00b0 {lat_str} W {LON_DEG}\u00b0 {lon_str}"
        checked += 1
        try:
            low_level.verify_secret(ENCODED_B, cand.encode("utf-8"), low_level.Type.ID)
            return (lat_t, cand, checked)      # match!
        except VerifyMismatchError:
            pass
    return (lat_t, None, checked)

def load_done():
    done = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    done.add(int(line))
    return done

def main():
    # Parameter sanity — proves the hash string parses to exactly the stated params.
    p = extract_parameters(ENCODED)
    assert (p.memory_cost, p.time_cost, p.parallelism, p.hash_len, p.salt_len) == \
           (50000, 2, 2, 32, 16), p
    # Determinism self-test — proves the Argon2 plumbing is wired correctly.
    a = low_level.hash_secret_raw(b"x", b"0123456789abcdef", time_cost=2,
                                  memory_cost=50000, parallelism=2, hash_len=32,
                                  type=low_level.Type.ID, version=19)
    b = low_level.hash_secret_raw(b"x", b"0123456789abcdef", time_cost=2,
                                  memory_cost=50000, parallelism=2, hash_len=32,
                                  type=low_level.Type.ID, version=19)
    assert a == b
    print("Params + Argon2 wiring OK. Salt =", "VDKb9O4kdfoDvzlc")

    workers = int(os.environ.get("WORKERS", 4))   # see note below for the M4
    all_rows = [r for r in range(LAT_LO, LAT_HI + 1) if lon_window(r) is not None]
    done = load_done()
    todo = [r for r in all_rows if r not in done]
    print(f"Rows total {len(all_rows)}, remaining {len(todo)}, workers {workers}")

    start_wall = datetime.now()
    t0 = time.perf_counter()
    print(f"Start:  {start_wall:%Y-%m-%d %H:%M:%S}")

    found = None
    session_checked = 0
    pf = open(PROGRESS_FILE, "a")
    with Pool(workers) as pool:
        for lat_t, res, n in pool.imap_unordered(check_lat_row, todo, chunksize=1):
            if res:
                found = res
                with open(RESULT_FILE, "w") as rf:
                    rf.write(res + "\n")
                pool.terminate()
                break
            pf.write(f"{lat_t}\n"); pf.flush()      # checkpoint this row
            session_checked += n
            if session_checked % 20000 < n:
                el = time.perf_counter() - t0
                rate = session_checked / el if el else 0
                eta = (TOTAL_EST - session_checked) / rate / 3600 if rate else 0
                print(f"  ~{session_checked:,} checked | {rate:5.1f} h/s "
                      f"| ETA ~{eta:4.1f} h", flush=True)
    pf.close()

    el = time.perf_counter() - t0
    end_wall = datetime.now()
    print(f"\n{'FOUND: ' + found if found else 'No match in searched set.'}")
    h, r = divmod(int(el), 3600)
    print(f"Start:  {start_wall:%Y-%m-%d %H:%M:%S}")
    print(f"Finish: {end_wall:%Y-%m-%d %H:%M:%S}")
    print(f"Total:  {h:02d}:{r//60:02d}:{r%60:02d} ({el:.1f}s, {session_checked:,} this run)")

if __name__ == "__main__":
    main()